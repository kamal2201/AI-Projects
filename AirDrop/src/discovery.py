"""mDNS / DNS-SD Service Discovery and Advertisement for AirDrop."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import ipaddress
import logging
import os
import socket
import sys
import threading
import time
from typing import Any, Callable
import uuid

import ifaddr
from zeroconf import (
    IPVersion,
    NonUniqueNameException,
    ServiceBrowser,
    ServiceInfo,
    ServiceListener,
    Zeroconf,
)

logger = logging.getLogger("airdrop.discovery")

# Service type definition for AirDrop over TCP
AIRDROP_SERVICE_TYPE = "_airdrop-file._tcp.local."
DEFAULT_STALE_TIMEOUT = 30.0  # seconds before unrefreshed device is considered expired


def get_lan_ip_addresses() -> list[str]:
    """Discover all active non-loopback IPv4 addresses on local network interfaces."""
    ip_list: list[str] = []
    # Ignore known virtual, tunnel, or peer-to-peer interfaces that do not support LAN multicast
    virtual_prefixes = ("utun", "tun", "tap", "docker", "veth", "vboxnet", "vmnet", "awdl", "llw")
    try:
        adapters = ifaddr.get_adapters()
        for adapter in adapters:
            name_lower = adapter.name.lower()
            if any(name_lower.startswith(prefix) for prefix in virtual_prefixes):
                continue
            for ip in adapter.ips:
                if ip.is_IPv4:
                    ip_str = ip.ip
                    # Skip loopback
                    if ip_str.startswith("127."):
                        continue
                    # Skip link-local autoconfiguration (169.254.x.x) if possible
                    if ip_str.startswith("169.254."):
                        continue
                    if ip_str not in ip_list:
                        ip_list.append(ip_str)
    except Exception as err:
        logger.debug("Failed to query network adapters via ifaddr: %s", err)

    # Fallback to route-based local IP if no interface IP found
    if not ip_list:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            fallback_ip = s.getsockname()[0]
            s.close()
            if fallback_ip and not fallback_ip.startswith("127."):
                ip_list.append(fallback_ip)
        except Exception:
            pass

    # Ultimate fallback to loopback
    if not ip_list:
        ip_list.append("127.0.0.1")

    # Sort so private LAN ranges (192.168.x.x, 10.x.x.x, 172.16-31.x.x) come first
    def ip_priority(addr: str) -> int:
        try:
            obj = ipaddress.ip_address(addr)
            if obj.is_private and not obj.is_loopback:
                return 0
            if obj.is_global:
                return 1
            return 2
        except ValueError:
            return 3

    ip_list.sort(key=ip_priority)
    return ip_list


def get_default_display_name() -> str:
    """Generate a clean, non-personal default display name from machine hostname."""
    raw_name = socket.gethostname().split(".")[0]
    # Clean non-alphanumeric chars (keep hyphens and underscores)
    clean = "".join(c for c in raw_name if c.isalnum() or c in ("-", "_")).strip("-")
    return clean or "AirDrop-Peer"


@dataclass
class DiscoveredDevice:
    """Represents an AirDrop receiver discovered on the local network."""

    service_name: str
    display_name: str
    addresses: list[str]
    port: int
    properties: dict[str, str] = field(default_factory=dict)
    is_available: bool = True
    last_seen: float = field(default_factory=time.time)
    node_id: str = ""

    @property
    def primary_address(self) -> str:
        """Return the best IPv4 address to connect to."""
        if self.addresses:
            return self.addresses[0]
        return "127.0.0.1"

    @property
    def status_label(self) -> str:
        return "AVAILABLE" if self.is_available else "UNAVAILABLE"

    def matches_query(self, query: str) -> bool:
        """Check if this device matches a search query string."""
        q = query.strip().lower()
        if not q:
            return False
        if q == self.display_name.lower():
            return True
        if q in self.display_name.lower():
            return True
        if q in self.service_name.lower():
            return True
        if q in self.primary_address:
            return True
        if self.node_id and q == self.node_id.lower():
            return True
        return False


class ServiceAdvertiser:
    """Advertises the AirDrop file receiver service via mDNS/DNS-SD."""

    def __init__(
        self,
        port: int,
        display_name: str | None = None,
        service_type: str = AIRDROP_SERVICE_TYPE,
        zc: Zeroconf | None = None,
    ) -> None:
        self.port = port
        self.service_type = service_type
        self.display_name = display_name or get_default_display_name()
        self.node_id = uuid.uuid4().hex[:8]
        self._custom_zc = zc is not None
        self.zc: Zeroconf | None = zc
        self.service_info: ServiceInfo | None = None
        self._is_advertising = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Register the mDNS service advertisement."""
        with self._lock:
            if self._is_advertising:
                return

            lan_ips = get_lan_ip_addresses()
            if self.zc is None:
                self.zc = Zeroconf(interfaces=lan_ips, ip_version=IPVersion.V4Only)

            packed_ips = [socket.inet_aton(ip) for ip in lan_ips]

            # Minimal non-personal metadata
            props = {
                "version": "1.0",
                "app": "airdrop",
                "node_id": self.node_id,
                "display_name": self.display_name,
            }

            # Create distinct instance name incorporating short node_id to avoid name collisions
            instance_name = f"{self.display_name}-{self.node_id}"
            full_service_name = f"{instance_name}.{self.service_type}"
            server_host = f"{self.display_name}.local."

            self.service_info = ServiceInfo(
                type_=self.service_type,
                name=full_service_name,
                addresses=packed_ips,
                port=self.port,
                properties=props,
                server=server_host,
            )

            try:
                self.zc.register_service(self.service_info)
                self._is_advertising = True
                logger.info(
                    "mDNS service registered: '%s' (%s:%d)",
                    self.display_name,
                    lan_ips[0] if lan_ips else "0.0.0.0",
                    self.port,
                )
            except NonUniqueNameException:
                # Handle collision by appending a timestamp
                instance_name = f"{self.display_name}-{int(time.time())}"
                full_service_name = f"{instance_name}.{self.service_type}"
                self.service_info = ServiceInfo(
                    type_=self.service_type,
                    name=full_service_name,
                    addresses=packed_ips,
                    port=self.port,
                    properties=props,
                    server=server_host,
                )
                self.zc.register_service(self.service_info)
                self._is_advertising = True
                logger.info("mDNS service registered with fallback name: '%s'", full_service_name)

    def stop(self) -> None:
        """Unregister the service and broadcast goodbye packet."""
        with self._lock:
            if not self._is_advertising:
                return

            if self.zc and self.service_info:
                try:
                    logger.info("Unregistering mDNS service '%s'...", self.display_name)
                    self.zc.unregister_service(self.service_info)
                except Exception as err:
                    logger.debug("Error during unregister_service: %s", err)

            if self.zc and not self._custom_zc:
                try:
                    self.zc.close()
                except Exception as err:
                    logger.debug("Error closing Zeroconf instance: %s", err)
                self.zc = None

            self.service_info = None
            self._is_advertising = False
            logger.info("mDNS service successfully stopped.")

    def __enter__(self) -> ServiceAdvertiser:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


