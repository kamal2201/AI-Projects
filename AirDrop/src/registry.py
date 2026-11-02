"""Unified Device Registry combining mDNS and BLE discovery results."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
import threading
import time
from typing import Any, Callable

logger = logging.getLogger("airdrop.registry")


class DeviceState(str, Enum):
    """Lifecycle and reachability states for discovered AirDrop peers."""
    DISCOVERED = "DISCOVERED"      # Discovered via BLE or unverified beacon (no resolved IP/port)
    REACHABLE = "REACHABLE"        # Resolved IP and port; ready for TCP file transfer
    CONNECTED = "CONNECTED"        # Active TCP socket file transfer in progress
    UNAVAILABLE = "UNAVAILABLE"    # Departed, expired, or out of range


class DiscoverySource(str, Enum):
    """Discovery mechanism source."""
    MDNS = "mDNS"
    BLE = "BLE"
    HYBRID = "mDNS+BLE"


@dataclass
class UnifiedDevice:
    """Represents a unified AirDrop device discovered via mDNS, BLE, or both."""

    node_id: str
    display_name: str
    state: DeviceState = DeviceState.DISCOVERED
    sources: set[str] = field(default_factory=set)
    ip_address: str | None = None
    port: int | None = None
    rssi: int | None = None
    ble_address: str | None = None
    service_name: str | None = None
    last_seen_mdns: float | None = None
    last_seen_ble: float | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    @property
    def is_reachable(self) -> bool:
        """True if the device has a known network IP and port ready for TCP connection."""
        return (
            self.state in (DeviceState.REACHABLE, DeviceState.CONNECTED)
            and self.ip_address is not None
            and self.port is not None
            and self.port > 0
        )

    @property
    def source_label(self) -> str:
        """Formatted display label of active discovery mechanisms."""
        if "mDNS" in self.sources and "BLE" in self.sources:
            return DiscoverySource.HYBRID.value
        if "mDNS" in self.sources:
            return DiscoverySource.MDNS.value
        if "BLE" in self.sources:
            return DiscoverySource.BLE.value
        return "Unknown"

    @property
    def signal_str(self) -> str:
        """Formatted signal strength string."""
        if self.rssi is not None:
            return f"{self.rssi} dBm"
        return "N/A"

    @property
    def endpoint_str(self) -> str:
        """Formatted IP:Port endpoint or Unknown."""
        if self.ip_address and self.port:
            return f"{self.ip_address}:{self.port}"
        return "Resolving..."

    def matches_query(self, query: str) -> bool:
        """Check if query matches display name, IP, node_id, or service name."""
        q = query.strip().lower()
        if not q:
            return False
        if q == self.display_name.lower():
            return True
        if q in self.display_name.lower():
            return True
        if self.ip_address and q in self.ip_address:
            return True
        if q == self.node_id.lower():
            return True
        if self.service_name and q in self.service_name.lower():
            return True
        return False


class DeviceRegistry:
    """Thread-safe unified registry merging mDNS and BLE discovery results."""

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._devices: dict[str, UnifiedDevice] = {}  # keyed by node_id
        self._service_to_node: dict[str, str] = {}    # service_name -> node_id
        self._ble_to_node: dict[str, str] = {}        # ble_address -> node_id
        self._lock = threading.RLock()
        self.on_change = on_change

    def register_mdns(
        self,
        node_id: str,
        display_name: str,
        addresses: list[str],
        port: int,
        service_name: str,
        properties: dict[str, Any] | None = None,
    ) -> UnifiedDevice:
        """Add or update a device discovered via mDNS."""
        now = time.time()
        primary_ip = addresses[0] if addresses else "127.0.0.1"

        with self._lock:
            if node_id in self._devices:
                dev = self._devices[node_id]
                dev.sources.add(DiscoverySource.MDNS.value)
                dev.ip_address = primary_ip
                dev.port = port
                dev.service_name = service_name
                dev.last_seen_mdns = now
                if properties:
                    dev.properties.update(properties)
                # If was only DISCOVERED (from BLE), now REACHABLE
                if dev.state != DeviceState.CONNECTED:
                    dev.state = DeviceState.REACHABLE
                logger.debug("Updated mDNS record for '%s' (%s)", display_name, node_id)
            else:
                dev = UnifiedDevice(
                    node_id=node_id,
                    display_name=display_name,
                    state=DeviceState.REACHABLE,
                    sources={DiscoverySource.MDNS.value},
                    ip_address=primary_ip,
                    port=port,
                    service_name=service_name,
                    last_seen_mdns=now,
                    properties=properties or {},
                )
                self._devices[node_id] = dev
                logger.info("New device discovered via mDNS: '%s' (%s:%d)", display_name, primary_ip, port)

            self._service_to_node[service_name] = node_id

        if self.on_change:
            self.on_change()
        return dev

    def register_ble(
        self,
        node_id: str,
        display_name: str,
        ble_address: str,
        rssi: int | None = None,
        properties: dict[str, Any] | None = None,
    ) -> UnifiedDevice:
        """Add or update a device discovered via BLE."""
        now = time.time()

        with self._lock:
            if node_id in self._devices:
                dev = self._devices[node_id]
                dev.sources.add(DiscoverySource.BLE.value)
                dev.rssi = rssi
                dev.ble_address = ble_address
                dev.last_seen_ble = now
                if properties:
                    dev.properties.update(properties)
                # If it already had IP and was UNAVAILABLE, revive as REACHABLE
                if dev.state == DeviceState.UNAVAILABLE and dev.ip_address and dev.port:
                    dev.state = DeviceState.REACHABLE
                logger.debug("Updated BLE record for '%s' (%s, RSSI: %s)", display_name, node_id, rssi)
            else:
                # BLE-only discovery: known to exist, but not yet reachable for TCP without IP
                dev = UnifiedDevice(
                    node_id=node_id,
                    display_name=display_name,
                    state=DeviceState.DISCOVERED,
                    sources={DiscoverySource.BLE.value},
                    rssi=rssi,
                    ble_address=ble_address,
                    last_seen_ble=now,
                    properties=properties or {},
                )
                self._devices[node_id] = dev
                logger.info("New device discovered via BLE: '%s' (RSSI: %s dBm)", display_name, rssi)

            self._ble_to_node[ble_address] = node_id

        if self.on_change:
            self.on_change()
        return dev

    def mark_connected(self, node_id: str) -> None:
        """Mark device as currently in an active transfer session."""
        with self._lock:
            if node_id in self._devices:
                self._devices[node_id].state = DeviceState.CONNECTED
        if self.on_change:
            self.on_change()

    def mark_disconnected(self, node_id: str) -> None:
        """Mark device as no longer in active transfer session."""
        with self._lock:
            if node_id in self._devices:
                dev = self._devices[node_id]
                if dev.ip_address and dev.port:
                    dev.state = DeviceState.REACHABLE
                else:
                    dev.state = DeviceState.DISCOVERED
        if self.on_change:
            self.on_change()

    def mark_service_unavailable(self, service_name: str) -> None:
        """Mark device unavailable when mDNS goodbye packet is received."""
        with self._lock:
            node_id = self._service_to_node.get(service_name)
            if node_id and node_id in self._devices:
                dev = self._devices[node_id]
                dev.sources.discard(DiscoverySource.MDNS.value)
                if not dev.sources or DiscoverySource.BLE.value not in dev.sources:
                    dev.state = DeviceState.UNAVAILABLE
                else:
                    # Still visible via BLE, but TCP endpoint gone
                    dev.state = DeviceState.DISCOVERED
                    dev.ip_address = None
                    dev.port = None
                logger.info("Service departed via mDNS: '%s'", dev.display_name)
        if self.on_change:
            self.on_change()

    def clean_expired(self, stale_seconds: float = 30.0) -> None:
        """Periodically mark devices whose advertisements have expired."""
        now = time.time()
        changed = False
        with self._lock:
            for dev in self._devices.values():
                if dev.state in (DeviceState.REACHABLE, DeviceState.DISCOVERED):
                    mdns_stale = dev.last_seen_mdns is None or (now - dev.last_seen_mdns > stale_seconds)
                    ble_stale = dev.last_seen_ble is None or (now - dev.last_seen_ble > stale_seconds)
                    if mdns_stale and ble_stale:
                        dev.state = DeviceState.UNAVAILABLE
                        changed = True
                        logger.info("Device advertisement expired: '%s'", dev.display_name)
        if changed and self.on_change:
            self.on_change()

    def get_devices(
        self,
        include_unavailable: bool = False,
        only_reachable: bool = False,
    ) -> list[UnifiedDevice]:
        """Return list of devices matching criteria."""
        with self._lock:
            res: list[UnifiedDevice] = []
            for d in self._devices.values():
                if not include_unavailable and d.state == DeviceState.UNAVAILABLE:
                    continue
                if only_reachable and not d.is_reachable:
                    continue
                res.append(d)
            return res

    def find_device(self, query: str, only_reachable: bool = False) -> UnifiedDevice | None:
        """Find a device matching query."""
        with self._lock:
            candidates = self.get_devices(include_unavailable=False, only_reachable=only_reachable)
            # Exact match first
            for dev in candidates:
                if query.lower() == dev.display_name.lower() or query == dev.ip_address:
                    return dev
            # Partial match
            for dev in candidates:
                if dev.matches_query(query):
                    return dev
            return None

    def format_table(self, include_unavailable: bool = False) -> str:
        """Generate a clean ASCII table of all tracked devices."""
        devices = self.get_devices(include_unavailable=include_unavailable)
        if not devices:
            return "No AirDrop devices currently registered."

        headers = ["#", "Display Name", "State", "Discovery", "Endpoint", "Signal", "Node ID"]
        rows: list[list[str]] = []
        for idx, dev in enumerate(devices, 1):
            rows.append([
                str(idx),
                dev.display_name,
                dev.state.value,
                dev.source_label,
                dev.endpoint_str,
                dev.signal_str,
                dev.node_id,
            ])

        col_widths = [len(h) for h in headers]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(val))

        def make_divider(char: str = "-") -> str:
            parts = [char * (w + 2) for w in col_widths]
            return "+" + "+".join(parts) + "+"

        def format_row(row_vals: list[str]) -> str:
            parts = [f" {val.ljust(col_widths[i])} " for i, val in enumerate(row_vals)]
            return "|" + "|".join(parts) + "|"

        out = [
            make_divider("-"),
            format_row(headers),
            make_divider("="),
        ]
        for row in rows:
            out.append(format_row(row))
        out.append(make_divider("-"))
        return "\n".join(out)
