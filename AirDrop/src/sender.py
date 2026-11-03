"""TCP Sender for AirDrop file transfer application."""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
import socket
import ssl
import sys
import time
from typing import Any, Callable

from src.discovery import (
    DiscoveredDevice,
    PeerBrowser,
    discover_peers_interactive,
)
from src.file_io import (
    compute_file_sha256,
    stream_file_chunks,
)
from src.protocol import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_SOCKET_TIMEOUT,
    AirDropError,
    AuthenticationError,
    ConcurrencyLimitError,
    ConnectionClosedError,
    TransferDeclinedError,
    encode_header,
    format_bytes,
    format_throughput,
    read_response_from_socket,
    send_exact,
)
from src.security import SecurityManager, compute_cert_fingerprint
from src.transport import (
    DirectWifiManager,
    FailoverTransportClient,
    TransportConnection,
    TransportType,
)

logger = logging.getLogger("airdrop.sender")


class Sender:
    """TCP File Sender client supporting Direct Wi-Fi, mTLS authentication, and automatic LAN fallback."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = DEFAULT_SOCKET_TIMEOUT,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        direct_host: str | None = None,
        direct_port: int | None = None,
        prefer_direct: bool = True,
        transport_client: FailoverTransportClient | None = None,
        use_tls: bool = False,
        security_manager: SecurityManager | None = None,
        display_name: str | None = None,
        pairing_callback: Callable[[str, str, str, Any], bool] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.chunk_size = chunk_size
        self.direct_host = direct_host
        self.direct_port = direct_port or port
        self.prefer_direct = prefer_direct
        self.transport_client = transport_client or FailoverTransportClient(
            lan_timeout=self.timeout
        )
        self.use_tls = use_tls
        self.security_manager = security_manager
        self.display_name = display_name or socket.gethostname().split(".")[0]
        self.pairing_callback = pairing_callback

    def send_file(
        self,
        file_path: str | Path,
        precompute_sha256: bool = False,
        wait_for_ack: bool = True,
        progress_callback: Callable[[int, int], None] | None = None,
        cancellation_token: threading.Event | None = None,
    ) -> dict[str, Any]:
        """Send a file to the receiver using direct transport with LAN fallback.

        Returns transfer metrics dictionary upon success.
        """
        path = Path(file_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"File does not exist: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a regular file: {path}")

        filesize = path.stat().st_size
        filename = path.name

        precomputed_hash: str | None = None
        if precompute_sha256:
            logger.info("Precomputing SHA-256 for '%s'...", filename)
            precomputed_hash = compute_file_sha256(path, chunk_size=self.chunk_size)
            logger.info("Precomputed SHA-256: %s", precomputed_hash)

        # Connection establishment separated from transfer logic
        direct_endpoint = (self.direct_host, self.direct_port) if self.direct_host else None
        conn, transport_logs = self.transport_client.connect(
            lan_endpoint=(self.host, self.port),
            direct_endpoint=direct_endpoint,
            prefer_direct=self.prefer_direct,
        )
        logger.info("Active Transport: %s (%s:%d)", conn.transport_type.value, conn.remote_host, conn.remote_port)

        sock = conn.sock
        server_fp: str | None = None
        try:
            # Step 0.5: mTLS Handshake & Verification if enabled
            if self.use_tls:
                if not self.security_manager:
                    self.security_manager = SecurityManager(display_name=self.display_name)
                client_ctx = self.security_manager.create_client_ssl_context()
                try:
                    sock = client_ctx.wrap_socket(conn.sock, server_side=False)
                    conn.sock = sock
                except ssl.SSLError as err:
                    logger.error("TLS client handshake failed: %s", err)
                    raise AuthenticationError(f"TLS handshake failed: {err}") from err

                server_cert_der = sock.getpeercert(binary_form=True)
                if server_cert_der:
                    server_fp = compute_cert_fingerprint(server_cert_der)
                    logger.info("TLS mTLS connection established (Server Fingerprint: %s)", server_fp)

                    trusted = self.security_manager.peer_store.is_trusted(self.host, server_fp)
                    if not trusted:
                        peer_rec = self.security_manager.peer_store.get_peer_by_fingerprint(server_fp)
                        if peer_rec:
                            trusted = True
                    if not trusted:
                        paired = False
                        if self.pairing_callback:
                            paired = self.pairing_callback(self.host, self.host, server_fp, sock.getpeercert(binary_form=False))
                        if paired:
                            cert_pem = ssl.DER_cert_to_PEM_cert(server_cert_der)
                            self.security_manager.peer_store.add_peer(f"peer_{server_fp[:8]}", self.host, cert_pem)
                            trusted = True
                        else:
                            raise AuthenticationError(f"Server certificate with fingerprint {server_fp} is not trusted.")

            # Step 1: Send Header
            node_id = self.security_manager.node_id if self.security_manager else "anonymous"
            extra: dict[str, Any] = {
                "secure": self.use_tls,
                "sender_name": self.display_name,
                "node_id": node_id,
            }
            if precomputed_hash:
                extra["sha256"] = precomputed_hash

            header_bytes = encode_header(filename, filesize, extra=extra)
            send_exact(sock, header_bytes)
            logger.debug("Sent header frame (%d bytes)", len(header_bytes))

            # Step 1.5: If secure mode, wait for recipient approval before sending chunks
            if self.use_tls:
                logger.info("Waiting for recipient approval for '%s'...", filename)
                approval_resp = read_response_from_socket(sock)
                app_status = approval_resp.get("status")
                app_msg = approval_resp.get("message", "")

                if app_status == "declined":
                    logger.warning("Recipient declined the file transfer: %s", app_msg)
                    raise TransferDeclinedError(f"Recipient declined file transfer: {app_msg}")
                elif app_status == "busy":
                    logger.warning("Receiver is busy: %s", app_msg)
                    raise ConcurrencyLimitError(f"Receiver busy: {app_msg}")
                elif app_status != "ok":
                    logger.error("Receiver rejected transfer: %s", app_msg)
                    raise AirDropError(f"Receiver error: {app_msg}")
                logger.info("Recipient approved transfer: %s", app_msg)

            # Step 2: Stream File Chunks
            logger.info(
                "Starting transfer of '%s' (%s, %d bytes) over %s [TLS: %s]...",
                filename,
                format_bytes(filesize),
                filesize,
                conn.transport_type.value,
                self.use_tls,
            )
            hasher = hashlib.sha256()
            bytes_sent = 0
            transfer_start = time.perf_counter()

            for chunk in stream_file_chunks(path, chunk_size=self.chunk_size):
                if cancellation_token and cancellation_token.is_set():
                    logger.info("Transfer cancelled by user during transmission of '%s'.", filename)
                    raise AirDropError(f"Transfer of '{filename}' cancelled by user.")
                send_exact(sock, chunk)
                hasher.update(chunk)
                bytes_sent += len(chunk)
                if progress_callback:
                    try:
                        progress_callback(bytes_sent, filesize)
                    except Exception as p_err:
                        logger.debug("Error in progress callback: %s", p_err)

            transfer_duration = time.perf_counter() - transfer_start
            sender_sha256 = hasher.hexdigest()

            if bytes_sent != filesize:
                raise AirDropError(
                    f"Transferred byte count mismatch: sent {bytes_sent} bytes, expected {filesize} bytes."
                )

            # Step 3: Wait for Receiver Acknowledgment
            ack_data: dict[str, Any] = {}
            if wait_for_ack:
                logger.info("Waiting for receiver acknowledgment...")
                try:
                    ack_data = read_response_from_socket(sock)
                except ConnectionClosedError as err:
                    raise AirDropError(
                        "Receiver closed connection without sending acknowledgment."
                    ) from err

                status = ack_data.get("status")
                message = ack_data.get("message", "")

                if status != "ok":
                    raise AirDropError(f"Receiver reported error: {message}")

                receiver_sha256 = ack_data.get("sha256")
                if receiver_sha256:
                    if receiver_sha256.lower() != sender_sha256.lower():
                        raise AirDropError(
                            f"Integrity check failed! Sender SHA-256: {sender_sha256}, "
                            f"Receiver SHA-256: {receiver_sha256}"
                        )
                    logger.info("Integrity verified: SHA-256 matches receiver (%s)", receiver_sha256)

            throughput_str = format_throughput(bytes_sent, transfer_duration)

            logger.info("=" * 60)
            logger.info("Transfer Succeeded: %s", filename)
            logger.info("Transport:         %s", conn.transport_type.value)
            logger.info("Destination:       %s:%d", conn.remote_host, conn.remote_port)
            logger.info("Bytes transferred: %s (%d bytes)", format_bytes(bytes_sent), bytes_sent)
            logger.info("Transfer duration: %.3f s", transfer_duration)
            logger.info("Average throughput:%s", throughput_str)
            logger.info("SHA-256 digest:    %s", sender_sha256)
            logger.info("=" * 60)

            return {
                "filename": filename,
                "filesize": bytes_sent,
                "duration": transfer_duration,
                "throughput_str": throughput_str,
                "sha256": sender_sha256,
                "transport_type": conn.transport_type.value,
                "transport_logs": transport_logs,
                "is_tls": self.use_tls,
                "server_fingerprint": server_fp,
                "ack": ack_data,
            }

        except ssl.SSLError as err:
            logger.error("TLS error during transfer: %s", err)
            raise AuthenticationError(f"TLS authentication failure: {err}") from err
        except (ConnectionError, BrokenPipeError) as err:
            logger.error("Connection severed during transfer: %s", err)
            raise ConnectionClosedError(f"Connection lost during transfer: {err}") from err
        finally:
            conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AirDrop TCP Sender - Send a file to a remote receiver."
    )
    # Support both positional arguments and flags
    parser.add_argument(
        "pos_host",
        nargs="?",
        help="Receiver IP address or hostname",
    )
    parser.add_argument(
        "pos_port",
        nargs="?",
        type=int,
        help="Receiver TCP port number",
    )
    parser.add_argument(
        "pos_file",
        nargs="?",
        help="Path to the file to transfer",
    )
    parser.add_argument(
        "--host",
        dest="flag_host",
        help="Receiver IP address or hostname",
    )
    parser.add_argument(
        "-p", "--port",
        dest="flag_port",
        type=int,
        help="Receiver TCP port number",
    )
    parser.add_argument(
        "-f", "--file",
        dest="flag_file",
        help="Path to the file to transfer",
    )
    parser.add_argument(
        "--to",
        help="Target device display name or IP to find automatically via mDNS",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Scan LAN for AirDrop receivers and select interactively",
    )
    parser.add_argument(
        "--no-ble",
        action="store_true",
        help="Disable BLE scanning and use mDNS only",
    )
    parser.add_argument(
        "--direct-host",
        help="Direct Wi-Fi endpoint IP (e.g. 192.168.2.1) to attempt before LAN fallback",
    )
    parser.add_argument(
        "--direct-port",
        type=int,
        help="Direct Wi-Fi endpoint port (default: same as receiver port)",
    )
    parser.add_argument(
        "--no-direct",
        action="store_true",
        help="Disable Direct Wi-Fi transport attempt and connect only via LAN TCP",
    )
    parser.add_argument(
        "--info-direct",
        action="store_true",
        help="Print platform Direct Wi-Fi setup guide and exit",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_SOCKET_TIMEOUT,
        help=f"Socket timeout in seconds (default: {DEFAULT_SOCKET_TIMEOUT})",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help=f"Streaming chunk size in bytes (default: {DEFAULT_CHUNK_SIZE})",
    )
    parser.add_argument(
        "--secure",
        action="store_true",
        help="Enable mTLS authenticated encryption and peer verification",
    )
    parser.add_argument(
        "--precompute-hash",
        action="store_true",
        help="Precalculate SHA-256 before sending (included in header)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )

    args = parser.parse_args()

    if args.info_direct:
        print(DirectWifiManager.get_setup_guide())
        info = DirectWifiManager.get_platform_support()
        print("Platform Direct Support Summary:")
        for k, v in info.items():
            print(f"  {k}: {v}")
        sys.exit(0)

    pos1 = args.pos_host
    pos2 = args.pos_port
    pos3 = args.pos_file

    file_path = args.flag_file
    host = args.flag_host
    port = args.flag_port

    if pos3 is not None:
        # Full 3 positional args: <host> <port> <file>
        host = host or pos1
        port = port or pos2
        file_path = file_path or pos3
    elif pos1 is not None and file_path is None:
        # 1 positional arg: treated as file path
        file_path = pos1

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # If host/port not given, or if --discover or --to was requested, use mDNS discovery
    if (not host or not port) or args.discover or args.to:
        if not file_path:
            parser.error(
                "A file path must be specified.\n"
                "Usage: python -m src.sender <file> (auto-discovers receiver)\n"
                "   or: python -m src.sender --to <device_name> <file>\n"
                "   or: python -m src.sender <host> <port> <file>"
            )

        browser = PeerBrowser(enable_ble=not args.no_ble)
        browser.start()
        try:
            target_device = None
            if args.to:
                logger.info("Searching LAN/BLE for AirDrop receiver matching '%s'...", args.to)
                start_search = time.time()
                while time.time() - start_search < 3.5:
                    target_device = browser.registry.find_device(args.to, only_reachable=True) or browser.find_device(args.to)
                    if target_device:
                        break
                    time.sleep(0.2)
                if not target_device:
                    logger.error("Device matching '%s' not found on the local network or BLE.", args.to)
                    sys.exit(2)
            else:
                target_device = discover_peers_interactive(scan_seconds=2.5, browser=browser)
                if not target_device:
                    logger.info("No target device selected. Exiting.")
                    sys.exit(0)

            if hasattr(target_device, "ip_address") and target_device.ip_address:
                host = target_device.ip_address
            else:
                host = getattr(target_device, "primary_address", None)
            port = target_device.port

            if not host or not port:
                logger.error(
                    "Device '%s' was discovered via BLE proximity, but has not resolved an IP address. "
                    "Cannot initiate TCP file transfer.",
                    target_device.display_name,
                )
                sys.exit(3)

            logger.info(
                "Target acquired: '%s' (%s:%d)",
                target_device.display_name,
                host,
                port,
            )
        finally:
            browser.stop()

    if not host or not port or not file_path:
        parser.error(
            "Missing required arguments. Usage: python -m src.sender <host> <port> <file_path>\n"
            "or use discovery: python -m src.sender --to <device_name> <file_path>"
        )

    sender = Sender(
        host=host,
        port=port,
        timeout=args.timeout,
        chunk_size=args.chunk_size,
        direct_host=args.direct_host,
        direct_port=args.direct_port,
        prefer_direct=not args.no_direct,
        use_tls=args.secure,
    )

    try:
        sender.send_file(
            file_path=file_path,
            precompute_sha256=args.precompute_hash,
        )
    except FileNotFoundError as err:
        logger.error("File error: %s", err)
        sys.exit(1)
    except ConnectionRefusedError:
        logger.error(
            "Connection refused. Please ensure the receiver is running on %s:%d and accessible.",
            host,
            port,
        )
        sys.exit(2)
    except AirDropError as err:
        logger.error("Transfer failed: %s", err)
        sys.exit(3)
    except Exception as err:
        logger.error("Unexpected error: %s", err)
        sys.exit(4)


if __name__ == "__main__":
    main()