class PeerBrowser(ServiceListener):
    """Browses and maintains the active registry of AirDrop devices on the LAN."""

    def __init__(
        self,
        service_type: str = AIRDROP_SERVICE_TYPE,
        zc: Zeroconf | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        self.service_type = service_type
        self._custom_zc = zc is not None
        self.zc: Zeroconf | None = zc
        self.browser: ServiceBrowser | None = None
        self.on_change = on_change

        self._devices: dict[str, DiscoveredDevice] = {}
        self._lock = threading.RLock()
        self._running = False
        self._sweeper_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start listening for service advertisements on the LAN."""
        with self._lock:
            if self._running:
                return

            if self.zc is None:
                lan_ips = get_lan_ip_addresses()
                self.zc = Zeroconf(interfaces=lan_ips, ip_version=IPVersion.V4Only)

            self._running = True
            self.browser = ServiceBrowser(self.zc, self.service_type, listener=self)

            # Background thread to check for stale/expired devices
            self._sweeper_thread = threading.Thread(target=self._sweeper_loop, daemon=True)
            self._sweeper_thread.start()
            logger.debug("PeerBrowser started for service type %s", self.service_type)

    def stop(self) -> None:
        """Stop browsing and release network sockets."""
        with self._lock:
            if not self._running:
                return

            self._running = False
            if self.browser:
                try:
                    self.browser.cancel()
                except Exception:
                    pass
                self.browser = None

            if self.zc and not self._custom_zc:
                try:
                    self.zc.close()
                except Exception:
                    pass
                self.zc = None

            logger.debug("PeerBrowser stopped.")

    # ServiceListener callbacks
    def add_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Invoked when a service advertisement is announced."""
        info = zc.get_service_info(type_, name)
        if not info:
            return

        addresses = [socket.inet_ntoa(a) for a in info.addresses if len(a) == 4]
        if not addresses:
            return

        # Decode properties safely
        props: dict[str, str] = {}
        for k, v in (info.properties or {}).items():
            key = k.decode("utf-8", errors="replace") if isinstance(k, bytes) else str(k)
            val = v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v)
            props[key] = val

        display_name = props.get("display_name")
        if not display_name:
            display_name = name.split(".")[0].rsplit("-", 1)[0]

        node_id = props.get("node_id", "")

        with self._lock:
            device = DiscoveredDevice(
                service_name=name,
                display_name=display_name,
                addresses=addresses,
                port=info.port,
                properties=props,
                is_available=True,
                last_seen=time.time(),
                node_id=node_id,
            )
            self._devices[name] = device
            logger.info(
                "Discovered device: '%s' at %s:%d (%s)",
                display_name,
                device.primary_address,
                device.port,
                name,
            )

        if self.on_change:
            self.on_change()

    def update_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Invoked when a service advertisement is updated."""
        self.add_service(zc, type_, name)

    def remove_service(self, zc: Zeroconf, type_: str, name: str) -> None:
        """Invoked when a goodbye packet is received."""
        with self._lock:
            if name in self._devices:
                dev = self._devices[name]
                dev.is_available = False
                logger.info("Device departed (goodbye): '%s' (%s)", dev.display_name, name)

        if self.on_change:
            self.on_change()

    def _sweeper_loop(self) -> None:
        """Periodically check for expired device advertisements."""
        while self._running:
            time.sleep(5.0)
            now = time.time()
            changed = False
            with self._lock:
                for dev in self._devices.values():
                    if dev.is_available and (now - dev.last_seen > DEFAULT_STALE_TIMEOUT):
                        dev.is_available = False
                        changed = True
                        logger.info("Device expired (stale TTL): '%s'", dev.display_name)
            if changed and self.on_change:
                self.on_change()

    def get_devices(self, include_unavailable: bool = False) -> list[DiscoveredDevice]:
        """Return a copy of discovered devices."""
        with self._lock:
            if include_unavailable:
                return list(self._devices.values())
            return [d for d in self._devices.values() if d.is_available]

    def find_device(self, query: str) -> DiscoveredDevice | None:
        """Find an available device matching query string (name or address)."""
        available = self.get_devices(include_unavailable=False)
        # First try exact match
        for dev in available:
            if query.lower() == dev.display_name.lower() or query == dev.primary_address:
                return dev
        # Next try substring match
        for dev in available:
            if dev.matches_query(query):
                return dev
        return None

    def __enter__(self) -> PeerBrowser:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()


def format_device_table(devices: list[DiscoveredDevice]) -> str:
    """Format discovered devices into a clean ASCII table."""
    if not devices:
        return "No AirDrop devices discovered."

    headers = ["#", "Display Name", "IP Address", "Port", "Status"]
    rows: list[list[str]] = []
    for idx, dev in enumerate(devices, 1):
        rows.append([
            str(idx),
            dev.display_name,
            dev.primary_address,
            str(dev.port),
            dev.status_label,
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

    out: list[str] = [
        make_divider("-"),
        format_row(headers),
        make_divider("="),
    ]
    for row in rows:
        out.append(format_row(row))
    out.append(make_divider("-"))
    return "\n".join(out)


def discover_peers_interactive(
    scan_seconds: float = 3.0,
    browser: PeerBrowser | None = None,
) -> DiscoveredDevice | None:
    """Scan the LAN, print available devices, and let user pick one interactively."""
    owns_browser = browser is None
    if browser is None:
        browser = PeerBrowser()
        browser.start()

    try:
        print(f"Scanning local network for AirDrop devices ({scan_seconds:.1f}s)...")
        time.sleep(scan_seconds)

        devices = browser.get_devices(include_unavailable=False)
        if not devices:
            print("No AirDrop receivers found on the local network.")
            return None

        print("\nDiscovered Devices:")
        print(format_device_table(devices))

        if len(devices) == 1:
            choice = input(f"\nConnect to '{devices[0].display_name}'? [Y/n]: ").strip().lower()
            if choice in ("", "y", "yes"):
                return devices[0]
            return None

        while True:
            sel = input(f"\nSelect a device (1-{len(devices)}) or 'q' to cancel: ").strip()
            if sel.lower() in ("q", "quit", "exit"):
                return None
            try:
                num = int(sel)
                if 1 <= num <= len(devices):
                    return devices[num - 1]
            except ValueError:
                pass
            print(f"Invalid selection. Please enter a number between 1 and {len(devices)}.")
    finally:
        if owns_browser:
            browser.stop()


def main() -> None:
    """CLI discovery monitor."""
    parser = argparse.ArgumentParser(
        description="AirDrop LAN Discovery - Scan and monitor active AirDrop devices."
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch for network peers until interrupted",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=4.0,
        help="Initial scan time in seconds (default: 4.0)",
    )
    parser.add_argument(
        "-a", "--all",
        action="store_true",
        help="Include departed or unavailable devices in listing",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    print("AirDrop LAN Peer Discovery")
    print(f"Browsing for service type '{AIRDROP_SERVICE_TYPE}'...")

    browser = PeerBrowser()
    browser.start()

    try:
        if not args.watch:
            time.sleep(args.timeout)
            devices = browser.get_devices(include_unavailable=args.all)
            print("\n" + format_device_table(devices))
        else:
            print("Watching for peers in real time (Press Ctrl-C to stop)...")
            last_count = -1
            while True:
                devices = browser.get_devices(include_unavailable=args.all)
                if len(devices) != last_count:
                    print("\n" + format_device_table(devices))
                    last_count = len(devices)
                time.sleep(2.0)
    except KeyboardInterrupt:
        print("\nDiscovery stopped by user.")
    finally:
        browser.stop()


if __name__ == "__main__":
    main()
