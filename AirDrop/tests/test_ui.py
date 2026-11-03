"""Automated unit and integration tests for UI components, application services, and event handling."""

import os
from pathlib import Path
import queue
import shutil
import socket
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from src.protocol import AirDropError
from src.receiver import Receiver
from src.registry import DeviceState, UnifiedDevice
from src.security import SecurityManager
from src.services import (
    DiscoveryService,
    IncomingTransferRequest,
    ReceiverService,
    SecurityService,
    TransferProgress,
    TransferService,
)
from src.ui import AirDropApp


class TestApplicationServices(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_svc_test_")
        self.dest_dir = Path(self.temp_dir) / "received"
        self.dest_dir.mkdir(parents=True)
        self.sec_mgr = SecurityManager(base_dir=Path(self.temp_dir) / "sec")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_discovery_service_lifecycle(self):
        changed_event = threading.Event()
        discovered_devs: list[UnifiedDevice] = []

        def on_change(devs):
            discovered_devs.clear()
            discovered_devs.extend(devs)
            changed_event.set()

        svc = DiscoveryService(enable_ble=False, on_peers_changed=on_change)
        try:
            svc.start()
            # Register a mock device in its registry
            svc.registry.register_mdns(
                node_id="mock_dev_01",
                display_name="MockPeer",
                addresses=["192.168.1.99"],
                port=5001,
                service_name="MockPeer._airdrop-file._tcp.local.",
            )

            # Wait for callback notification
            changed_event.wait(timeout=2.0)
            self.assertTrue(changed_event.is_set())
            self.assertEqual(len(svc.get_devices()), 1)
            self.assertEqual(svc.get_devices()[0].display_name, "MockPeer")
        finally:
            svc.stop()

    def test_receiver_service_approval_flow(self):
        received_requests: list[IncomingTransferRequest] = []

        def on_req(req: IncomingTransferRequest):
            received_requests.append(req)

        svc = ReceiverService(
            dest_dir=self.dest_dir,
            port=0,
            use_tls=False,
            security_manager=self.sec_mgr,
            on_incoming_request=on_req,
        )

        req = IncomingTransferRequest(
            request_id="req1",
            filename="document.pdf",
            filesize=1024 * 1024,
            sender_name="Alice",
            sender_node_id="alice01",
        )

        self.assertEqual(req.formatted_size, "1.00 MiB")

        # Test approving request
        svc.respond_to_request(req, approve=True)
        self.assertTrue(req.approved)
        self.assertTrue(req.response_event.is_set())

        # Test declining request
        req2 = IncomingTransferRequest(
            request_id="req2",
            filename="unwanted.exe",
            filesize=500,
            sender_name="Bob",
            sender_node_id="bob01",
        )
        svc.respond_to_request(req2, approve=False)
        self.assertFalse(req2.approved)

    def test_transfer_service_with_progress_and_completion(self):
        """Test TransferService executes transfer in background and invokes progress and complete callbacks."""
        receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            use_tls=False,
            advertise=False,
            enable_ble=False,
        )
        r_thread = threading.Thread(target=receiver.start, daemon=True)
        r_thread.start()

        start = time.time()
        while receiver.active_port is None and (time.time() - start < 5.0):
            time.sleep(0.01)

        port = receiver.active_port

        try:
            # Create test file
            src_file = Path(self.temp_dir) / "test_svc.bin"
            data = os.urandom(256 * 1024)  # 256 KiB
            src_file.write_bytes(data)

            target_dev = UnifiedDevice(
                node_id="r1",
                display_name="LocalReceiver",
                state=DeviceState.REACHABLE,
                ip_address="127.0.0.1",
                port=port,
            )

            progress_reports: list[TransferProgress] = []
            completed_files: list[str] = []
            finished_event = threading.Event()

            svc = TransferService(use_tls=False)
            svc.send_files_async(
                files=[src_file],
                device=target_dev,
                on_progress=progress_reports.append,
                on_completed=lambda fn, m: completed_files.append(fn),
                on_all_finished=finished_event.set,
            )

            finished_event.wait(timeout=5.0)
            self.assertTrue(finished_event.is_set())
            self.assertIn("test_svc.bin", completed_files)
            self.assertGreater(len(progress_reports), 0)

            last_prog = progress_reports[-1]
            self.assertEqual(last_prog.bytes_transferred, len(data))
            self.assertEqual(last_prog.fraction, 1.0)
            self.assertTrue((self.dest_dir / "test_svc.bin").exists())

        finally:
            receiver.stop()
            r_thread.join(timeout=2.0)

    def test_transfer_service_cancellation(self):
        """Test canceling an active transfer cleanly unlinks partial files."""
        receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            use_tls=False,
            advertise=False,
            enable_ble=False,
        )
        r_thread = threading.Thread(target=receiver.start, daemon=True)
        r_thread.start()

        start = time.time()
        while receiver.active_port is None and (time.time() - start < 5.0):
            time.sleep(0.01)

        port = receiver.active_port

        try:
            # Create a larger 2 MiB file
            src_file = Path(self.temp_dir) / "cancel_test.bin"
            src_file.write_bytes(os.urandom(2 * 1024 * 1024))

            target_dev = UnifiedDevice(
                node_id="r1",
                display_name="LocalReceiver",
                state=DeviceState.REACHABLE,
                ip_address="127.0.0.1",
                port=port,
            )

            error_captured: list[Exception] = []
            finished_event = threading.Event()

            svc = TransferService(use_tls=False)

            def progress_hook(prog: TransferProgress):
                # Trigger cancellation on first chunk
                if prog.bytes_transferred > 0:
                    svc.cancel()

            svc.send_files_async(
                files=[src_file],
                device=target_dev,
                on_progress=progress_hook,
                on_error=lambda fn, err: error_captured.append(err),
                on_all_finished=finished_event.set,
            )

            finished_event.wait(timeout=5.0)
            self.assertTrue(finished_event.is_set())
            self.assertGreater(len(error_captured), 0)
            self.assertIn("cancelled", str(error_captured[0]).lower())

            # Allow receiver thread to finish processing connection and cleanup
            start_wait = time.time()
            while receiver._active_transfers > 0 and (time.time() - start_wait < 3.0):
                time.sleep(0.05)
            time.sleep(0.1)

            # Verify destination file does NOT exist and no .part files remain
            self.assertFalse((self.dest_dir / "cancel_test.bin").exists())
            self.assertEqual(len(list(self.dest_dir.glob("*.part"))), 0)

        finally:
            receiver.stop()
            r_thread.join(timeout=2.0)


