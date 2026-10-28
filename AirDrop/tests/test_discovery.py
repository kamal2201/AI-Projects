"""Tests for mDNS service advertisement, browsing, and discovery."""

from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

from zeroconf import ServiceInfo

from src.discovery import (
    AIRDROP_SERVICE_TYPE,
    DiscoveredDevice,
    PeerBrowser,
    ServiceAdvertiser,
    format_device_table,
    get_default_display_name,
    get_lan_ip_addresses,
)
from src.file_io import compute_file_sha256
from src.receiver import Receiver
from src.sender import Sender


class TestDiscoveredDeviceModel(unittest.TestCase):
    def test_primary_address(self):
        dev = DiscoveredDevice(
            service_name="Mac-123._airdrop-file._tcp.local.",
            display_name="Mac-123",
            addresses=["192.168.1.50", "10.0.0.1"],
            port=5001,
        )
        self.assertEqual(dev.primary_address, "192.168.1.50")
        self.assertEqual(dev.status_label, "AVAILABLE")

    def test_fallback_address(self):
        dev = DiscoveredDevice(
            service_name="Mac-123._airdrop-file._tcp.local.",
            display_name="Mac-123",
            addresses=[],
            port=5001,
            is_available=False,
        )
        self.assertEqual(dev.primary_address, "127.0.0.1")
        self.assertEqual(dev.status_label, "UNAVAILABLE")

    def test_matches_query(self):
        dev = DiscoveredDevice(
            service_name="Office-PC-99._airdrop-file._tcp.local.",
            display_name="Office-PC",
            addresses=["192.168.1.105"],
            port=5001,
            node_id="abc12345",
        )
        self.assertTrue(dev.matches_query("office"))
        self.assertTrue(dev.matches_query("Office-PC"))
        self.assertTrue(dev.matches_query("192.168.1.105"))
        self.assertTrue(dev.matches_query("abc12345"))
        self.assertFalse(dev.matches_query("home-laptop"))
        self.assertFalse(dev.matches_query(""))


class TestDiscoveryFormatting(unittest.TestCase):
    def test_format_empty_table(self):
        self.assertEqual(format_device_table([]), "No AirDrop devices discovered.")

    def test_format_populated_table(self):
        dev1 = DiscoveredDevice(
            service_name="Laptop-A._airdrop-file._tcp.local.",
            display_name="Laptop-A",
            addresses=["192.168.1.10"],
            port=5001,
        )
        table = format_device_table([dev1])
        self.assertIn("Laptop-A", table)
        self.assertIn("192.168.1.10", table)
        self.assertIn("5001", table)
        self.assertIn("AVAILABLE", table)
        self.assertIn("#", table)


class TestNetworkHelpers(unittest.TestCase):
    def test_get_lan_ip_addresses(self):
        ips = get_lan_ip_addresses()
        self.assertIsInstance(ips, list)
        self.assertGreater(len(ips), 0)
        # Verify valid IPv4 format
        for ip in ips:
            socket.inet_aton(ip)

    def test_get_default_display_name(self):
        name = get_default_display_name()
        self.assertIsInstance(name, str)
        self.assertGreater(len(name), 0)
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)


class TestPeerBrowserCallbacks(unittest.TestCase):
    def test_service_listener_lifecycle(self):
        browser = PeerBrowser()
        # Mock Zeroconf and ServiceInfo
        mock_zc = MagicMock()
        mock_info = MagicMock(spec=ServiceInfo)
        mock_info.addresses = [socket.inet_aton("192.168.1.42")]
        mock_info.port = 5001
        mock_info.properties = {
            b"version": b"1.0",
            b"display_name": b"Mock-Peer",
            b"node_id": b"mock01",
        }
        mock_zc.get_service_info.return_value = mock_info

        service_name = "Mock-Peer-mock01._airdrop-file._tcp.local."

        # Test add_service
        browser.add_service(mock_zc, AIRDROP_SERVICE_TYPE, service_name)
        dev = browser.find_device("Mock-Peer")
        self.assertIsNotNone(dev)
        self.assertEqual(dev.display_name, "Mock-Peer")
        self.assertEqual(dev.primary_address, "192.168.1.42")
        self.assertEqual(dev.port, 5001)
        self.assertTrue(dev.is_available)

        # Test remove_service (goodbye packet)
        browser.remove_service(mock_zc, AIRDROP_SERVICE_TYPE, service_name)
        # Should now be unavailable
        self.assertIsNone(browser.find_device("Mock-Peer"))
        all_devs = browser.get_devices(include_unavailable=True)
        self.assertEqual(len(all_devs), 1)
        self.assertFalse(all_devs[0].is_available)


