"""Tests for path traversal prevention, malformed headers, truncated payloads, and error scenarios."""

import json
from pathlib import Path
import shutil
import socket
import struct
import tempfile
import threading
import time
import unittest

from src.protocol import (
    DEFAULT_MAX_HEADER_SIZE,
    HEADER_PREFIX_FORMAT,
    HEADER_PREFIX_SIZE,
    read_response_from_socket,
)
from src.receiver import Receiver


class TestSecurityAndErrorHandling(unittest.TestCase):
    def setUp(self):
        self.dest_dir = tempfile.mkdtemp(prefix="airdrop_security_dest_")
        self.receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            timeout=5.0,
            max_file_size=50 * 1024,  # 50 KiB limit for testing
        )
        self.receiver_thread = threading.Thread(
            target=self.receiver.start,
            kwargs={"single_transfer": False},
            daemon=True,
        )
        self.receiver_thread.start()

        start = time.time()
        while self.receiver.active_port is None and (time.time() - start) < 5.0:
            time.sleep(0.01)

        self.port = self.receiver.active_port

    def tearDown(self):
        self.receiver.stop()
        self.receiver_thread.join(timeout=2.0)
        shutil.rmtree(self.dest_dir, ignore_errors=True)

    def test_path_traversal_rejection(self):
        """Ensure path traversal attacks like ../../etc/passwd are blocked."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        try:
            payload = json.dumps({"filename": "../../evil_escape.txt", "filesize": 10}).encode("utf-8")
            s.sendall(struct.pack(HEADER_PREFIX_FORMAT, len(payload)) + payload)
            response = read_response_from_socket(s)
            self.assertEqual(response.get("status"), "error")
            self.assertIn("Security rejection", response.get("message", ""))
        finally:
            s.close()

        # Confirm file was not written
        self.assertFalse((Path(self.dest_dir).parent / "evil_escape.txt").exists())
        self.assertEqual(len(list(Path(self.dest_dir).iterdir())), 0)

    def test_unreasonable_header_size(self):
        """Header length prefix exceeding limit must be rejected immediately."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        try:
            # Send huge header length (10 MB)
            huge_len = 10 * 1024 * 1024
            s.sendall(struct.pack(HEADER_PREFIX_FORMAT, huge_len))
            response = read_response_from_socket(s)
            self.assertEqual(response.get("status"), "error")
            self.assertIn("exceeds maximum allowable", response.get("message", ""))
        finally:
            s.close()

    def test_oversized_transfer_rejection(self):
        """Declared file size exceeding max_file_size must be rejected."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        try:
            # Max file size is configured to 50 KiB; send 100 KiB
            payload = json.dumps({"filename": "big.bin", "filesize": 100 * 1024}).encode("utf-8")
            s.sendall(struct.pack(HEADER_PREFIX_FORMAT, len(payload)) + payload)
            response = read_response_from_socket(s)
            self.assertEqual(response.get("status"), "error")
            self.assertIn("exceeds maximum allowed size", response.get("message", ""))
        finally:
            s.close()

    def test_truncated_payload_cleanup(self):
        """Sender declares 5000 bytes but sends only 1000 then disconnects.

        Temporary file must be removed and no corrupted destination file left.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        try:
            payload = json.dumps({"filename": "truncated.dat", "filesize": 5000}).encode("utf-8")
            s.sendall(struct.pack(HEADER_PREFIX_FORMAT, len(payload)) + payload)
            # Send only 1000 bytes
            s.sendall(b"A" * 1000)
            # Abruptly close
            s.close()
        except Exception:
            pass

        # Give receiver a moment to process disconnect and cleanup
        time.sleep(0.1)

        # Verify no completed file exists
        dest_file = Path(self.dest_dir) / "truncated.dat"
        self.assertFalse(dest_file.exists())

        # Verify no leftover .part files exist
        part_files = list(Path(self.dest_dir).glob("*.part"))
        self.assertEqual(len(part_files), 0)

    def test_disconnect_during_header_prefix(self):
        """Sender disconnects after sending only 2 bytes of the 4-byte prefix."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        s.sendall(b"\x00\x00")
        s.close()

        # Give receiver a moment to handle disconnect cleanly
        time.sleep(0.1)
        # Server should still be alive
        self.assertTrue(self.receiver._running)

    def test_checksum_mismatch_detected(self):
        """If expected SHA-256 is in header and doesn't match payload, reject and remove."""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", self.port))
        try:
            header_dict = {
                "filename": "bad_hash.txt",
                "filesize": 5,
                "sha256": "0" * 64,  # Invalid hash
            }
            payload = json.dumps(header_dict).encode("utf-8")
            s.sendall(struct.pack(HEADER_PREFIX_FORMAT, len(payload)) + payload)
            s.sendall(b"12345")
            response = read_response_from_socket(s)
            self.assertEqual(response.get("status"), "error")
            self.assertIn("Checksum mismatch", response.get("message", ""))
        finally:
            s.close()

        dest_file = Path(self.dest_dir) / "bad_hash.txt"
        self.assertFalse(dest_file.exists())
        self.assertEqual(len(list(Path(self.dest_dir).glob("*.part"))), 0)


if __name__ == "__main__":
    unittest.main()