class TestAirDropAppUI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_ui_test_")
        self.root = tk.Tk()
        self.root.withdraw()  # Headless mode for testing

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_app_initialization_and_widgets(self):
        app = AirDropApp(
            root=self.root,
            dest_dir=Path(self.temp_dir) / "received",
            port=5993,
            use_tls=False,
        )

        try:
            # Verify widgets exist
            self.assertIsNotNone(app.device_tree)
            self.assertIsNotNone(app.file_listbox)
            self.assertIsNotNone(app.send_btn)
            self.assertIsNotNone(app.progress_bar)
            self.assertIsNotNone(app.status_label)

            # Test updating device table
            dev1 = UnifiedDevice(
                node_id="ui_node_01",
                display_name="Office-Mac",
                state=DeviceState.REACHABLE,
                sources={"mDNS", "BLE"},
                ip_address="192.168.1.55",
                port=5001,
                rssi=-58,
            )
            app._update_device_table([dev1])

            items = app.device_tree.get_children()
            self.assertEqual(len(items), 1)
            vals = app.device_tree.item(items[0], "values")
            self.assertEqual(vals[0], "Office-Mac")
            self.assertEqual(vals[1], "REACHABLE")
            self.assertEqual(vals[2], "mDNS+BLE")

            # Test file listbox updates
            dummy_file = Path(self.temp_dir) / "doc.txt"
            dummy_file.write_text("UI file queue test")
            app.selected_files = [dummy_file]
            app.file_listbox.insert(tk.END, "doc.txt (18 B)")
            app._update_total_size()

            self.assertIn("1 file(s) selected", app.total_size_label.cget("text"))

            # Test progress UI update
            prog = TransferProgress(
                filename="doc.txt",
                bytes_transferred=500,
                total_bytes=1000,
                fraction=0.5,
                throughput_bps=1024 * 1024,
                throughput_str="1.00 MiB/s (8.39 Mbps)",
                eta_seconds=0.5,
            )
            app._update_progress_ui(prog)
            self.assertEqual(app.progress_bar["value"], 50)
            self.assertIn("50%", app.status_label.cget("text"))

        finally:
            app.on_close()


if __name__ == "__main__":
    unittest.main()
