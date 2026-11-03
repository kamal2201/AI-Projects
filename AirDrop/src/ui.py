"""Modern, cross-platform graphical user interface for AirDrop using Tkinter and ttk."""

from __future__ import annotations

import logging
from pathlib import Path
import queue
import socket
import sys
import threading
import time
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from src.protocol import format_bytes, format_throughput
from src.registry import DeviceState, UnifiedDevice
from src.security import SecurityManager
from src.services import (
    DiscoveryService,
    IncomingTransferRequest,
    ReceiverService,
    SecurityService,
    TransferProgress,
    TransferService,
)

logger = logging.getLogger("airdrop.ui")


class AirDropApp:
    """Main AirDrop GUI Application."""

    def __init__(
        self,
        root: tk.Tk | None = None,
        use_tls: bool = True,
        dest_dir: str | Path = "./received",
        port: int = 5001,
    ) -> None:
        self.root = root or tk.Tk()
        self.root.title("AirDrop — Secure Peer-to-Peer Transfer")
        self.root.geometry("920x680")
        self.root.minsize(780, 560)

        self.use_tls = use_tls
        self.dest_dir = Path(dest_dir).resolve()
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self.port = port

        # Thread-safe event queue for background service communications
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()

        # Initialize Application Services
        self.security_service = SecurityService()
        self.discovery_service = DiscoveryService(
            enable_ble=True,
            on_peers_changed=self._on_peers_changed,
        )
        self.receiver_service = ReceiverService(
            dest_dir=self.dest_dir,
            port=self.port,
            use_tls=self.use_tls,
            allow_plain_tcp=True,
            security_manager=self.security_service.manager,
            on_incoming_request=self._on_incoming_request,
            on_transfer_complete=self._on_receive_complete,
        )
        self.transfer_service = TransferService(
            security_manager=self.security_service.manager,
            use_tls=self.use_tls,
        )

        # State
        self.selected_files: list[Path] = []
        self.discovered_devices: list[UnifiedDevice] = []
        self.selected_device: UnifiedDevice | None = None
        self._is_transferring = False

        # Apply Visual Theme
        self._setup_styles()
        self._build_ui()

        # Start event loop consumer
        self.root.after(50, self._process_event_queue)

        # Start background services
        self.discovery_service.start()
        self.receiver_service.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _setup_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # Color palette
        bg_dark = "#1e1e2e"
        fg_text = "#cdd6f4"
        accent_blue = "#89b4fa"
        card_bg = "#313244"
        btn_green = "#a6e3a1"
        btn_red = "#f38ba8"

        self.root.configure(bg=bg_dark)

        style.configure("TFrame", background=bg_dark)
        style.configure("Card.TFrame", background=card_bg, relief="flat")
        style.configure("TLabel", background=bg_dark, foreground=fg_text, font=("Helvetica", 11))
        style.configure("Title.TLabel", font=("Helvetica", 14, "bold"), foreground=accent_blue)
        style.configure("Subtitle.TLabel", font=("Helvetica", 10), foreground="#a6adc8")
        style.configure("Header.TLabel", font=("Helvetica", 18, "bold"), foreground="#ffffff")
        style.configure("Status.TLabel", font=("Helvetica", 10, "italic"), foreground=accent_blue)

        style.configure(
            "Primary.TButton",
            font=("Helvetica", 11, "bold"),
            background=accent_blue,
            foreground="#11111b",
            padding=6,
        )
        style.configure(
            "Success.TButton",
            font=("Helvetica", 11, "bold"),
            background=btn_green,
            foreground="#11111b",
            padding=6,
        )
        style.configure(
            "Danger.TButton",
            font=("Helvetica", 11, "bold"),
            background=btn_red,
            foreground="#11111b",
            padding=6,
        )

        # Treeview styling
        style.configure(
            "Treeview",
            background="#181825",
            foreground="#cdd6f4",
            fieldbackground="#181825",
            font=("Helvetica", 11),
            rowheight=26,
        )
        style.configure(
            "Treeview.Heading",
            background="#313244",
            foreground="#ffffff",
            font=("Helvetica", 11, "bold"),
        )
        style.map("Treeview", background=[("selected", "#45475a")])

        # Progressbar
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor="#181825",
            background=accent_blue,
            thickness=16,
        )

    def _build_ui(self) -> None:
        main_container = ttk.Frame(self.root, padding=16)
        main_container.pack(fill=tk.BOTH, expand=True)

        # 1. Top Header Bar
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 14))

        title_box = ttk.Frame(header_frame)
        title_box.pack(side=tk.LEFT)

        ttk.Label(title_box, text="AirDrop P2P", style="Header.TLabel").pack(anchor=tk.W)
        node_id = self.security_service.get_local_node_id()
        fp_short = self.security_service.get_local_fingerprint()[:24] + "..."
        local_info = f"Node ID: {node_id} | Security: {fp_short} | Port: {self.port}"
        ttk.Label(title_box, text=local_info, style="Subtitle.TLabel").pack(anchor=tk.W)

        btn_box = ttk.Frame(header_frame)
        btn_box.pack(side=tk.RIGHT)
        ttk.Button(
            btn_box,
            text="Security & Trust",
            command=self._show_security_dialog,
        ).pack(side=tk.LEFT, padx=4)

        # 2. Main Content Split View (Left: Devices | Right: File Queue)
        content_paned = ttk.PanedWindow(main_container, orient=tk.HORIZONTAL)
        content_paned.pack(fill=tk.BOTH, expand=True, pady=(0, 12))

        # Left: Nearby Devices Panel
        left_frame = ttk.Frame(content_paned, padding=8)
        content_paned.add(left_frame, weight=3)

        ttk.Label(left_frame, text="Nearby Devices (mDNS + BLE)", style="Title.TLabel").pack(
            anchor=tk.W, pady=(0, 6)
        )

        columns = ("name", "state", "source", "signal", "endpoint")
        self.device_tree = ttk.Treeview(
            left_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.device_tree.heading("name", text="Device")
        self.device_tree.heading("state", text="Status")
        self.device_tree.heading("source", text="Protocol")
        self.device_tree.heading("signal", text="Signal")
        self.device_tree.heading("endpoint", text="Endpoint")

        self.device_tree.column("name", width=140)
        self.device_tree.column("state", width=95)
        self.device_tree.column("source", width=85)
        self.device_tree.column("signal", width=75)
        self.device_tree.column("endpoint", width=130)

        tree_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=self.device_tree.yview)
        self.device_tree.configure(yscrollcommand=tree_scroll.set)

        self.device_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.device_tree.bind("<<TreeviewSelect>>", self._on_device_selected)

        # Right: File Selection & Actions Panel
        right_frame = ttk.Frame(content_paned, padding=8)
        content_paned.add(right_frame, weight=2)

        ttk.Label(right_frame, text="Files to Transfer", style="Title.TLabel").pack(
            anchor=tk.W, pady=(0, 6)
        )

        self.file_listbox = tk.Listbox(
            right_frame,
            bg="#181825",
            fg="#cdd6f4",
            selectbackground="#45475a",
            font=("Helvetica", 10),
            relief="flat",
            highlightthickness=1,
            highlightcolor="#89b4fa",
        )
        self.file_listbox.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        file_btn_frame = ttk.Frame(right_frame)
        file_btn_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(file_btn_frame, text="+ Add Files...", command=self._add_files).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(file_btn_frame, text="Clear List", command=self._clear_files).pack(
            side=tk.LEFT
        )

        self.total_size_label = ttk.Label(right_frame, text="0 files selected (0 B)", style="Subtitle.TLabel")
        self.total_size_label.pack(anchor=tk.W, pady=(0, 8))

        # Send Button
        self.send_btn = ttk.Button(
            right_frame,
            text="Send Files",
            style="Primary.TButton",
            command=self._start_send_transfer,
        )
        self.send_btn.pack(fill=tk.X)

        # 3. Bottom Panel: Transfer Progress & Monitor
        bottom_frame = ttk.LabelFrame(main_container, text=" Transfer Monitor ", padding=10)
        bottom_frame.pack(fill=tk.X)

        self.status_label = ttk.Label(bottom_frame, text="Idle. Select a device and files to send.")
        self.status_label.pack(anchor=tk.W, pady=(0, 4))

        self.progress_bar = ttk.Progressbar(
            bottom_frame,
            orient=tk.HORIZONTAL,
            mode="determinate",
            style="Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        metrics_box = ttk.Frame(bottom_frame)
        metrics_box.pack(fill=tk.X)

        self.metrics_label = ttk.Label(metrics_box, text="Speed: -- MB/s | ETA: --s | Transferred: 0 B", style="Subtitle.TLabel")
        self.metrics_label.pack(side=tk.LEFT)

        self.cancel_btn = ttk.Button(
            metrics_box,
            text="Cancel Transfer",
            style="Danger.TButton",
            command=self._cancel_transfer,
            state=tk.DISABLED,
        )
        self.cancel_btn.pack(side=tk.RIGHT)

    # Event Queue Processing (Thread-safe UI updates)
    def _process_event_queue(self) -> None:
        while not self.event_queue.empty():
            try:
                event_type, data = self.event_queue.get_nowait()
                if event_type == "peers_changed":
                    self._update_device_table(data)
                elif event_type == "progress":
                    self._update_progress_ui(data)
                elif event_type == "complete":
                    self._on_transfer_success_ui(data)
                elif event_type == "error":
                    self._on_transfer_error_ui(data)
                elif event_type == "incoming_request":
                    self._prompt_incoming_request(data)
            except queue.Empty:
                break
        self.root.after(50, self._process_event_queue)

    def _on_peers_changed(self, devices: list[UnifiedDevice]) -> None:
        self.event_queue.put(("peers_changed", devices))

    def _update_device_table(self, devices: list[UnifiedDevice]) -> None:
        self.discovered_devices = devices
        selected_node = self.selected_device.node_id if self.selected_device else None

        # Clear existing items
        for item in self.device_tree.get_children():
            self.device_tree.delete(item)

        for dev in devices:
            sig = dev.signal_str
            state_str = dev.state.value
            item_id = self.device_tree.insert(
                "",
                tk.END,
                values=(
                    dev.display_name,
                    state_str,
                    dev.source_label,
                    sig,
                    dev.endpoint_str,
                ),
            )
            if selected_node and dev.node_id == selected_node:
                self.device_tree.selection_set(item_id)
                self.selected_device = dev

    def _on_device_selected(self, event=None) -> None:
        selected_items = self.device_tree.selection()
        if not selected_items:
            self.selected_device = None
            return

        item = selected_items[0]
        vals = self.device_tree.item(item, "values")
        if not vals:
            return

        dev_name = vals[0]
        # Match from discovered_devices
        for d in self.discovered_devices:
            if d.display_name == dev_name:
                self.selected_device = d
                break

        if self.selected_device:
            self.send_btn.configure(text=f"Send to {self.selected_device.display_name}")

    def _add_files(self) -> None:
        selected = filedialog.askopenfilenames(title="Select Files to Transfer")
        if not selected:
            return

        for p_str in selected:
            p = Path(p_str)
            if p.is_file() and p not in self.selected_files:
                self.selected_files.append(p)
                self.file_listbox.insert(tk.END, f"{p.name} ({format_bytes(p.stat().st_size)})")

        self._update_total_size()

    def _clear_files(self) -> None:
        self.selected_files.clear()
        self.file_listbox.delete(0, tk.END)
        self._update_total_size()

    def _update_total_size(self) -> None:
        total = sum(p.stat().st_size for p in self.selected_files)
        count = len(self.selected_files)
        self.total_size_label.configure(text=f"{count} file(s) selected ({format_bytes(total)})")

    def _start_send_transfer(self) -> None:
        if not self.selected_files:
            messagebox.showwarning("No Files", "Please select one or more files to send.")
            return

        if not self.selected_device:
            messagebox.showwarning("No Recipient", "Please select a target device from the nearby list.")
            return

        if not self.selected_device.is_reachable:
            messagebox.showerror(
                "Device Unreachable",
                f"Device '{self.selected_device.display_name}' was discovered via BLE proximity, "
                "but has not yet resolved an IP endpoint over Wi-Fi/LAN.\n"
                "Please verify both devices are on the same local network.",
            )
            return

        self._is_transferring = True
        self.send_btn.configure(state=tk.DISABLED)
        self.cancel_btn.configure(state=tk.NORMAL)
        self.progress_bar["value"] = 0
        self.status_label.configure(
            text=f"Connecting to {self.selected_device.display_name} ({self.selected_device.endpoint_str})..."
        )

        self.transfer_service.send_files_async(
            files=self.selected_files,
            device=self.selected_device,
            on_progress=lambda p: self.event_queue.put(("progress", p)),
            on_completed=lambda fn, m: self.event_queue.put(("complete", (fn, m))),
            on_error=lambda fn, err: self.event_queue.put(("error", (fn, err))),
            on_all_finished=self._on_all_finished_callback,
        )

    def _update_progress_ui(self, prog: TransferProgress) -> None:
        percent = int(prog.fraction * 100)
        self.progress_bar["value"] = percent
        self.status_label.configure(
            text=f"Sending '{prog.filename}': {percent}% ({format_bytes(prog.bytes_transferred)} / {format_bytes(prog.total_bytes)})"
        )
        self.metrics_label.configure(
            text=f"Speed: {prog.throughput_str} | ETA: {prog.eta_seconds:.1f}s"
        )

    def _on_transfer_success_ui(self, data: tuple[str, dict[str, Any]]) -> None:
        filename, metrics = data
        self.progress_bar["value"] = 100
        self.status_label.configure(
            text=f"Transfer Successful: '{filename}' ({metrics.get('throughput_str', '')})"
        )
        self.metrics_label.configure(text=f"SHA-256: {metrics.get('sha256', '')[:24]}...")

    def _on_transfer_error_ui(self, data: tuple[str, Exception]) -> None:
        filename, err = data
        self.status_label.configure(text=f"Transfer Failed for '{filename}': {err}")
        messagebox.showerror("Transfer Error", f"Transfer of '{filename}' failed:\n{err}")

    def _on_all_finished_callback(self) -> None:
        self.root.after(0, self._reset_transfer_controls)

    def _reset_transfer_controls(self) -> None:
        self._is_transferring = False
        self.send_btn.configure(state=tk.NORMAL)
        self.cancel_btn.configure(state=tk.DISABLED)

    def _cancel_transfer(self) -> None:
        self.transfer_service.cancel()
        self.status_label.configure(text="Transfer cancelled by user. Cleaning up...")
        self.cancel_btn.configure(state=tk.DISABLED)

    # Incoming Transfer Approval Modal
    def _on_incoming_request(self, req: IncomingTransferRequest) -> None:
        self.event_queue.put(("incoming_request", req))

    def _prompt_incoming_request(self, req: IncomingTransferRequest) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Incoming Transfer Request")
        dialog.geometry("450x260")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#1e1e2e")

        container = ttk.Frame(dialog, padding=16)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(container, text="Incoming File Transfer", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 8))

        info_text = (
            f"Sender: {req.sender_name} (ID: {req.sender_node_id})\n"
            f"File:   {req.filename}\n"
            f"Size:   {req.formatted_size}\n\n"
            f"Do you want to accept and download this file?"
        )
        ttk.Label(container, text=info_text, font=("Helvetica", 11)).pack(anchor=tk.W, pady=(0, 14))

        btn_box = ttk.Frame(container)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM)

        def accept():
            dialog.destroy()
            self.receiver_service.respond_to_request(req, approve=True)

        def decline():
            dialog.destroy()
            self.receiver_service.respond_to_request(req, approve=False)

        ttk.Button(btn_box, text="Accept Transfer", style="Success.TButton", command=accept).pack(side=tk.RIGHT, padx=6)
        ttk.Button(btn_box, text="Decline", style="Danger.TButton", command=decline).pack(side=tk.RIGHT)

    def _on_receive_complete(self, metrics: dict[str, Any]) -> None:
        self.status_label.configure(
            text=f"Received: '{metrics.get('filename')}' ({metrics.get('throughput_str', '')})"
        )

    # Security & Pairing Dialog
    def _show_security_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Security, Trust & Pairing")
        dialog.geometry("640x480")
        dialog.transient(self.root)
        dialog.configure(bg="#1e1e2e")

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="Security & Trust Manager", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 6))

        fp = self.security_service.get_local_fingerprint()
        node = self.security_service.get_local_node_id()

        ttk.Label(frame, text=f"Node ID:     {node}\nFingerprint: {fp}", font=("Courier", 10)).pack(anchor=tk.W, pady=(0, 10))

        ttk.Label(frame, text="Trusted Paired Peers:", style="Subtitle.TLabel").pack(anchor=tk.W, pady=(0, 4))

        tree = ttk.Treeview(frame, columns=("name", "node", "fp"), show="headings", height=6)
        tree.heading("name", text="Name")
        tree.heading("node", text="Node ID")
        tree.heading("fp", text="Fingerprint")
        tree.column("name", width=120)
        tree.column("node", width=90)
        tree.column("fp", width=350)
        tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        for p in self.security_service.list_trusted_peers():
            tree.insert("", tk.END, values=(p["display_name"], p["node_id"], p["fingerprint"]))

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X)

        def export_cert():
            dest = filedialog.asksaveasfilename(
                title="Export Public Certificate",
                initialfile="my_airdrop.crt",
                defaultextension=".crt",
            )
            if dest:
                self.security_service.export_cert_file(dest)
                messagebox.showinfo("Export Successful", f"Certificate exported to:\n{dest}")

        def pair_cert():
            src_file = filedialog.askopenfilename(
                title="Select Peer Public Certificate",
                filetypes=[("Certificate Files", "*.crt;*.pem")],
            )
            if src_file:
                # Prompt for node ID & Name
                node_id = f"peer_{int(time.time())}"
                fp, pin = self.security_service.pair_with_cert_file(node_id, "PairedPeer", src_file)
                messagebox.showinfo(
                    "Device Paired Successfully",
                    f"Paired Peer Fingerprint:\n{fp}\n\nShort Auth PIN (Verify with peer):\n{pin}",
                )
                dialog.destroy()

        ttk.Button(btn_row, text="Export Public Cert...", command=export_cert).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Pair Device (Import Cert)...", command=pair_cert).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn_row, text="Close", command=dialog.destroy).pack(side=tk.RIGHT)

    def on_close(self) -> None:
        """Clean shutdown of UI and background services."""
        try:
            self.discovery_service.stop()
            self.receiver_service.stop()
        except Exception:
            pass
        self.root.destroy()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = tk.Tk()
    app = AirDropApp(root=root)
    root.mainloop()


if __name__ == "__main__":
    main()
