"""Bluetooth Low Energy (BLE) Discovery and Advertising for AirDrop."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
import logging
import os
import platform
import sys
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("airdrop.ble")

# Application-specific BLE Service UUID (128-bit)
AIRDROP_BLE_SERVICE_UUID = "f7826da6-4fa2-4e98-8024-bc5b71e0893e"
BLE_LOCAL_NAME_PREFIX = "AD-"

# Module-level CoreBluetooth integration for macOS
_HAS_PYOBJC_COREBLUETOOTH = False
_MacPeripheralDelegate = None
_CBUUID = None
_CBAdvertisementDataServiceUUIDsKey = None
_CBAdvertisementDataLocalNameKey = None
_dispatch_queue_create = None

if platform.system() == "Darwin":
    try:
        from Foundation import NSObject
        from CoreBluetooth import (
            CBPeripheralManager,
            CBUUID as _CBUUID_import,
            CBAdvertisementDataServiceUUIDsKey as _CBAdvUUIDsKey,
            CBAdvertisementDataLocalNameKey as _CBAdvNameKey,
        )
        from libdispatch import dispatch_queue_create as _dispatch_create

        _CBUUID = _CBUUID_import
        _CBAdvertisementDataServiceUUIDsKey = _CBAdvUUIDsKey
        _CBAdvertisementDataLocalNameKey = _CBAdvNameKey
        _dispatch_queue_create = _dispatch_create

        class _MacPeripheralDelegateClass(NSObject):
            """Objective-C delegate for CBPeripheralManager registered once at module load."""

            def initWithAdvertiser_(self, advertiser: Any):
                self = self.init()
                if self is not None:
                    self._advertiser = advertiser
                return self

            def peripheralManagerDidUpdateState_(self, mgr: Any):
                state = mgr.state()
                # 5 = CBManagerStatePoweredOn
                if state == 5 and self._advertiser:
                    cbuuid = _CBUUID.UUIDWithString_(AIRDROP_BLE_SERVICE_UUID)
                    adv_data = {
                        _CBAdvertisementDataServiceUUIDsKey: [cbuuid],
                        _CBAdvertisementDataLocalNameKey: f"{BLE_LOCAL_NAME_PREFIX}{self._advertiser.node_id[:8]}",
                    }
                    mgr.startAdvertising_(adv_data)
                    logger.debug("CoreBluetooth peripheral started advertising.")
                elif state == 4:
                    logger.warning("Bluetooth is powered off on this Mac.")
                elif state == 3:
                    logger.warning("Bluetooth permission unauthorized on this Mac.")

        _MacPeripheralDelegate = _MacPeripheralDelegateClass
        _HAS_PYOBJC_COREBLUETOOTH = True
    except Exception as err:
        logger.debug("Could not initialize macOS PyObjC CoreBluetooth delegate: %s", err)


class BleStatus(str, Enum):
    """Status of the BLE subsystem."""
    READY = "READY"
    BLUETOOTH_DISABLED = "BLUETOOTH_DISABLED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    UNSUPPORTED = "UNSUPPORTED"
    ERROR = "ERROR"


@dataclass
class BleAdvertisement:
    """Parsed minimal BLE advertisement payload."""
    node_id: str
    display_name: str
    address: str
    rssi: int
    service_uuid: str = AIRDROP_BLE_SERVICE_UUID


def parse_ble_advertisement(
    name: str | None,
    service_uuids: list[str] | None,
    address: str,
    rssi: int,
) -> BleAdvertisement | None:
    """Parse minimal AirDrop identifiers from a BLE advertisement.

    Ensures no personal information, email addresses, phone numbers, or filenames
    are accepted or parsed.
    """
    is_airdrop = False
    node_id = ""

    # Check for service UUID match
    if service_uuids:
        normalized_uuids = [u.lower().strip() for u in service_uuids]
        if AIRDROP_BLE_SERVICE_UUID.lower() in normalized_uuids:
            is_airdrop = True

    # Check for local name prefix 'AD-<node_id>'
    if name and name.startswith(BLE_LOCAL_NAME_PREFIX):
        is_airdrop = True
        parts = name.split("-", 1)
        if len(parts) > 1 and parts[1]:
            node_id = parts[1].strip()

    if not is_airdrop:
        return None

    if not node_id:
        # Fallback to sanitized tail of BLE address
        node_id = address.replace(":", "").replace("-", "")[-8:].lower()

    # Display name is strictly derived from node_id to prevent leaking personal info
    display_name = f"AirDrop-BLE-{node_id[:6]}"

    return BleAdvertisement(
        node_id=node_id,
        display_name=display_name,
        address=address,
        rssi=rssi,
    )


class MockBleBus:
    """Thread-safe mock BLE bus for deterministic testing and simulated environments."""

    _subscribers: list[Callable[[BleAdvertisement], None]] = []
    _lock = threading.Lock()

    @classmethod
    def subscribe(cls, callback: Callable[[BleAdvertisement], None]) -> None:
        with cls._lock:
            if callback not in cls._subscribers:
                cls._subscribers.append(callback)

    @classmethod
    def unsubscribe(cls, callback: Callable[[BleAdvertisement], None]) -> None:
        with cls._lock:
            if callback in cls._subscribers:
                cls._subscribers.remove(callback)

    @classmethod
    def broadcast(cls, adv: BleAdvertisement) -> None:
        with cls._lock:
            subscribers = list(cls._subscribers)
        for sub in subscribers:
            try:
                sub(adv)
            except Exception as err:
                logger.debug("Error in MockBleBus subscriber: %s", err)


class BleAdvertiser:
    """Manages BLE peripheral advertising of the AirDrop service."""

    def __init__(
        self,
        node_id: str,
        display_name: str | None = None,
        use_mock: bool = False,
    ) -> None:
        self.node_id = node_id
        self.display_name = display_name or f"AirDrop-{node_id[:6]}"
        self.use_mock = use_mock
        self.status = BleStatus.READY
        self.is_advertising = False
        self._lock = threading.Lock()

        # macOS CoreBluetooth handles
        self._cb_manager = None
        self._cb_delegate = None
        self._dispatch_queue = None

        # Background simulator thread if mocking
        self._mock_thread: threading.Thread | None = None

    def start(self) -> BleStatus:
        """Begin broadcasting minimal AirDrop BLE advertisements."""
        with self._lock:
            if self.is_advertising:
                return self.status

            if self.use_mock:
                self._start_mock_advertising()
                self.is_advertising = True
                self.status = BleStatus.READY
                logger.info("Mock BLE advertiser started for node '%s'", self.node_id)
                return self.status

            # Attempt native macOS CoreBluetooth peripheral advertisement
            if platform.system() == "Darwin":
                status = self._start_macos_advertising()
                if status == BleStatus.READY:
                    self.is_advertising = True
                    self.status = BleStatus.READY
                    logger.info("Native macOS BLE peripheral advertising started (node: %s)", self.node_id)
                    return self.status
                else:
                    self.status = status
                    logger.warning("Native macOS BLE advertising not available: %s", status.value)
                    return status

            # For Linux / Windows without root or direct peripheral drivers
            logger.info("BLE peripheral advertising not natively configured on %s. Operating in passive scan mode.", platform.system())
            self.status = BleStatus.UNSUPPORTED
            return self.status

    def stop(self) -> None:
        """Stop broadcasting BLE advertisements."""
        with self._lock:
            if not self.is_advertising and not self.use_mock:
                return

            if self.use_mock:
                self.is_advertising = False
                logger.debug("Mock BLE advertiser stopped.")
                return

            if self._cb_manager is not None:
                try:
                    self._cb_manager.stopAdvertising()
                except Exception as err:
                    logger.debug("Error stopping CoreBluetooth advertisement: %s", err)
                self._cb_manager = None

            self.is_advertising = False
            logger.info("BLE advertiser stopped.")

    def _start_mock_advertising(self) -> None:
        """Broadcast advertisements to MockBleBus periodically."""
        self.is_advertising = True

        def loop():
            while self.is_advertising:
                adv = BleAdvertisement(
                    node_id=self.node_id,
                    display_name=self.display_name,
                    address=f"mock:{self.node_id[:4]}",
                    rssi=-55,
                )
                MockBleBus.broadcast(adv)
                time.sleep(1.0)

        self._mock_thread = threading.Thread(target=loop, daemon=True)
        self._mock_thread.start()

    def _start_macos_advertising(self) -> BleStatus:
        """Initialize CoreBluetooth CBPeripheralManager on macOS."""
        if not _HAS_PYOBJC_COREBLUETOOTH or _MacPeripheralDelegate is None:
            return BleStatus.UNSUPPORTED

        try:
            from CoreBluetooth import CBPeripheralManager

            self._cb_delegate = _MacPeripheralDelegate.alloc().initWithAdvertiser_(self)
            self._dispatch_queue = _dispatch_queue_create(b"com.airdrop.ble.peripheral", None)
            self._cb_manager = CBPeripheralManager.alloc().initWithDelegate_queue_(
                self._cb_delegate, self._dispatch_queue
            )

            # Wait briefly to check state
            time.sleep(0.3)
            state = self._cb_manager.state()
            if state == 4:
                return BleStatus.BLUETOOTH_DISABLED
            elif state == 3:
                return BleStatus.PERMISSION_DENIED
            elif state == 2:
                return BleStatus.UNSUPPORTED
            return BleStatus.READY

        except Exception as err:
            logger.warning("Failed to start macOS BLE peripheral advertising: %s", err)
            return BleStatus.ERROR


class BleScanner:
    """Manages BLE scanning and passes discovered instances to DeviceRegistry."""

    def __init__(
        self,
        on_discovered: Callable[[BleAdvertisement], None],
        use_mock: bool = False,
    ) -> None:
        self.on_discovered = on_discovered
        self.use_mock = use_mock
        self.status = BleStatus.READY
        self.is_scanning = False
        self._lock = threading.Lock()

        self._scanner_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> BleStatus:
        """Start scanning for nearby AirDrop BLE advertisements."""
        with self._lock:
            if self.is_scanning:
                return self.status

            self._stop_event.clear()
            self.is_scanning = True

            # Register with MockBleBus regardless so simulations work seamlessly
            MockBleBus.subscribe(self._on_mock_advertisement)

            if not self.use_mock:
                self._scanner_thread = threading.Thread(target=self._run_async_scan, daemon=True)
                self._scanner_thread.start()

            logger.info("BLE Scanner active.")
            return BleStatus.READY

    def stop(self) -> None:
        """Stop BLE scanning."""
        with self._lock:
            if not self.is_scanning:
                return

            self.is_scanning = False
            self._stop_event.set()

            MockBleBus.unsubscribe(self._on_mock_advertisement)

            if self._loop and self._loop.is_running():
                self._loop.call_soon_threadsafe(self._loop.stop)

            logger.info("BLE Scanner stopped.")

    def _on_mock_advertisement(self, adv: BleAdvertisement) -> None:
        """Handle simulated advertisement."""
        if self.is_scanning:
            self.on_discovered(adv)

    def _run_async_scan(self) -> None:
        """Background thread running bleak BleakScanner loop."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._scan_coroutine())
        except Exception as err:
            logger.debug("BLE scan loop ended: %s", err)
        finally:
            self._loop.close()

    async def _scan_coroutine(self) -> None:
        """Async scanning coroutine using bleak."""
        try:
            from bleak import BleakScanner
        except ImportError:
            logger.warning("Bleak is not installed. BLE hardware scanning disabled.")
            self.status = BleStatus.UNSUPPORTED
            return

        def detection_callback(device: Any, advertisement_data: Any):
            try:
                name = advertisement_data.local_name
                uuids = advertisement_data.service_uuids
                adv = parse_ble_advertisement(
                    name=name,
                    service_uuids=uuids,
                    address=device.address,
                    rssi=advertisement_data.rssi,
                )
                if adv and self.is_scanning:
                    self.on_discovered(adv)
            except Exception as err:
                logger.debug("Error in BLE detection callback: %s", err)

        try:
            scanner = BleakScanner(detection_callback=detection_callback)
            await scanner.start()
            logger.debug("BleakScanner started successfully.")

            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)

            await scanner.stop()
            logger.debug("BleakScanner stopped cleanly.")

        except Exception as err:
            err_str = str(err).lower()
            if "powered off" in err_str or "disabled" in err_str:
                self.status = BleStatus.BLUETOOTH_DISABLED
                logger.warning("Bluetooth is turned off on this device.")
            elif "permission" in err_str or "unauthorized" in err_str:
                self.status = BleStatus.PERMISSION_DENIED
                logger.warning("Bluetooth permission was denied by the operating system.")
            else:
                self.status = BleStatus.ERROR
                logger.debug("BleakScanner encountered non-fatal error: %s", err)
