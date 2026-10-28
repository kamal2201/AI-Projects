"""File operations, streaming, atomic writing, and path safety validation for AirDrop."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import Generator

from src.protocol import (
    DEFAULT_CHUNK_SIZE,
    DiskSpaceError,
    PathTraversalError,
)

logger = logging.getLogger(__name__)

# Minimum free disk headroom required above the file size (10 MiB)
DEFAULT_DISK_SAFETY_MARGIN = 10 * 1024 * 1024


def sanitize_filename(filename: str) -> str:
    """Validate and sanitize a received filename.

    Rejects path traversal characters, directory separators, null bytes,
    and reserved/empty names.
    """
    if not filename or not isinstance(filename, str):
        raise PathTraversalError("Filename cannot be empty.")

    if "\x00" in filename:
        raise PathTraversalError("Filename contains invalid null byte.")

    # Reject any directory path separators (both POSIX / and Windows \)
    if "/" in filename or "\\" in filename:
        raise PathTraversalError(f"Filename contains directory separators: {filename!r}")

    # Strip whitespace
    stripped = filename.strip()
    if not stripped:
        raise PathTraversalError("Filename contains only whitespace.")

    # Disallow current and parent directory relative names
    if stripped in {".", ".."}:
        raise PathTraversalError(f"Filename cannot be '.' or '..': {filename!r}")

    # Strip any potential leading dashes or dangerous control chars
    clean_name = os.path.basename(stripped)
    if not clean_name or clean_name in {".", ".."}:
        raise PathTraversalError(f"Invalid resolved filename: {filename!r}")

    return clean_name


def resolve_destination_path(
    dest_dir: str | Path,
    filename: str,
    allow_overwrite: bool = False,
) -> Path:
    """Validate destination path within directory and handle collision resolution safely."""
    dest_path = Path(dest_dir).resolve()
    dest_path.mkdir(parents=True, exist_ok=True)

    clean_name = sanitize_filename(filename)
    target_path = (dest_path / clean_name).resolve()

    # Strict check: target must be directly within dest_path
    try:
        target_path.relative_to(dest_path)
    except ValueError as err:
        raise PathTraversalError(f"Target path escapes destination directory: {target_path}") from err

    if target_path.parent != dest_path:
        raise PathTraversalError(f"Nested destination path not permitted: {target_path}")

    if not allow_overwrite and target_path.exists():
        target_path = get_non_conflicting_path(dest_path, clean_name)

    return target_path


def get_non_conflicting_path(dest_dir: Path, filename: str) -> Path:
    """Generate a unique filename by appending (1), (2), etc. if the file already exists."""
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 1
    candidate = dest_dir / filename
    while candidate.exists():
        candidate = dest_dir / f"{stem} ({counter}){suffix}"
        counter += 1
    return candidate


def check_disk_space(
    dest_dir: str | Path,
    required_bytes: int,
    safety_margin: int = DEFAULT_DISK_SAFETY_MARGIN,
) -> None:
    """Verify that dest_dir has enough free disk space to store required_bytes."""
    dest_path = Path(dest_dir).resolve()
    dest_path.mkdir(parents=True, exist_ok=True)

    try:
        usage = shutil.disk_usage(dest_path)
    except OSError as err:
        raise DiskSpaceError(f"Failed to query disk space on {dest_path}: {err}") from err

    needed = required_bytes + safety_margin
    if usage.free < needed:
        raise DiskSpaceError(
            f"Insufficient disk space in {dest_path}: "
            f"needed {needed} bytes (including {safety_margin} margin), but only {usage.free} bytes free."
        )


def stream_file_chunks(
    file_path: str | Path,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Generator[bytes, None, None]:
    """Read a file in bounded chunks. Never loads entire file into memory."""
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"File not found or is not a regular file: {path}")

    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            yield chunk


def compute_file_sha256(file_path: str | Path, chunk_size: int = DEFAULT_CHUNK_SIZE) -> str:
    """Compute SHA-256 hash of a file by streaming in chunks."""
    hasher = hashlib.sha256()
    for chunk in stream_file_chunks(file_path, chunk_size=chunk_size):
        hasher.update(chunk)
    return hasher.hexdigest()


class AtomicFileWriter:
    """Writes received data to a temporary file and atomically replaces destination upon success.

    If an error occurs or transfer is aborted, the temporary file is deleted.
    """

    def __init__(self, target_path: Path) -> None:
        self.target_path = Path(target_path).resolve()
        self.dest_dir = self.target_path.parent
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        self.temp_file: tempfile._TemporaryFileWrapper | None = None
        self.temp_path: Path | None = None
        self.hasher = hashlib.sha256()
        self.bytes_written = 0
        self._completed = False

    def __enter__(self) -> AtomicFileWriter:
        # Create temp file in the same directory to ensure atomic os.replace across filesystems
        self.temp_file = tempfile.NamedTemporaryFile(
            dir=self.dest_dir,
            prefix=f".{self.target_path.name}.",
            suffix=".part",
            delete=False,
        )
        self.temp_path = Path(self.temp_file.name)
        return self

    def write(self, data: bytes) -> int:
        """Write chunk of bytes to temporary file and update running hash."""
        if self._completed or not self.temp_file:
            raise RuntimeError("Cannot write to closed or completed AtomicFileWriter.")
        self.temp_file.write(data)
        self.hasher.update(data)
        count = len(data)
        self.bytes_written += count
        return count

    def commit(self) -> tuple[Path, str]:
        """Flush, fsync, close temporary file, and atomically rename to target_path."""
        if self._completed:
            raise RuntimeError("Already committed.")
        if not self.temp_file or not self.temp_path:
            raise RuntimeError("Temp file not open.")

        try:
            self.temp_file.flush()
            os.fsync(self.temp_file.fileno())
            self.temp_file.close()

            # Atomic replace
            os.replace(self.temp_path, self.target_path)
            self._completed = True
            sha256_digest = self.hasher.hexdigest()
            logger.info("Successfully committed file to %s (sha256: %s)", self.target_path, sha256_digest)
            return self.target_path, sha256_digest
        except Exception:
            self.cleanup()
            raise

    def cleanup(self) -> None:
        """Close and remove temporary file if not committed."""
        if self.temp_file and not self.temp_file.closed:
            try:
                self.temp_file.close()
            except Exception:
                pass
        if self.temp_path and self.temp_path.exists():
            try:
                self.temp_path.unlink()
                logger.debug("Cleaned up temporary file %s", self.temp_path)
            except Exception as err:
                logger.warning("Failed to remove temporary file %s: %s", self.temp_path, err)

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None or not self._completed:
            self.cleanup()
