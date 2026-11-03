"""TCP Receiver for AirDrop file transfer application."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import socket
import ssl
import sys
import threading
import time
from typing import Any, Callable

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
    AuthenticationError,
    ConcurrencyLimitError,
    ConnectionClosedError,
    DiskSpaceError,
    HeaderTooLargeError,
    OversizedFileError,
    PathTraversalError,
    ProtocolError,
    TransferDeclinedError,
    TruncatedTransferError,
    encode_response,
    format_bytes,
    format_throughput,
    read_header_from_socket,
    send_exact,
)
from src.security import SecurityManager, compute_cert_fingerprint
from src.transport import DirectWifiManager, TransportType

logger = logging.getLogger("airdrop.receiver")


class Receiver:
    """TCP File Receiver server supporting mTLS authenticated encryption and recipient approval."""

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
        enable_ble: bool = True,
        display_name: str | None = None,
        use_tls: bool = False,
        allow_plain_tcp: bool = True,
        security_manager: SecurityManager | None = None,
        require_approval: bool = False,
        approval_callback: Callable[[str, int, str, str], bool] | None = None,
        auto_accept: bool = False,
        max_concurrent_transfers: int = 5,
        pairing_callback: Callable[[str, str, str, Any], bool] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.dest_dir = Path(dest_dir).resolve()
        self.timeout = timeout
        self.max_header_size = max_header_size
        self.max_file_size = max_file_size
        self.allow_overwrite = allow_overwrite
        self.advertise = advertise
        self.enable_ble = enable_ble
        self.display_name = display_name

        self.use_tls = use_tls
        self.allow_plain_tcp = allow_plain_tcp
        self.security_manager = security_manager
        self.require_approval = require_approval
        self.approval_callback = approval_callback
        self.auto_accept = auto_accept
        self.max_concurrent_transfers = max_concurrent_transfers
        self.pairing_callback = pairing_callback

        self.server_sock: socket.socket | None = None
        self._running = False
        self.active_port: int | None = None
        self.advertiser: ServiceAdvertiser | None = None
        self._active_transfers = 0
        self._lock = threading.Lock()

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
                    enable_ble=self.enable_ble,
                )
                self.advertiser.start()
            except Exception as err:
                logger.warning("Could not start service advertisement: %s", err)

        try:
            while self._running:
                try:
                    client_sock, client_addr = self.server_sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break

                # Determine transport type based on incoming client IP
                if client_addr[0].startswith("127.") or client_addr[0] == "::1":
                    inferred_transport = TransportType.LOOPBACK
                elif client_addr[0].startswith("192.168.2.") or client_addr[0].startswith("169.254."):
                    inferred_transport = TransportType.DIRECT_WIFI
                else:
                    inferred_transport = TransportType.LAN_TCP

                logger.info("Connection accepted via %s from %s:%d", inferred_transport.value, client_addr[0], client_addr[1])

                # Enforce concurrency limit
                with self._lock:
                    if self._active_transfers >= self.max_concurrent_transfers:
                        logger.warning(
                            "Rejecting connection from %s:%d: concurrent transfer limit reached (%d)",
                            client_addr[0], client_addr[1], self.max_concurrent_transfers
                        )
                        self._send_error_response(client_sock, "Server busy: concurrent transfer limit reached", status="busy")
                        client_sock.close()
                        continue
                    self._active_transfers += 1

                try:
                    self.handle_client(client_sock, client_addr)
                except Exception as err:
                    logger.error("Error processing connection from %s:%d: %s", client_addr[0], client_addr[1], err)
                finally:
                    with self._lock:
                        self._active_transfers -= 1
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

        if client_addr[0].startswith("127.") or client_addr[0] == "::1":
            inferred_transport = TransportType.LOOPBACK
        elif client_addr[0].startswith("192.168.2.") or client_addr[0].startswith("169.254."):
            inferred_transport = TransportType.DIRECT_WIFI
        else:
            inferred_transport = TransportType.LAN_TCP

        # Step 0: Check for TLS Handshake vs Plain TCP
        active_sock = client_sock
        is_tls = False
        peer_cert_fp = None
        peer_cert_der = None

        try:
            peek_byte = client_sock.recv(1, socket.MSG_PEEK)
            if peek_byte == b"\x16":
                is_tls = True
        except Exception:
            pass

        if is_tls:
            if not self.security_manager:
                self.security_manager = SecurityManager(display_name=self.display_name)
            ssl_ctx = self.security_manager.create_server_ssl_context(require_client_cert=True)
            try:
                active_sock = ssl_ctx.wrap_socket(client_sock, server_side=True)
                peer_cert_der = active_sock.getpeercert(binary_form=True)
                if peer_cert_der:
                    peer_cert_fp = compute_cert_fingerprint(peer_cert_der)
                    logger.info("TLS mTLS handshake established with %s:%d (Fingerprint: %s)", client_addr[0], client_addr[1], peer_cert_fp)
            except ssl.SSLError as err:
                logger.error("TLS authentication failed from %s:%d: %s", client_addr[0], client_addr[1], err)
                raise AuthenticationError(f"TLS authentication failure: {err}") from err
        elif not self.allow_plain_tcp:
            logger.error("Rejecting unencrypted connection from %s:%d: plaintext TCP prohibited", client_addr[0], client_addr[1])
            self._send_error_response(client_sock, "Authentication required: plaintext TCP prohibited", status="unauthorized")
            raise AuthenticationError("Plaintext connections prohibited; strict TLS required.")

        try:
            return self._process_transfer(
                active_sock=active_sock,
                client_addr=client_addr,
                inferred_transport=inferred_transport,
                is_tls=is_tls,
                peer_cert_fp=peer_cert_fp,
                peer_cert_der=peer_cert_der,
                start_time=start_time,
            )
        finally:
            if active_sock is not client_sock:
                try:
                    active_sock.close()
                except Exception:
                    pass

    def _process_transfer(
        self,
        active_sock: socket.socket,
        client_addr: tuple[str, int],
        inferred_transport: TransportType,
        is_tls: bool,
        peer_cert_fp: str | None,
        peer_cert_der: bytes | None,
        start_time: float,
    ) -> dict[str, Any] | None:
        # Step 1: Read and validate header
        try:
            header, wire_header_len = read_header_from_socket(
                active_sock,
                max_header_size=self.max_header_size,
                max_file_size=self.max_file_size,
            )
        except (HeaderTooLargeError, ProtocolError, OversizedFileError) as err:
            logger.error("Rejected transfer from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(active_sock, f"Protocol error: {err}")
            raise
        except (ConnectionClosedError, socket.timeout) as err:
            logger.error("Client %s:%d disconnected or timed out during header: %s", client_addr[0], client_addr[1], err)
            raise

        filename = header["filename"]
        filesize = header["filesize"]
        expected_sha256 = header.get("sha256")
        sender_node_id = header.get("node_id", "")
        sender_name = header.get("sender_name", client_addr[0])

        # Step 1.1: Verify Peer Cryptographic Identity if TLS
        if is_tls and peer_cert_fp and self.security_manager:
            trusted = self.security_manager.peer_store.is_trusted(sender_node_id, peer_cert_fp)
            if not trusted:
                peer_record = self.security_manager.peer_store.get_peer_by_fingerprint(peer_cert_fp)
                if peer_record:
                    trusted = True

            if not trusted:
                # Check pairing callback
                paired = False
                if self.pairing_callback:
                    paired = self.pairing_callback(sender_node_id, sender_name, peer_cert_fp, active_sock.getpeercert(binary_form=False))
                if paired and peer_cert_der:
                    cert_pem = ssl.DER_cert_to_PEM_cert(peer_cert_der)
                    self.security_manager.peer_store.add_peer(sender_node_id, sender_name, cert_pem)
                    trusted = True

            if not trusted:
                logger.warning("Rejected untrusted peer '%s' (%s) with fingerprint %s", sender_name, sender_node_id, peer_cert_fp)
                self._send_error_response(active_sock, "Untrusted peer certificate: pairing required", status="unauthorized")
                raise AuthenticationError(f"Peer '{sender_name}' ({sender_node_id}) is not trusted.")

        logger.info(
            "Transfer requested: '%s' (%s, %d bytes) from %s:%d [TLS: %s]",
            filename,
            format_bytes(filesize),
            filesize,
            client_addr[0],
            client_addr[1],
            is_tls,
        )

        # Step 1.2: Explicit Recipient Approval Gate
        requires_approval = header.get("secure", False) or self.require_approval
        if requires_approval:
            approved = False
            if self.auto_accept:
                approved = True
            elif self.approval_callback:
                approved = self.approval_callback(filename, filesize, sender_name, sender_node_id)
            else:
                try:
                    ans = input(
                        f"\n[AirDrop Transfer Request]\nIncoming file: '{filename}' ({format_bytes(filesize)})\n"
                        f"From: '{sender_name}' ({client_addr[0]})\nAccept transfer? [y/N]: "
                    ).strip().lower()
                    approved = ans in ("y", "yes")
                except Exception:
                    approved = False

            if not approved:
                logger.warning("Recipient declined file transfer for '%s'", filename)
                self._send_error_response(active_sock, "Recipient declined file transfer", status="declined")
                raise TransferDeclinedError(f"Transfer of '{filename}' declined by recipient.")

            # Notify sender that recipient approved the transfer
            send_exact(active_sock, encode_response("ok", "Transfer approved by recipient"))

        # Step 2: Validate filename & resolve destination
        try:
            target_path = resolve_destination_path(
                self.dest_dir, filename, allow_overwrite=self.allow_overwrite
            )
        except PathTraversalError as err:
            logger.error("Security violation from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(active_sock, f"Security rejection: {err}")
            raise

        # Step 3: Check free disk space
        try:
            check_disk_space(self.dest_dir, filesize)
        except DiskSpaceError as err:
            logger.error("Insufficient disk space for '%s': %s", filename, err)
            self._send_error_response(active_sock, f"Storage error: {err}")
            raise

        # Step 4: Stream payload to temporary atomic file
        writer = AtomicFileWriter(target_path)
        transfer_start = time.perf_counter()
        received_bytes = 0

        try:
            with writer:
                while received_bytes < filesize:
                    to_read = min(filesize - received_bytes, DEFAULT_CHUNK_SIZE)
                    chunk = active_sock.recv(to_read)
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
            self._send_error_response(active_sock, f"Truncated transfer: {err}")
            raise
        except socket.timeout as err:
            logger.error("Transfer timed out from %s:%d: %s", client_addr[0], client_addr[1], err)
            self._send_error_response(active_sock, "Transfer timed out")
            raise
        except Exception as err:
            logger.error("Transfer failed for '%s': %s", filename, err)
            self._send_error_response(active_sock, f"Server write error: {err}")
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
            self._send_error_response(active_sock, "Checksum mismatch")
            raise AirDropError("Checksum mismatch")

        # Step 6: Send success acknowledgment
        try:
            ack_payload = {
                "sha256": computed_sha256,
                "bytes_received": received_bytes,
                "saved_as": final_path.name,
            }
            send_exact(active_sock, encode_response("ok", "Transfer complete", extra=ack_payload))
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
        logger.info("Encrypted TLS:     %s", is_tls)
        logger.info("-" * 60)

        return {
            "filename": filename,
            "saved_path": final_path,
            "filesize": received_bytes,
            "sha256": computed_sha256,
            "duration": transfer_duration,
            "throughput_str": throughput_str,
            "transport_type": inferred_transport.value,
            "is_tls": is_tls,
            "peer_fingerprint": peer_cert_fp,
        }

    def _send_error_response(self, sock: socket.socket, message: str, status: str = "error") -> None:
        """Attempt to send an error response frame before closing socket."""
        try:
            frame = encode_response(status, message)
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
        "--no-ble",
        action="store_true",
        help="Disable BLE peripheral advertisement",
    )
    parser.add_argument(
        "--info-direct",
        action="store_true",
        help="Print platform Direct Wi-Fi setup guide and exit",
    )
    parser.add_argument(
        "--secure",
        action="store_true",
        help="Enable mTLS authenticated encryption and identity verification",
    )
    parser.add_argument(
        "--strict-tls",
        action="store_true",
        help="Strict TLS mode: reject unencrypted plaintext TCP connections completely",
    )
    parser.add_argument(
        "--auto-accept",
        action="store_true",
        help="Automatically approve incoming file requests without interactive prompt",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Maximum concurrent active file transfers (default: 5)",
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
        enable_ble=not args.no_ble,
        display_name=args.name,
        use_tls=args.secure or args.strict_tls,
        allow_plain_tcp=not args.strict_tls,
        auto_accept=args.auto_accept,
        max_concurrent_transfers=args.max_concurrent,
    )

    try:
        receiver.start(single_transfer=args.single)
    except KeyboardInterrupt:
        logger.info("\nReceiver interrupted by user. Exiting.")
        sys.exit(0)


if __name__ == "__main__":
    main()