class TestLiveDiscoveryMdns(unittest.TestCase):
    def test_advertise_and_discover_live(self):
        """Test advertising and discovering over local mDNS."""
        test_port = 5910
        test_name = f"TestNode-{int(time.time() * 1000) % 10000}"

        browser = PeerBrowser()
        advertiser = ServiceAdvertiser(port=test_port, display_name=test_name)

        try:
            browser.start()
            advertiser.start()

            # Wait up to 5 seconds for local mDNS resolution
            discovered = None
            start = time.time()
            while time.time() - start < 5.0:
                discovered = browser.find_device(test_name)
                if discovered:
                    break
                time.sleep(0.2)

            self.assertIsNotNone(discovered, f"Failed to discover advertised peer '{test_name}'")
            self.assertEqual(discovered.port, test_port)
            self.assertEqual(discovered.display_name, test_name)
            self.assertTrue(discovered.is_available)

            # Stop advertiser -> goodbye packet
            advertiser.stop()

            # Wait for goodbye packet processing
            start = time.time()
            while time.time() - start < 4.0:
                if not browser.find_device(test_name):
                    break
                time.sleep(0.2)

            self.assertIsNone(
                browser.find_device(test_name),
                "Device still reported available after advertiser stopped.",
            )

        finally:
            advertiser.stop()
            browser.stop()

    def test_duplicate_device_names_handling(self):
        """Test two services registered with the same display name."""
        common_name = "TwinDevice"
        adv1 = ServiceAdvertiser(port=5920, display_name=common_name)
        adv2 = ServiceAdvertiser(port=5921, display_name=common_name)
        browser = PeerBrowser()

        try:
            browser.start()
            adv1.start()
            adv2.start()

            start = time.time()
            found_count = 0
            while time.time() - start < 5.0:
                devs = [d for d in browser.get_devices() if d.display_name == common_name]
                found_count = len(devs)
                if found_count >= 2:
                    break
                time.sleep(0.2)

            # Both services must be uniquely registered despite the same display name
            self.assertEqual(
                found_count, 2, "Expected both twin devices to be registered and discovered."
            )

        finally:
            adv1.stop()
            adv2.stop()
            browser.stop()


class TestEndToEndTransferWithDiscovery(unittest.TestCase):
    def setUp(self):
        self.dest_dir = tempfile.mkdtemp(prefix="airdrop_disc_dest_")
        self.src_dir = tempfile.mkdtemp(prefix="airdrop_disc_src_")

        self.display_name = f"ReceiverNode-{int(time.time() * 1000) % 10000}"
        self.receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            timeout=10.0,
            advertise=True,
            display_name=self.display_name,
        )

        self.receiver_thread = threading.Thread(
            target=self.receiver.start,
            kwargs={"single_transfer": True},
            daemon=True,
        )
        self.receiver_thread.start()

        # Wait for receiver to bind and start advertising
        start = time.time()
        while (self.receiver.active_port is None or self.receiver.advertiser is None) and (time.time() - start < 5.0):
            time.sleep(0.05)

        self.assertIsNotNone(self.receiver.active_port)

    def tearDown(self):
        self.receiver.stop()
        self.receiver_thread.join(timeout=2.0)
        shutil.rmtree(self.dest_dir, ignore_errors=True)
        shutil.rmtree(self.src_dir, ignore_errors=True)

    def test_discover_and_transfer(self):
        """Use PeerBrowser to discover the receiver and send a file to it."""
        browser = PeerBrowser()
        browser.start()

        try:
            target_device = None
            start = time.time()
            while time.time() - start < 5.0:
                target_device = browser.find_device(self.display_name)
                if target_device:
                    break
                time.sleep(0.2)

            self.assertIsNotNone(target_device, f"Could not discover {self.display_name}")

            # Send file to discovered device using its port and localhost
            test_file = Path(self.src_dir) / "discovery_test.txt"
            test_file.write_text("Sent via automatic LAN mDNS discovery!\n")

            sender = Sender(host="127.0.0.1", port=target_device.port, timeout=10.0)
            result = sender.send_file(test_file)

            self.assertEqual(result["filesize"], test_file.stat().st_size)

            dest_file = Path(self.dest_dir) / "discovery_test.txt"
            self.assertTrue(dest_file.exists())
            self.assertEqual(compute_file_sha256(test_file), compute_file_sha256(dest_file))

        finally:
            browser.stop()


if __name__ == "__main__":
    unittest.main()
