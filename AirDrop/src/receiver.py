"""TCP Receiver for AirDrop file transfer application."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import socket
import sys
import time
from typing import Any

from src.discovery import ServiceAdvertiser
from src.file_io import (
    AtomicFileWriter,
    check_disk_space,
    resolve_destination_path,
)
from src.protocol import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_MAX_HEADER_SIZE,
    DEFAULT_SOCKET_TIMEOUT,
    AirDropError,
    ConnectionClosedError,
    DiskSpaceError,
    HeaderTooLargeError,
    OversizedFileError,
    PathTraversalError,
    ProtocolError,
    TruncatedTransferError,
    encode_response,
    format_bytes,
    format_throughput,
    read_header_from_socket,
    send_exact,
)

logger = logging.getLogger("airdrop.receiver")


class Receiver:
    """TCP File Receiver server."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5001,
        dest_dir: str | Path = "./received",
        timeout: float = DEFAULT_SOCKET_TIMEOUT,
        max_header_size: int = DEFAULT_MAX_HEADER_SIZE,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        allow_overwrite: bool = False,
        advertise: bool = True,
        display_name: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.dest_dir = Path(dest_dir).resolve()
        self.timeout = timeout
        self.max_header_size = max_header_size
        self.max_file_size = max_file_size
        self.allow_overwrite = allow_overwrite
        self.advertise = advertise
        self.display_name = display_name

        self.server_sock: socket.socket | None = None
        self._running = False
        self.active_port: int | None = None
        self.advertiser: ServiceAdvertiser | None = None

    def start(self, single_transfer: bool = False) -> None:
        """Start listening for incoming TCP file transfers."""
        self.dest_dir.mkdir(parents=True, exist_ok=True)

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen(5)
        # Configure short timeout on accept to allow clean shutdown checks
        self.server_sock.settimeout(0.5)

        self.active_port = self.server_sock.getsockname()[1]
        self._running = True

        logger.info("=" * 60)
        logger.info("AirDrop Receiver listening on %s:%d", self.host, self.active_port)
        logger.info("Destination directory: %s", self.dest_dir)
        logger.info("Max file size: %s", format_bytes(self.max_file_size))
        logger.info("=" * 60)

        if self.advertise and self.active_port is not None:
            try:
                self.advertiser = ServiceAdvertiser(
                    port=self.active_port,
                    display_name=self.display_name,
                )
                self.advertiser.start()
            except Exception as err:
                logger.warning("Could not start mDNS advertisement: %s", err)

        try:
            while self._running:
                try:
                    client_sock, client_addr = self.server_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                logger.info("Connection accepted from %s:%d", client_addr[0], client_addr[1])
                try:
                    self.handle_client(client_sock, client_addr)
                except Exception as err:
                    logger.error("Error processing connection from %s:%d: %s", client_addr[0], client_addr[1], err)
                finally:
                    try:
                        client_sock.close()
                    except Exception:
                        pass

                if single_transfer:
                    logger.info("Single transfer requested. Stopping receiver.")
                    break
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop listening and close server socket."""
        self._running = False
        if self.advertiser:
            try:
                self.advertiser.stop()
            except Exception as err:
                logger.debug("Error stopping advertiser: %s", err)
            self.advertiser = None

        if self.server_sock:
            try:
                self.server_sock.close()
            except Exception:
                pass
            self.server_sock = None
        logger.info("Receiver server stopped.")

    def handle_client(
        self, client_sock: socket.socket, client_addr: tuple[str, int]
    ) -> dict[str, Any] | None:
        """Handle an individual incoming file transfer session."""
        client_sock.settimeout(self.timeout)
        start_time = time.perf_counter()

        # Step 1: Read and validate header
        try:
            header, wire_header_len = read_header_from_socket(
                client_sock,
                max_header_size=self.max_header_size,
                max_file_size=self.max_file_size,
            )
        except (HeaderTooLargeError, ProtocolError, OversizedFileError) as err:
            logger.error("Rejected transfer from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(client_sock, f"Protocol error: {err}")
            raise
        except (ConnectionClosedError, socket.timeout) as err:
            logger.error("Client %s:%d disconnected or timed out during header: %s", client_addr[0], client_addr[1], err)
            raise

        filename = header["filename"]
        filesize = header["filesize"]
        expected_sha256 = header.get("sha256")

        logger.info(
            "Transfer requested: '%s' (%s, %d bytes) from %s:%d",
            filename,
            format_bytes(filesize),
            filesize,
            client_addr[0],
            client_addr[1],
        )

        # Step 2: Validate filename & resolve destination
        try:
            target_path = resolve_destination_path(
                self.dest_dir, filename, allow_overwrite=self.allow_overwrite
            )
        except PathTraversalError as err:
            logger.error("Security violation from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(client_sock, f"Security rejection: {err}")
            raise

        # Step 3: Check free disk space
        try:
            check_disk_space(self.dest_dir, filesize)
        except DiskSpaceError as err:
            logger.error("Insufficient disk space for '%s': %s", filename, err)
            self._send_error_response(client_sock, f"Storage error: {err}")
            raise

        # Step 4: Stream payload to temporary atomic file
        writer = AtomicFileWriter(target_path)
        transfer_start = time.perf_counter()
        received_bytes = 0

        try:
            with writer:
                while received_bytes < filesize:
                    to_read = min(filesize - received_bytes, DEFAULT_CHUNK_SIZE)
                    chunk = client_sock.recv(to_read)
                    if not chunk:
                        raise TruncatedTransferError(
                            f"Connection closed prematurely after {received_bytes}/{filesize} bytes.",
                            received_bytes=received_bytes,
                            expected_bytes=filesize,
                        )
                    writer.write(chunk)
                    received_bytes += len(chunk)

                final_path, computed_sha256 = writer.commit()
        except TruncatedTransferError as err:
            logger.error("Transfer truncated from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(client_sock, f"Truncated transfer: {err}")
            raise
        except socket.timeout as err:
            logger.error("Transfer timed out from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(client_sock, "Transfer timed out")
            raise
        except Exception as err:
            logger.error("Transfer failed for '%s': %s", filename, err)
            self._send_error_response(client_sock, f"Server write error: {err}")
            raise

        # Step 5: Verify SHA-256 integrity if provided
        if expected_sha256 and expected_sha256.lower() != computed_sha256.lower():
            logger.error(
                "SHA-256 mismatch for '%s'! Expected: %s, Computed: %s",
                filename,
                expected_sha256,
                computed_sha256,
            )
            # Remove corrupted file
            try:
                final_path.unlink()
            except Exception:
                pass
            self._send_error_response(client_sock, "Checksum mismatch")
            raise AirDropError("Checksum mismatch")

        # Step 6: Send success acknowledgment
        try:
            ack_payload = {
                "sha256": computed_sha256,
                "bytes_received": received_bytes,
                "saved_as": final_path.name,
            }
            send_exact(client_sock, encode_response("ok", "Transfer complete", extra=ack_payload))
        except Exception as err:
            logger.warning("Could not send ACK to %s:%d: %s", client_addr[0], client_addr[1], err)

        transfer_duration = time.perf_counter() - transfer_start
        overall_duration = time.perf_counter() - start_time
        throughput_str = format_throughput(received_bytes, transfer_duration)

        logger.info("-" * 60)
        logger.info("Transfer Complete: %s", final_path.name)
        logger.info("Saved to:          %s", final_path)
        logger.info("Bytes transferred: %s (%d bytes)", format_bytes(received_bytes), received_bytes)
        logger.info("Payload duration:  %.3f s (Overall: %.3f s)", transfer_duration, overall_duration)
        logger.info("Average throughput:%s", throughput_str)
        logger.info("SHA-256 digest:    %s", computed_sha256)
        logger.info("-" * 60)

        return {
            "filename": filename,
            "saved_path": final_path,
            "filesize": received_bytes,
            "sha256": computed_sha256,
            "duration": transfer_duration,
            "throughput_str": throughput_str,
        }

    def _send_error_response(self, sock: socket.socket, message: str) -> None:
        """Attempt to send an error response frame before closing socket."""
        try:
            frame = encode_response("error", message)
            sock.sendall(frame)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AirDrop TCP Receiver - Listen for incoming file transfers."
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host IP address to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=5001,
        help="TCP port to listen on (default: 5001)",
    )
    parser.add_argument(
        "-d", "--dest-dir",
        default="./received",
        help="Directory to save received files (default: ./received)",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Exit after receiving one file transfer",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing files instead of creating (1), (2), etc.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_SOCKET_TIMEOUT,
        help=f"Socket timeout in seconds (default: {DEFAULT_SOCKET_TIMEOUT})",
    )
    parser.add_argument(
        "--name",
        help="Custom device display name to advertise via mDNS (default: machine hostname)",
    )
    parser.add_argument(
        "--no-advertise",
        action="store_true",
        help="Disable mDNS / DNS-SD local network advertisement",
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

    receiver = Receiver(
        host=args.host,
        port=args.port,
        dest_dir=args.dest_dir,
        timeout=args.timeout,
        allow_overwrite=args.overwrite,
        advertise=not args.no_advertise,
        display_name=args.name,
    )

    try:
        receiver.start(single_transfer=args.single)
    except KeyboardInterrupt:
        logger.info("\nReceiver interrupted by user. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
