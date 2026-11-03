"""Application service controllers separating UI components from networking and business logic."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import queue
import threading
import time
from typing import Any, Callable

from src.discovery import PeerBrowser
from src.protocol import format_bytes, format_throughput
from src.receiver import Receiver
from src.registry import DeviceRegistry, UnifiedDevice
from src.security import SecurityManager, compute_cert_fingerprint, compute_sas_pin
from src.sender import Sender

logger = logging.getLogger("airdrop.services")


@dataclass
class TransferProgress:
    """Current progress metrics for an ongoing transfer."""

    filename: str
    bytes_transferred: int
    total_bytes: int
    fraction: float
    throughput_bps: float
    throughput_str: str
    eta_seconds: float
    is_complete: bool = False
    is_cancelled: bool = False
    error_message: str | None = None


@dataclass
class IncomingTransferRequest:
    """Represents an incoming transfer awaiting recipient consent."""

    request_id: str
    filename: str
    filesize: int
    sender_name: str
    sender_node_id: str
    response_event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False

    @property
    def formatted_size(self) -> str:
        return format_bytes(self.filesize)


class DiscoveryService:
    """Application service for discovering nearby AirDrop peers over LAN (mDNS) and BLE."""

    def __init__(
        self,
        enable_ble: bool = True,
        on_peers_changed: Callable[[list[UnifiedDevice]], None] | None = None,
    ) -> None:
        self.enable_ble = enable_ble
        self.on_peers_changed = on_peers_changed
        self.registry = DeviceRegistry(on_change=self._notify_change)
        self.browser: PeerBrowser | None = None

    def start(self) -> None:
        """Start mDNS and BLE background scanning."""
        if self.browser:
            return
        self.browser = PeerBrowser(
            registry=self.registry,
            enable_ble=self.enable_ble,
            on_change=self._notify_change,
        )
        self.browser.start()
        logger.info("DiscoveryService started.")

    def stop(self) -> None:
        """Stop scanning and release network/Bluetooth sockets."""
        if self.browser:
            try:
                self.browser.stop()
            except Exception:
                pass
            self.browser = None
        logger.info("DiscoveryService stopped.")

    def _notify_change(self) -> None:
        if self.on_peers_changed:
            try:
                devices = self.get_devices()
                self.on_peers_changed(devices)
            except Exception as err:
                logger.debug("Error in on_peers_changed callback: %s", err)

    def get_devices(self, include_unavailable: bool = False) -> list[UnifiedDevice]:
        return self.registry.get_devices(include_unavailable=include_unavailable)

    def find_device(self, query: str) -> UnifiedDevice | None:
        return self.registry.find_device(query)


class ReceiverService:
    """Application service managing incoming transfer receiver server."""

    def __init__(
        self,
        dest_dir: str | Path = "./received",
        port: int = 5001,
        use_tls: bool = False,
        allow_plain_tcp: bool = True,
        security_manager: SecurityManager | None = None,
        on_incoming_request: Callable[[IncomingTransferRequest], None] | None = None,
        on_transfer_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.dest_dir = Path(dest_dir).resolve()
        self.port = port
        self.use_tls = use_tls
        self.allow_plain_tcp = allow_plain_tcp
        self.security_manager = security_manager
        self.on_incoming_request = on_incoming_request
        self.on_transfer_complete = on_transfer_complete

        self.receiver: Receiver | None = None
        self._thread: threading.Thread | None = None
        self._pending_requests: dict[str, IncomingTransferRequest] = {}

    def start(self) -> None:
        """Start listening on background thread."""
        if self.receiver:
            return

        self.receiver = Receiver(
            port=self.port,
            dest_dir=self.dest_dir,
            use_tls=self.use_tls,
            allow_plain_tcp=self.allow_plain_tcp,
            security_manager=self.security_manager,
            require_approval=True,
            approval_callback=self._approval_callback,
            advertise=True,
            enable_ble=True,
        )

        def runner():
            try:
                self.receiver.start(single_transfer=False)
            except Exception as err:
                logger.debug("Receiver thread stopped: %s", err)

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        logger.info("ReceiverService active on port %d.", self.port)

    def stop(self) -> None:
        """Stop listening and shut down receiver."""
        if self.receiver:
            try:
                self.receiver.stop()
            except Exception:
                pass
            self.receiver = None
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        logger.info("ReceiverService stopped.")

    def _approval_callback(
        self, filename: str, filesize: int, sender_name: str, node_id: str
    ) -> bool:
        """Invoked by Receiver when an incoming file header is received."""
        req_id = f"{node_id}-{int(time.time() * 1000)}"
        req = IncomingTransferRequest(
            request_id=req_id,
            filename=filename,
            filesize=filesize,
            sender_name=sender_name,
            sender_node_id=node_id,
        )
        self._pending_requests[req_id] = req

        if self.on_incoming_request:
            try:
                self.on_incoming_request(req)
            except Exception as err:
                logger.debug("Error dispatching incoming request: %s", err)

        # Wait for user decision with 30s timeout
        req.response_event.wait(timeout=30.0)
        approved = req.approved
        self._pending_requests.pop(req_id, None)
        return approved

    def respond_to_request(self, req: IncomingTransferRequest, approve: bool) -> None:
        """Called by UI to approve or decline transfer."""
        req.approved = approve
        req.response_event.set()


class TransferService:
    """Application service executing outgoing file transfers with progress and cancellation."""

    def __init__(
        self,
        security_manager: SecurityManager | None = None,
        use_tls: bool = False,
    ) -> None:
        self.security_manager = security_manager
        self.use_tls = use_tls
        self.cancellation_token = threading.Event()
        self._active_sender: Sender | None = None
        self._is_transferring = False
        self._lock = threading.Lock()

    def send_files_async(
        self,
        files: list[Path | str],
        device: UnifiedDevice,
        on_progress: Callable[[TransferProgress], None] | None = None,
        on_completed: Callable[[str, dict[str, Any]], None] | None = None,
        on_error: Callable[[str, Exception], None] | None = None,
        on_all_finished: Callable[[], None] | None = None,
    ) -> None:
        """Transfer one or more files in a background worker thread."""
        with self._lock:
            if self._is_transferring:
                raise RuntimeError("Another transfer is currently active.")
            self._is_transferring = True
            self.cancellation_token.clear()

        def worker():
            try:
                endpoint_ip = device.ip_address or "127.0.0.1"
                endpoint_port = device.port or 5001

                for file_item in files:
                    file_path = Path(file_item)
                    filename = file_path.name
                    filesize = file_path.stat().st_size

                    if self.cancellation_token.is_set():
                        break

                    sender = Sender(
                        host=endpoint_ip,
                        port=endpoint_port,
                        use_tls=self.use_tls,
                        security_manager=self.security_manager,
                        prefer_direct=True,
                    )
                    self._active_sender = sender

                    start_time = time.perf_counter()

                    def progress_handler(bytes_sent: int, total_bytes: int):
                        elapsed = time.perf_counter() - start_time
                        throughput = bytes_sent / elapsed if elapsed > 0 else 0.0
                        remaining_bytes = total_bytes - bytes_sent
                        eta = (remaining_bytes / throughput) if throughput > 0 else 0.0
                        fraction = bytes_sent / total_bytes if total_bytes > 0 else 1.0

                        prog = TransferProgress(
                            filename=filename,
                            bytes_transferred=bytes_sent,
                            total_bytes=total_bytes,
                            fraction=fraction,
                            throughput_bps=throughput,
                            throughput_str=format_throughput(bytes_sent, elapsed),
                            eta_seconds=eta,
                        )
                        if on_progress:
                            on_progress(prog)

                    try:
                        metrics = sender.send_file(
                            file_path=file_path,
                            precompute_sha256=True,
                            progress_callback=progress_handler,
                            cancellation_token=self.cancellation_token,
                        )
                        if on_completed:
                            on_completed(filename, metrics)
                    except Exception as err:
                        if on_error:
                            on_error(filename, err)
                        break

            finally:
                with self._lock:
                    self._is_transferring = False
                    self._active_sender = None
                if on_all_finished:
                    on_all_finished()

        t = threading.Thread(target=worker, daemon=True)
        t.start()

    def cancel(self) -> None:
        """Cancel ongoing transfer immediately."""
        self.cancellation_token.set()
        logger.info("Cancellation requested by user.")


class SecurityService:
    """Application service for cryptographic keys, peer pairing, and trust inspection."""

    def __init__(self, security_manager: SecurityManager | None = None) -> None:
        self.manager = security_manager or SecurityManager()

    def get_local_fingerprint(self) -> str:
        return self.manager.get_local_fingerprint()

    def get_local_node_id(self) -> str:
        return self.manager.node_id

    def export_cert_file(self, dest_path: Path | str) -> Path:
        p = Path(dest_path)
        p.write_text(self.manager.get_local_cert_pem(), encoding="utf-8")
        return p

    def pair_with_cert_file(self, node_id: str, display_name: str, cert_path: Path | str) -> tuple[str, str]:
        cert_pem = Path(cert_path).read_text(encoding="utf-8")
        peer = self.manager.peer_store.add_peer(node_id, display_name, cert_pem)
        pin = compute_sas_pin(self.manager.get_local_cert_pem(), cert_pem)
        return peer.fingerprint, pin

    def list_trusted_peers(self) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self.manager.peer_store.list_peers()]

    def revoke_peer(self, node_id: str) -> bool:
        return self.manager.peer_store.remove_peer(node_id)

    def reset_all(self) -> None:
        self.manager.reset_all()
