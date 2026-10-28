"""Integration tests for end-to-end TCP file transfers."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest

from src.file_io import compute_file_sha256
from src.receiver import Receiver
from src.sender import Sender


class TestEndToEndTransfer(unittest.TestCase):
    def setUp(self):
        self.src_dir = tempfile.mkdtemp(prefix="airdrop_src_")
        self.dest_dir = tempfile.mkdtemp(prefix="airdrop_dest_")

        # Start receiver on ephemeral port (port 0)
        self.receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_dir,
            timeout=10.0,
        )

        self.receiver_thread = threading.Thread(
            target=self.receiver.start,
            kwargs={"single_transfer": False},
            daemon=True,
        )
        self.receiver_thread.start()

        # Wait until active_port is assigned
        timeout = 5.0
        start = time.time()
        while self.receiver.active_port is None and (time.time() - start) < timeout:
            time.sleep(0.01)

        self.assertIsNotNone(self.receiver.active_port, "Receiver failed to bind to a port.")
        self.port = self.receiver.active_port
        self.sender = Sender(host="127.0.0.1", port=self.port, timeout=10.0)

    def tearDown(self):
        self.receiver.stop()
        self.receiver_thread.join(timeout=2.0)
        shutil.rmtree(self.src_dir, ignore_errors=True)
        shutil.rmtree(self.dest_dir, ignore_errors=True)

    def _verify_transfer(self, src_file: Path, dest_filename: str):
        result = self.sender.send_file(src_file)
        self.assertIn("sha256", result)
        self.assertIn("throughput_str", result)

        dest_file = Path(self.dest_dir) / dest_filename
        self.assertTrue(dest_file.exists(), f"Destination file does not exist: {dest_file}")

        # Byte-by-byte SHA-256 comparison
        src_sha = compute_file_sha256(src_file)
        dest_sha = compute_file_sha256(dest_file)
        self.assertEqual(src_sha, dest_sha)
        self.assertEqual(src_file.stat().st_size, dest_file.stat().st_size)

        # Check no temporary files left
        parts = list(Path(self.dest_dir).glob("*.part"))
        self.assertEqual(len(parts), 0, f"Found lingering temporary part files: {parts}")

    def test_transfer_empty_file(self):
        """Test sending an empty 0-byte file."""
        src = Path(self.src_dir) / "empty.txt"
        src.touch()
        self._verify_transfer(src, "empty.txt")

    def test_transfer_small_file(self):
        """Test sending a small text file."""
        src = Path(self.src_dir) / "small.txt"
        src.write_text("Hello, this is a small file transfer testing AirDrop TCP sockets!\n")
        self._verify_transfer(src, "small.txt")

    def test_transfer_binary_file(self):
        """Test sending arbitrary binary content with null bytes and control chars."""
        src = Path(self.src_dir) / "binary.dat"
        data = bytes(range(256)) * 64  # 16 KiB with all byte values
        src.write_bytes(data)
        self._verify_transfer(src, "binary.dat")

    def test_transfer_large_file(self):
        """Test sending a multi-megabyte file across multiple chunks (5 MiB)."""
        src = Path(self.src_dir) / "large.iso"
        # 5 MiB file with deterministic pseudorandom data
        size = 5 * 1024 * 1024
        chunk_pattern = os.urandom(64 * 1024)
        with open(src, "wb") as f:
            for _ in range(size // len(chunk_pattern)):
                f.write(chunk_pattern)
        self._verify_transfer(src, "large.iso")

    def test_transfer_with_precomputed_hash(self):
        """Test transfer with precomputed SHA-256 in header."""
        src = Path(self.src_dir) / "hashed.bin"
        src.write_bytes(os.urandom(128 * 1024))
        result = self.sender.send_file(src, precompute_sha256=True)
        self.assertEqual(result["filesize"], 128 * 1024)

        dest = Path(self.dest_dir) / "hashed.bin"
        self.assertTrue(dest.exists())
        self.assertEqual(compute_file_sha256(src), compute_file_sha256(dest))

    def test_multiple_sequential_transfers(self):
        """Test multiple consecutive transfers on the same receiver server."""
        for i in range(3):
            src = Path(self.src_dir) / f"file_{i}.txt"
            src.write_text(f"Sequential transfer number {i}\n")
            self._verify_transfer(src, f"file_{i}.txt")


if __name__ == "__main__":
    unittest.main()
