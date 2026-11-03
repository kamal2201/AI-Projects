"""Tests for Direct Wi-Fi transport, LAN fallback, connection diagnostics, and failure handling."""

import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from src.benchmark import (
    BenchmarkResult,
    format_benchmark_table,
    run_local_benchmark_matrix,
    run_single_benchmark,
)
from src.file_io import compute_file_sha256
from src.protocol import AirDropError
from src.receiver import Receiver
from src.sender import Sender
from src.transport import (
    DirectWifiManager,
    DirectWifiTransport,
    FailoverTransportClient,
    LanTcpTransport,
    TransportConnection,
    TransportType,
)


class TestTransportPrimitives(unittest.TestCase):
    def test_transport_connection_context_manager(self):
        s1, s2 = socket.socketpair()
        try:
            conn = TransportConnection(
                sock=s1,
                transport_type=TransportType.LOOPBACK,
                remote_host="127.0.0.1",
                remote_port=5001,
            )
            with conn:
                conn.send(b"ping")
                data = s2.recv(4)
                self.assertEqual(data, b"ping")
                s2.sendall(b"pong")
                received = conn.receive(4)
                self.assertEqual(received, b"pong")
            self.assertTrue(s1._closed)
        finally:
            s2.close()

    def test_platform_direct_support_detection(self):
        support = DirectWifiManager.get_platform_support()
        self.assertIn("platform", support)
        self.assertIn("supports_awdl_public", support)
        self.assertFalse(support["supports_awdl_public"], "AWDL must not be claimed as public!")
        guide = DirectWifiManager.get_setup_guide()
        self.assertIsInstance(guide, str)
        self.assertGreater(len(guide), 20)


