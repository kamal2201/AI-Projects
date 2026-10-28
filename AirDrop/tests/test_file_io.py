"""Unit tests for file operations, path traversal safety, and atomic writing."""

import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from src.file_io import (
    AtomicFileWriter,
    check_disk_space,
    compute_file_sha256,
    resolve_destination_path,
    sanitize_filename,
    stream_file_chunks,
)
from src.protocol import (
    DiskSpaceError,
    PathTraversalError,
)


class TestFilenameSanitization(unittest.TestCase):
    def test_valid_filenames(self):
        valid = [
            "report.pdf",
            "Archive.tar.gz",
            "My File Name (1).txt",
            "notes_2026-10-28.md",
            "image.PNG",
            "unicode_файл_日本語.dat",
        ]
        for name in valid:
            self.assertEqual(sanitize_filename(name), name.strip())

    def test_path_traversal_rejections(self):
        traversals = [
            "../../etc/passwd",
            "../secret.txt",
            "/etc/shadow",
            "\\Windows\\System32\\calc.exe",
            "foo/bar.txt",
            "sub\\dir\\file.txt",
            "..",
            ".",
            "   ",
            "",
            "file\x00name.txt",
        ]
        for bad in traversals:
            with self.subTest(bad=bad):
                with self.assertRaises(PathTraversalError):
                    sanitize_filename(bad)


class TestDestinationPathResolution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_test_dest_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_resolve_new_file(self):
        resolved = resolve_destination_path(self.temp_dir, "document.pdf")
        self.assertEqual(resolved.name, "document.pdf")
        self.assertEqual(resolved.parent, Path(self.temp_dir).resolve())

    def test_collision_avoidance(self):
        p1 = Path(self.temp_dir) / "data.csv"
        p1.write_text("first")

        r2 = resolve_destination_path(self.temp_dir, "data.csv", allow_overwrite=False)
        self.assertEqual(r2.name, "data (1).csv")
        r2.write_text("second")

        r3 = resolve_destination_path(self.temp_dir, "data.csv", allow_overwrite=False)
        self.assertEqual(r3.name, "data (2).csv")

    def test_allow_overwrite(self):
        p1 = Path(self.temp_dir) / "data.csv"
        p1.write_text("first")

        resolved = resolve_destination_path(self.temp_dir, "data.csv", allow_overwrite=True)
        self.assertEqual(resolved, p1.resolve())


class TestDiskSpaceCheck(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_test_disk_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sufficient_space(self):
        # 1024 bytes should always succeed on local temp drive
        check_disk_space(self.temp_dir, 1024)

    def test_insufficient_space(self):
        # Mock disk usage free to 100 bytes
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = shutil._ntuple_diskusage(10_000, 9_900, 100)
            with self.assertRaises(DiskSpaceError):
                check_disk_space(self.temp_dir, 10_000)


class TestFileStreamingAndHashing(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_test_stream_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_stream_chunks_and_sha256(self):
        test_file = Path(self.temp_dir) / "test.bin"
        content = os.urandom(256 * 1024)  # 256 KiB
        test_file.write_bytes(content)

        expected_hash = hashlib.sha256(content).hexdigest()
        computed_hash = compute_file_sha256(test_file, chunk_size=16 * 1024)
        self.assertEqual(computed_hash, expected_hash)

        # Verify streamed bytes
        streamed = b"".join(stream_file_chunks(test_file, chunk_size=32 * 1024))
        self.assertEqual(streamed, content)


class TestAtomicFileWriter(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_test_atomic_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_successful_commit(self):
        target = Path(self.temp_dir) / "final.txt"
        content = b"This is a reliable atomic write test."
        expected_hash = hashlib.sha256(content).hexdigest()

        writer = AtomicFileWriter(target)
        with writer:
            writer.write(content)
            final_path, sha = writer.commit()

        self.assertTrue(target.exists())
        self.assertEqual(final_path, target.resolve())
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(sha, expected_hash)

        # Verify no .part temporary files left in dest_dir
        part_files = list(Path(self.temp_dir).glob("*.part"))
        self.assertEqual(len(part_files), 0)

    def test_aborted_write_cleans_temp_file(self):
        target = Path(self.temp_dir) / "aborted.txt"

        writer = AtomicFileWriter(target)
        temp_path_captured = None
        try:
            with writer:
                writer.write(b"partial corrupted data")
                temp_path_captured = writer.temp_path
                raise ValueError("Simulated network drop / failure")
        except ValueError:
            pass

        self.assertFalse(target.exists())
        if temp_path_captured:
            self.assertFalse(temp_path_captured.exists())
        part_files = list(Path(self.temp_dir).glob("*.part"))
        self.assertEqual(len(part_files), 0)


if __name__ == "__main__":
    unittest.main()
