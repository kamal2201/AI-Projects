"""TCP Sender for AirDrop file transfer application."""

from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path
import socket
import sys
import time
from typing import Any

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
    ConnectionClosedError,
    encode_header,
    format_bytes,
    format_throughput,
    read_response_from_socket,
    send_exact,
)

logger = logging.getLogger("airdrop.sender")


class Sender:
    """TCP File Sender client."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = DEFAULT_SOCKET_TIMEOUT,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.chunk_size = chunk_size

    def send_file(
        self,
        file_path: str | Path,
        precompute_sha256: bool = False,
        wait_for_ack: bool = True,
    ) -> dict[str, Any]:
        """Send a file to the configured receiver over TCP.

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

        logger.info("Connecting to receiver at %s:%d ...", self.host, self.port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)

        try:
            sock.connect((self.host, self.port))
            logger.info("Connected to %s:%d", self.host, self.port)

            # Step 1: Send Header
            extra = {"sha256": precomputed_hash} if precomputed_hash else None
            header_bytes = encode_header(filename, filesize, extra=extra)
            send_exact(sock, header_bytes)
            logger.debug("Sent header frame (%d bytes)", len(header_bytes))

            # Step 2: Stream File Chunks
            logger.info(
                "Starting transfer of '%s' (%s, %d bytes)...",
                filename,
                format_bytes(filesize),
                filesize,
            )
            hasher = hashlib.sha256()
            bytes_sent = 0
            transfer_start = time.perf_counter()

            for chunk in stream_file_chunks(path, chunk_size=self.chunk_size):
                send_exact(sock, chunk)
                hasher.update(chunk)
                bytes_sent += len(chunk)

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
            logger.info("Destination:       %s:%d", self.host, self.port)
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
                "ack": ack_data,
            }

        finally:
            try:
                sock.close()
            except Exception:
                pass


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

        browser = PeerBrowser()
        browser.start()
        try:
            target_device: DiscoveredDevice | None = None
            if args.to:
                logger.info("Searching LAN for AirDrop receiver matching '%s'...", args.to)
                start_search = time.time()
                while time.time() - start_search < 3.5:
                    target_device = browser.find_device(args.to)
                    if target_device:
                        break
                    time.sleep(0.2)
                if not target_device:
                    logger.error("Device matching '%s' not found on the local network.", args.to)
                    sys.exit(2)
            else:
                target_device = discover_peers_interactive(scan_seconds=2.5, browser=browser)
                if not target_device:
                    logger.info("No target device selected. Exiting.")
                    sys.exit(0)

            host = target_device.primary_address
            port = target_device.port
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
