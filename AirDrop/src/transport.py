"""Transport abstraction layer separating connection establishment from file transfer.

Provides Direct Wi-Fi transport, standard LAN TCP transport, and automatic
failover with detailed connection diagnostics.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import logging
import platform
import socket
import sys
import time
from typing import Any

from src.protocol import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_SOCKET_TIMEOUT,
    AirDropError,
    ConnectionClosedError,
    recv_exact,
    send_exact,
)

logger = logging.getLogger("airdrop.transport")


class TransportType(str, Enum):
    """Network transport type used for file transfer."""
    DIRECT_WIFI = "DIRECT_WIFI"        # Direct P2P Wi-Fi / SoftAP (Routerless)
    LAN_TCP = "LAN_TCP"                # Infrastructure LAN TCP
    LOOPBACK = "LOOPBACK"              # Localhost testing
    SIMULATED_DIRECT = "SIMULATED_DIRECT"  # Emulated direct transport


@dataclass
class TransportConnection:
    """Active network connection with transport metadata."""

    sock: socket.socket
    transport_type: TransportType
    remote_host: str
    remote_port: int
    local_host: str = ""
    local_port: int = 0
    connect_time_seconds: float = 0.0
    interface_name: str | None = None

    def send(self, data: bytes) -> None:
        """Send all data over the transport connection."""
        send_exact(self.sock, data)

    def receive(self, num_bytes: int) -> bytes:
        """Receive exact byte count from the transport connection."""
        return recv_exact(self.sock, num_bytes)

    def close(self) -> None:
        """Close the underlying connection socket."""
        try:
            self.sock.close()
        except Exception:
            pass

    def __enter__(self) -> TransportConnection:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


class BaseTransportClient(ABC):
    """Abstract client interface for connection establishment."""

    @property
    @abstractmethod
    def transport_type(self) -> TransportType:
        """Return the transport type identifier."""
        pass

    @abstractmethod
    def connect(self, host: str, port: int, timeout: float = DEFAULT_SOCKET_TIMEOUT) -> TransportConnection:
        """Establish a network connection to target host and port."""
        pass


class LanTcpTransport(BaseTransportClient):
    """Standard infrastructure LAN TCP transport client."""

    @property
    def transport_type(self) -> TransportType:
        return TransportType.LAN_TCP

    def connect(self, host: str, port: int, timeout: float = DEFAULT_SOCKET_TIMEOUT) -> TransportConnection:
        start = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        # Optimize TCP socket for high throughput
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        try:
            sock.connect((host, port))
            connect_duration = time.perf_counter() - start
            local_addr = sock.getsockname()

            # Classify loopback vs LAN
            actual_type = (
                TransportType.LOOPBACK
                if host.startswith("127.") or host == "localhost"
                else TransportType.LAN_TCP
            )

            return TransportConnection(
                sock=sock,
                transport_type=actual_type,
                remote_host=host,
                remote_port=port,
                local_host=local_addr[0],
                local_port=local_addr[1],
                connect_time_seconds=connect_duration,
            )
        except Exception:
            sock.close()
            raise


class DirectWifiTransport(BaseTransportClient):
    """Direct Wi-Fi / SoftAP peer-to-peer transport client."""

    def __init__(self, bind_interface: str | None = None) -> None:
        self.bind_interface = bind_interface

    @property
    def transport_type(self) -> TransportType:
        return TransportType.DIRECT_WIFI

    def connect(self, host: str, port: int, timeout: float = 3.0) -> TransportConnection:
        """Connect directly over Wi-Fi without requiring an infrastructure router."""
        start = time.perf_counter()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)

        # Set TCP nodelay and socket buffer sizes for direct high-speed transfers
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        try:
            sock.connect((host, port))
            connect_duration = time.perf_counter() - start
            local_addr = sock.getsockname()

            return TransportConnection(
                sock=sock,
                transport_type=TransportType.DIRECT_WIFI,
                remote_host=host,
                remote_port=port,
                local_host=local_addr[0],
                local_port=local_addr[1],
                connect_time_seconds=connect_duration,
                interface_name=self.bind_interface,
            )
        except Exception:
            sock.close()
            raise


class FailoverTransportClient:
    """Manages connection establishment with primary Direct Wi-Fi and fallback to LAN TCP."""

    def __init__(
        self,
        direct_transport: DirectWifiTransport | None = None,
        lan_transport: LanTcpTransport | None = None,
        direct_timeout: float = 3.0,
        lan_timeout: float = DEFAULT_SOCKET_TIMEOUT,
    ) -> None:
        self.direct_transport = direct_transport or DirectWifiTransport()
        self.lan_transport = lan_transport or LanTcpTransport()
        self.direct_timeout = direct_timeout
        self.lan_timeout = lan_timeout

    def connect(
        self,
        lan_endpoint: tuple[str, int],
        direct_endpoint: tuple[str, int] | None = None,
        prefer_direct: bool = True,
    ) -> tuple[TransportConnection, list[str]]:
        """Attempt connection, trying direct transport first with graceful LAN fallback.

        Returns (TransportConnection, list_of_event_logs).
        """
        logs: list[str] = []

        # Attempt Direct Wi-Fi first if requested and endpoint provided
        if prefer_direct and direct_endpoint:
            direct_host, direct_port = direct_endpoint
            logger.info("Attempting Direct Wi-Fi transport connection to %s:%d ...", direct_host, direct_port)
            try:
                conn = self.direct_transport.connect(direct_host, direct_port, timeout=self.direct_timeout)
                msg = f"Connected via Direct Wi-Fi transport to {direct_host}:{direct_port} ({conn.connect_time_seconds*1000:.1f}ms)"
                logs.append(msg)
                logger.info(msg)
                return conn, logs
            except Exception as err:
                fail_msg = f"Direct Wi-Fi connection to {direct_host}:{direct_port} failed (reason: {err})"
                logs.append(fail_msg)
                logger.warning("%s. Falling back to LAN TCP (%s:%d)...", fail_msg, lan_endpoint[0], lan_endpoint[1])

        # Fallback to LAN TCP
        lan_host, lan_port = lan_endpoint
        logger.info("Connecting via LAN TCP transport to %s:%d ...", lan_host, lan_port)
        try:
            conn = self.lan_transport.connect(lan_host, lan_port, timeout=self.lan_timeout)
            msg = f"Connected via LAN TCP transport to {lan_host}:{lan_port} ({conn.connect_time_seconds*1000:.1f}ms)"
            logs.append(msg)
            logger.info(msg)
            return conn, logs
        except Exception as err:
            err_msg = f"LAN TCP connection to {lan_host}:{lan_port} failed: {err}"
            logs.append(err_msg)
            logger.error(err_msg)
            raise AirDropError(f"All transports failed. Direct: {logs[0] if logs else 'N/A'}, LAN: {err_msg}") from err


class DirectWifiManager:
    """Platform detection and instructions for routerless Direct Wi-Fi setup."""

    DEFAULT_DIRECT_SSID = "AirDrop-Direct"
    DEFAULT_DIRECT_PASS = "airdrop12345"
    DEFAULT_DIRECT_IP = "192.168.2.1"
    DEFAULT_CLIENT_IP = "192.168.2.2"

    @classmethod
    def get_platform_support(cls) -> dict[str, Any]:
        """Inspect and return platform capabilities for direct peer-to-peer Wi-Fi."""
        system = platform.system()
        res = {
            "platform": system,
            "release": platform.release(),
            "supports_awdl_public": False,  # AWDL is private on all macOS releases
            "supports_wifi_direct_p2p": False,
            "supports_softap_hotspot": False,
            "recommended_routerless_mode": "None",
            "notes": "",
        }

        if system == "Darwin":
            res["supports_awdl_public"] = False
            res["supports_softap_hotspot"] = True
            res["recommended_routerless_mode"] = "Wi-Fi SoftAP / Internet Sharing"
            res["notes"] = (
                "Apple AWDL is private and inaccessible to third-party apps. "
                "Routerless high-speed direct transfer on macOS is officially supported via Wi-Fi SoftAP "
                "(System Settings > General > Sharing > Internet Sharing, or Wi-Fi Hotspot)."
            )
        elif system == "Linux":
            res["supports_wifi_direct_p2p"] = True
            res["supports_softap_hotspot"] = True
            res["recommended_routerless_mode"] = "Wi-Fi Direct (wpa_supplicant / nmcli hotspot)"
            res["notes"] = (
                "Linux supports Wi-Fi Direct (P2P) via wpa_supplicant and Wi-Fi Hotspot mode via nmcli/hostapd."
            )
        elif system == "Windows":
            res["supports_wifi_direct_p2p"] = True
            res["supports_softap_hotspot"] = True
            res["recommended_routerless_mode"] = "Windows.Devices.WiFiDirect / Mobile Hotspot"
            res["notes"] = (
                "Windows 10/11 supports Wi-Fi Direct via WinRT and Hosted Network/Mobile Hotspot via netsh."
            )
        else:
            res["notes"] = f"Unsupported platform: {system}. Automatic LAN TCP fallback will be used."

        return res

    @classmethod
    def get_setup_guide(cls) -> str:
        """Return platform-specific instructions for establishing a routerless direct Wi-Fi link."""
        system = platform.system()
        if system == "Darwin":
            return (
                "=== macOS Routerless Direct Wi-Fi Setup ===\n"
                "1. On Receiver (Computer A):\n"
                "   - Option 1 (GUI): Open System Settings > General > Sharing > Internet Sharing.\n"
                "     Share your connection from Ethernet/iPhone to Wi-Fi, and set Wi-Fi Options (WPA2 Personal).\n"
                "   - Option 2 (Local Link-Local): Enable Wi-Fi. Receiver and Sender will use APIPA (169.254.x.x) or direct link.\n"
                "2. On Sender (Computer B):\n"
                "   - Connect directly to Computer A's Wi-Fi network.\n"
                "3. Once connected, run the Receiver on Computer A and Sender on Computer B.\n"
                "   Transfers stream directly between Wi-Fi antennas at maximum 802.11ac/ax speeds without a router.\n"
            )
        elif system == "Linux":
            return (
                "=== Linux Direct Wi-Fi (P2P / SoftAP) Setup ===\n"
                "1. On Receiver (Computer A):\n"
                "   nmcli dev wifi hotspot ifname wlan0 ssid AirDrop-Direct password airdrop12345\n"
                "2. On Sender (Computer B):\n"
                "   nmcli dev wifi connect AirDrop-Direct password airdrop12345\n"
                "3. Transfer files directly over the routerless point-to-point link.\n"
            )
        elif system == "Windows":
            return (
                "=== Windows Direct Wi-Fi / Mobile Hotspot Setup ===\n"
                "1. On Receiver (Computer A):\n"
                "   Turn ON 'Mobile Hotspot' in Windows Settings > Network & Internet > Mobile Hotspot.\n"
                "2. On Sender (Computer B):\n"
                "   Connect to the hotspot SSID.\n"
                "3. Transfer files directly at local Wi-Fi speeds without an external router.\n"
            )
        return "Automatic LAN TCP fallback is active for your operating system."
