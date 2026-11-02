"""Unit and integration tests for BLE discovery, device registry, and state management."""

import time
import unittest
from unittest.mock import MagicMock, patch

from src.ble_discovery import (
    AIRDROP_BLE_SERVICE_UUID,
    BLE_LOCAL_NAME_PREFIX,
    BleAdvertisement,
    BleAdvertiser,
    BleScanner,
    BleStatus,
    MockBleBus,
    parse_ble_advertisement,
)
from src.registry import (
    DeviceRegistry,
    DeviceState,
    DiscoverySource,
    UnifiedDevice,
)


class TestBleAdvertisementParsing(unittest.TestCase):
    def test_parse_valid_airdrop_advertisement(self):
        adv = parse_ble_advertisement(
            name=f"{BLE_LOCAL_NAME_PREFIX}ab12cd34",
            service_uuids=[AIRDROP_BLE_SERVICE_UUID],
            address="AA:BB:CC:DD:EE:FF",
            rssi=-62,
        )
        self.assertIsNotNone(adv)
        self.assertEqual(adv.node_id, "ab12cd34")
        self.assertEqual(adv.rssi, -62)
        self.assertEqual(adv.address, "AA:BB:CC:DD:EE:FF")
        # Ensure name does not contain personal info
        self.assertIn("ab12cd", adv.display_name)
        self.assertNotIn("@", adv.display_name)

    def test_reject_non_airdrop_advertisement(self):
        adv = parse_ble_advertisement(
            name="Random-Bluetooth-Headphones",
            service_uuids=["0000180a-0000-1000-8000-00805f9b34fb"],
            address="11:22:33:44:55:66",
            rssi=-70,
        )
        self.assertIsNone(adv)

    def test_privacy_no_personal_data_leakage(self):
        """Ensure filenames, emails, and personal paths are never stored in BLE advertisement."""
        adv = parse_ble_advertisement(
            name=f"{BLE_LOCAL_NAME_PREFIX}secret12",
            service_uuids=[AIRDROP_BLE_SERVICE_UUID],
            address="00:11:22:33:44:55",
            rssi=-50,
        )
        self.assertIsNotNone(adv)
        for forbidden in ["@", ".pdf", ".txt", "/Users/", "C:\\", "phone"]:
            self.assertNotIn(forbidden, adv.display_name)
            self.assertNotIn(forbidden, adv.node_id)


class TestUnifiedDeviceRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = DeviceRegistry()

    def test_merge_ble_then_mdns_deduplication(self):
        """Registering via BLE first and mDNS second must produce a single merged hybrid device."""
        node_id = "test_node_01"

        # 1. Seen via BLE
        dev_ble = self.registry.register_ble(
            node_id=node_id,
            display_name="AirDrop-BLE-01",
            ble_address="E6:21:E1:F8:00:01",
            rssi=-65,
        )
        self.assertEqual(dev_ble.state, DeviceState.DISCOVERED)
        self.assertFalse(dev_ble.is_reachable)
        self.assertIsNone(dev_ble.ip_address)
        self.assertEqual(dev_ble.source_label, "BLE")
        self.assertEqual(len(self.registry.get_devices()), 1)

        # 2. Seen via mDNS
        dev_merged = self.registry.register_mdns(
            node_id=node_id,
            display_name="MacBook-Pro",
            addresses=["192.168.1.100"],
            port=5001,
            service_name="MacBook-Pro-test_node_01._airdrop-file._tcp.local.",
        )

        # Must be the exact same instance in registry
        devices = self.registry.get_devices()
        self.assertEqual(len(devices), 1, "Duplicate device created instead of merging!")

        dev = devices[0]
        self.assertEqual(dev.node_id, node_id)
        self.assertEqual(dev.state, DeviceState.REACHABLE)
        self.assertTrue(dev.is_reachable)
        self.assertEqual(dev.ip_address, "192.168.1.100")
        self.assertEqual(dev.port, 5001)
        self.assertEqual(dev.rssi, -65)
        self.assertEqual(dev.source_label, "mDNS+BLE")

    def test_merge_mdns_then_ble_deduplication(self):
        """Registering via mDNS first and BLE second must produce a single merged hybrid device."""
        node_id = "test_node_02"

        # 1. Seen via mDNS
        self.registry.register_mdns(
            node_id=node_id,
            display_name="Office-PC",
            addresses=["10.0.0.45"],
            port=5001,
            service_name="Office-PC-test_node_02._airdrop-file._tcp.local.",
        )
        dev = self.registry.find_device("Office-PC")
        self.assertIsNotNone(dev)
        self.assertEqual(dev.state, DeviceState.REACHABLE)
        self.assertEqual(dev.source_label, "mDNS")

        # 2. Seen via BLE
        self.registry.register_ble(
            node_id=node_id,
            display_name="Office-PC",
            ble_address="12:34:56:78:9A:BC",
            rssi=-54,
        )

        devices = self.registry.get_devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0].source_label, "mDNS+BLE")
        self.assertEqual(devices[0].rssi, -54)
        self.assertTrue(devices[0].is_reachable)

    def test_discovery_alone_cannot_trigger_transfer(self):
        """A device discovered ONLY via BLE cannot be connected to for file transfer."""
        dev = self.registry.register_ble(
            node_id="ble_only_node",
            display_name="Nearby-Device",
            ble_address="00:11:22:33:44:55",
            rssi=-75,
        )
        self.assertEqual(dev.state, DeviceState.DISCOVERED)
        self.assertFalse(dev.is_reachable)
        self.assertIsNone(dev.ip_address)
        self.assertIsNone(dev.port)

        # Querying only_reachable devices must exclude this device
        reachable_devs = self.registry.get_devices(only_reachable=True)
        self.assertNotIn(dev, reachable_devs)
        self.assertIsNone(self.registry.find_device("Nearby-Device", only_reachable=True))

    def test_duplicate_device_display_names(self):
        """Two distinct physical devices with the same display name are kept separate."""
        dev1 = self.registry.register_mdns(
            node_id="node_alpha",
            display_name="MacBook",
            addresses=["192.168.1.10"],
            port=5001,
            service_name="MacBook-alpha._airdrop-file._tcp.local.",
        )
        dev2 = self.registry.register_mdns(
            node_id="node_beta",
            display_name="MacBook",
            addresses=["192.168.1.20"],
            port=5001,
            service_name="MacBook-beta._airdrop-file._tcp.local.",
        )
        devices = self.registry.get_devices()
        self.assertEqual(len(devices), 2)
        self.assertNotEqual(dev1.node_id, dev2.node_id)
        self.assertNotEqual(dev1.ip_address, dev2.ip_address)

    def test_device_lifecycle_state_transitions(self):
        """Test transitions: DISCOVERED -> REACHABLE -> CONNECTED -> REACHABLE -> UNAVAILABLE."""
        node_id = "lifecycle_node"

        # 1. DISCOVERED
        dev = self.registry.register_ble(node_id, "NodeX", "AA:BB:CC:DD:EE:FF", rssi=-60)
        self.assertEqual(dev.state, DeviceState.DISCOVERED)

        # 2. REACHABLE
        dev = self.registry.register_mdns(
            node_id, "NodeX", ["192.168.1.55"], 5001, "NodeX._airdrop-file._tcp.local."
        )
        self.assertEqual(dev.state, DeviceState.REACHABLE)

        # 3. CONNECTED
        self.registry.mark_connected(node_id)
        self.assertEqual(dev.state, DeviceState.CONNECTED)

        # 4. REACHABLE (transfer complete)
        self.registry.mark_disconnected(node_id)
        self.assertEqual(dev.state, DeviceState.REACHABLE)

        # 5. UNAVAILABLE (mDNS goodbye)
        self.registry.mark_service_unavailable("NodeX._airdrop-file._tcp.local.")
        self.registry.clean_expired(stale_seconds=0.0)
        self.assertEqual(dev.state, DeviceState.UNAVAILABLE)


class TestBleHardwareAndErrorHandling(unittest.TestCase):
    def test_mock_ble_advertising_and_scanning(self):
        """Verify advertising and scanning using MockBleBus."""
        node_id = "mock_test_123"
        display_name = "MockTestDevice"

        discovered_events: list[BleAdvertisement] = []
        scanner = BleScanner(on_discovered=discovered_events.append, use_mock=True)
        advertiser = BleAdvertiser(node_id=node_id, display_name=display_name, use_mock=True)

        try:
            scanner.start()
            advertiser.start()

            # Wait for mock broadcast event
            start = time.time()
            while not discovered_events and (time.time() - start < 3.0):
                time.sleep(0.1)

            self.assertGreater(len(discovered_events), 0)
            adv = discovered_events[0]
            self.assertEqual(adv.node_id, node_id)
            self.assertEqual(adv.display_name, display_name)

        finally:
            advertiser.stop()
            scanner.stop()

    def test_ble_disabled_handling(self):
        """Simulate Bluetooth powered off and verify clean status reporting."""
        advertiser = BleAdvertiser(node_id="disabled_test")
        with patch.object(advertiser, "_start_macos_advertising", return_value=BleStatus.BLUETOOTH_DISABLED):
            status = advertiser.start()
            self.assertEqual(status, BleStatus.BLUETOOTH_DISABLED)
            self.assertFalse(advertiser.is_advertising)

    def test_ble_permission_denied_handling(self):
        """Simulate Bluetooth permission denied and verify clean status reporting."""
        advertiser = BleAdvertiser(node_id="perm_denied_test")
        with patch.object(advertiser, "_start_macos_advertising", return_value=BleStatus.PERMISSION_DENIED):
            status = advertiser.start()
            self.assertEqual(status, BleStatus.PERMISSION_DENIED)
            self.assertFalse(advertiser.is_advertising)

    def test_ble_unsupported_hardware_handling(self):
        """Simulate unsupported hardware (e.g. VM / container)."""
        advertiser = BleAdvertiser(node_id="unsupported_test")
        with patch("platform.system", return_value="Linux"):
            status = advertiser.start()
            self.assertEqual(status, BleStatus.UNSUPPORTED)
            self.assertFalse(advertiser.is_advertising)


if __name__ == "__main__":
    unittest.main()