class TestFailoverTransport(unittest.TestCase):
    def setUp(self):
        self.dest_dir = tempfile.mkdtemp(prefix="airdrop_trans_dest_")
        self.src_dir = tempfile.mkdtemp(prefix="airdrop_trans_src_")

        # Start standard receiver
        self.receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            advertise=False,
            enable_ble=False,
        )
        self.recv_thread = threading.Thread(target=self.receiver.start, daemon=True)
        self.recv_thread.start()

        start = time.time()
        while self.receiver.active_port is None and (time.time() - start < 5.0):
            time.sleep(0.01)

        self.lan_port = self.receiver.active_port
        self.assertIsNotNone(self.lan_port)

    def tearDown(self):
        self.receiver.stop()
        self.recv_thread.join(timeout=2.0)
        shutil.rmtree(self.dest_dir, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def test_direct_wifi_success(self):
        """When direct endpoint is available, transfer uses DIRECT_WIFI transport."""
        # Point direct_endpoint to the active receiver port
        client = FailoverTransportClient(direct_timeout=1.0)
        conn, logs = client.connect(
            lan_endpoint=("127.0.0.1", self.lan_port),
            direct_endpoint=("127.0.0.1", self.lan_port),
            prefer_direct=True,
        )
        try:
            self.assertEqual(conn.transport_type, TransportType.DIRECT_WIFI)
            self.assertTrue(any("Connected via Direct Wi-Fi" in line for line in logs))
        finally:
            conn.close()

    def test_direct_wifi_failure_falls_back_to_lan_tcp(self):
        """When direct endpoint is unavailable, logs reason and falls back to LAN TCP."""
        # Use an unused port for direct endpoint (e.g. 59998)
        unused_port = 59998
        client = FailoverTransportClient(direct_timeout=0.5)

        conn, logs = client.connect(
            lan_endpoint=("127.0.0.1", self.lan_port),
            direct_endpoint=("127.0.0.1", unused_port),
            prefer_direct=True,
        )
        try:
            # Fallback should result in successful connection via LAN_TCP / LOOPBACK
            self.assertIn(conn.transport_type, (TransportType.LAN_TCP, TransportType.LOOPBACK))
            # Verify failure reason is captured in logs
            failure_logged = any(
                "Direct Wi-Fi connection to 127.0.0.1:59998 failed" in log for log in logs
            )
            self.assertTrue(failure_logged, f"Failure reason was not logged: {logs}")
            fallback_logged = any("Connected via LAN TCP" in log for log in logs)
            self.assertTrue(fallback_logged, f"Fallback was not logged: {logs}")
        finally:
            conn.close()

    def test_sender_end_to_end_with_direct_fallback(self):
        """Sender attempts direct connection, fails over to LAN, and completes file transfer."""
        test_file = Path(self.src_dir) / "fallback_test.txt"
        test_file.write_text("Testing Direct Wi-Fi failover to LAN TCP transport!\n")

        # Configure sender with unreachable direct host to trigger fallback
        sender = Sender(
            host="127.0.0.1",
            port=self.lan_port,
            direct_host="127.0.0.1",
            direct_port=59997,  # Unused port
            prefer_direct=True,
            timeout=5.0,
        )

        result = sender.send_file(test_file, precompute_sha256=True)

        self.assertIn(result["transport_type"], (TransportType.LAN_TCP.value, TransportType.LOOPBACK.value))
        self.assertTrue(any("failed" in log for log in result["transport_logs"]))

        # Verify file received and intact
        dest_file = Path(self.dest_dir) / "fallback_test.txt"
        self.assertTrue(dest_file.exists())
        self.assertEqual(compute_file_sha256(test_file), compute_file_sha256(dest_file))

    def test_both_transports_fail_raises_airdrop_error(self):
        """When both direct and LAN endpoints are unreachable, an AirDropError is raised."""
        client = FailoverTransportClient(direct_timeout=0.2, lan_timeout=0.2)
        with self.assertRaises(AirDropError) as ctx:
            client.connect(
                lan_endpoint=("127.0.0.1", 59996),
                direct_endpoint=("127.0.0.1", 59995),
            )
        self.assertIn("All transports failed", str(ctx.exception))


class TestDisconnectionAndAtomicIntegrity(unittest.TestCase):
    def setUp(self):
        self.dest_dir = tempfile.mkdtemp(prefix="airdrop_disc_dest_")
        self.receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            timeout=2.0,
            advertise=False,
            enable_ble=False,
        )
        self.recv_thread = threading.Thread(target=self.receiver.start, daemon=True)
        self.recv_thread.start()

        start = time.time()
        while self.receiver.active_port is None and (time.time() - start < 5.0):
            time.sleep(0.01)

        self.port = self.receiver.active_port

    def tearDown(self):
        self.receiver.stop()
        self.recv_thread.join(timeout=2.0)
        shutil.rmtree(self.dest_dir, ignore_errors=True)

    def test_mid_transfer_disconnection_cleans_temporary_file(self):
        """Disconnection mid-transfer must never leave partial or corrupt files."""
        from src.protocol import encode_header, HEADER_PREFIX_FORMAT
        import json
        import struct

        # Connect directly
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(("127.0.0.1", self.port))

        # Declare a 2 MB file
        filesize = 2 * 1024 * 1024
        header_bytes = encode_header("interrupted_large.bin", filesize)
        sock.sendall(header_bytes)

        # Send only 128 KiB
        sock.sendall(os.urandom(128 * 1024))

        # Abruptly close socket (simulating walk out of Wi-Fi range)
        sock.close()

        # Allow receiver to detect socket close
        time.sleep(0.2)

        # Incomplete file must NOT exist
        dest_file = Path(self.dest_dir) / "interrupted_large.bin"
        self.assertFalse(dest_file.exists(), "Corrupted incomplete destination file was committed!")

        # No .part temporary files must remain
        part_files = list(Path(self.dest_dir).glob("*.part"))
        self.assertEqual(len(part_files), 0, f"Found lingering temporary files: {part_files}")


class TestBenchmarkUtility(unittest.TestCase):
    def test_benchmark_result_formatting(self):
        res = BenchmarkResult(
            file_size_bytes=5 * 1024 * 1024,
            chunk_size_bytes=64 * 1024,
            transport_name=TransportType.DIRECT_WIFI.value,
            duration_seconds=0.05,
            throughput_bytes_per_sec=100 * 1024 * 1024,
            throughput_mbps=838.86,
            sha256_match=True,
        )
        table = format_benchmark_table([res])
        self.assertIn("5.00 MiB", table)
        self.assertIn("64.00 KiB", table)
        self.assertIn(TransportType.DIRECT_WIFI.value, table)
        self.assertIn("PASSED", table)

    def test_run_local_benchmark_matrix(self):
        """Run local benchmark matrix for 1 MiB file."""
        results = run_local_benchmark_matrix(
            sizes_mib=[1],
            chunk_sizes=[64 * 1024],
        )
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].sha256_match)
        self.assertGreater(results[0].throughput_bytes_per_sec, 0)


if __name__ == "__main__":
    unittest.main()
