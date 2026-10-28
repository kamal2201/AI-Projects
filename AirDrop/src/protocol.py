"""Protocol definitions, framing, and serialization for AirDrop TCP file transfer."""

from __future__ import annotations

import json
import logging
import socket
import struct
from typing import Any

logger = logging.getLogger(__name__)

# Protocol Constants
HEADER_PREFIX_FORMAT = ">I"  # 32-bit unsigned integer (big-endian)
HEADER_PREFIX_SIZE = struct.calcsize(HEADER_PREFIX_FORMAT)  # 4 bytes

# Constraints
DEFAULT_MAX_HEADER_SIZE = 64 * 1024  # 64 KiB
DEFAULT_CHUNK_SIZE = 64 * 1024       # 64 KiB chunk size for streaming
DEFAULT_SOCKET_TIMEOUT = 30.0        # 30 seconds
DEFAULT_MAX_FILE_SIZE = 100 * 1024 * 1024 * 1024  # 100 GiB


# Custom Exceptions
class AirDropError(Exception):
    """Base exception for all AirDrop errors."""
    pass


class ProtocolError(AirDropError):
    """Raised when protocol framing or header parsing fails."""
    pass


class HeaderTooLargeError(ProtocolError):
    """Raised when the received header size exceeds the allowed threshold."""
    pass


class ConnectionClosedError(AirDropError):
    """Raised when a socket connection closes unexpectedly."""
    def __init__(self, message: str, bytes_read: int = 0, expected_bytes: int = 0) -> None:
        super().__init__(message)
        self.bytes_read = bytes_read
        self.expected_bytes = expected_bytes


class TruncatedTransferError(AirDropError):
    """Raised when payload stream terminates prematurely."""
    def __init__(self, message: str, received_bytes: int = 0, expected_bytes: int = 0) -> None:
        super().__init__(message)
        self.received_bytes = received_bytes
        self.expected_bytes = expected_bytes


class OversizedFileError(AirDropError):
    """Raised when a transfer exceeds maximum allowable file size."""
    pass


class PathTraversalError(AirDropError):
    """Raised when a filename contains path traversal or invalid characters."""
    pass


class DiskSpaceError(AirDropError):
    """Raised when there is insufficient disk space on the receiver."""
    pass


def encode_header(
    filename: str,
    filesize: int,
    extra: dict[str, Any] | None = None,
    max_header_size: int = DEFAULT_MAX_HEADER_SIZE,
) -> bytes:
    """Encode a metadata header into a prefixed binary frame.

    Format: [4-byte big-endian length][UTF-8 encoded JSON]
    """
    if not isinstance(filename, str) or not filename.strip():
        raise ProtocolError("Filename must be a non-empty string.")
    if "\x00" in filename:
        raise ProtocolError("Filename cannot contain null bytes.")
    if type(filesize) is not int or filesize < 0:
        raise ProtocolError(f"Filesize must be a non-negative integer, got: {filesize!r}")

    payload: dict[str, Any] = {
        "filename": filename,
        "filesize": filesize,
    }
    if extra:
        payload.update(extra)

    try:
        json_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as err:
        raise ProtocolError(f"Failed to serialize header to JSON: {err}") from err

    header_length = len(json_bytes)
    if header_length > max_header_size:
        raise HeaderTooLargeError(
            f"Header size ({header_length} bytes) exceeds limit of {max_header_size} bytes."
        )

    prefix = struct.pack(HEADER_PREFIX_FORMAT, header_length)
    return prefix + json_bytes


def decode_header(
    header_bytes: bytes,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
) -> dict[str, Any]:
    """Decode and validate a JSON header payload from raw bytes."""
    try:
        text = header_bytes.decode("utf-8")
        data = json.loads(text)
    except UnicodeDecodeError as err:
        raise ProtocolError(f"Header is not valid UTF-8: {err}") from err
    except json.JSONDecodeError as err:
        raise ProtocolError(f"Header is not valid JSON: {err}") from err

    if not isinstance(data, dict):
        raise ProtocolError(f"Header must be a JSON object, got: {type(data).__name__}")

    if "filename" not in data:
        raise ProtocolError("Header missing required field 'filename'.")
    filename = data["filename"]
    if not isinstance(filename, str) or not filename.strip():
        raise ProtocolError("Field 'filename' must be a non-empty string.")
    if "\x00" in filename:
        raise ProtocolError("Field 'filename' cannot contain null bytes.")

    if "filesize" not in data:
        raise ProtocolError("Header missing required field 'filesize'.")
    filesize = data["filesize"]
    if type(filesize) is not int or filesize < 0:
        raise ProtocolError(f"Field 'filesize' must be a non-negative integer, got: {filesize!r}")

    if filesize > max_file_size:
        raise OversizedFileError(
            f"Declared file size ({filesize} bytes) exceeds maximum allowed size ({max_file_size} bytes)."
        )

    return data


def recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
    """Read exactly num_bytes from a socket.

    Raises ConnectionClosedError if the socket is closed before reading num_bytes.
    """
    if num_bytes < 0:
        raise ValueError(f"num_bytes must be non-negative, got {num_bytes}")
    if num_bytes == 0:
        return b""

    chunks: list[bytes] = []
    received = 0
    while received < num_bytes:
        chunk = sock.recv(min(num_bytes - received, DEFAULT_CHUNK_SIZE))
        if not chunk:
            raise ConnectionClosedError(
                f"Connection closed prematurely after {received}/{num_bytes} bytes.",
                bytes_read=received,
                expected_bytes=num_bytes,
            )
        chunks.append(chunk)
        received += len(chunk)

    return b"".join(chunks)


def send_exact(sock: socket.socket, data: bytes) -> None:
    """Send all bytes to a socket."""
    sock.sendall(data)


def read_header_from_socket(
    sock: socket.socket,
    max_header_size: int = DEFAULT_MAX_HEADER_SIZE,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
) -> tuple[dict[str, Any], int]:
    """Read fixed-length prefix and JSON header from socket.

    Returns (header_dict, total_header_wire_bytes).
    """
    prefix_bytes = recv_exact(sock, HEADER_PREFIX_SIZE)
    (header_len,) = struct.unpack(HEADER_PREFIX_FORMAT, prefix_bytes)

    if header_len == 0:
        raise ProtocolError("Received empty header length (0 bytes).")
    if header_len > max_header_size:
        raise HeaderTooLargeError(
            f"Incoming header length ({header_len} bytes) exceeds maximum allowable ({max_header_size} bytes)."
        )

    header_bytes = recv_exact(sock, header_len)
    header_data = decode_header(header_bytes, max_file_size=max_file_size)
    total_wire_bytes = HEADER_PREFIX_SIZE + header_len
    return header_data, total_wire_bytes


def encode_response(status: str, message: str = "", extra: dict[str, Any] | None = None) -> bytes:
    """Encode an acknowledgment/status response frame."""
    payload: dict[str, Any] = {
        "status": status,
        "message": message,
    }
    if extra:
        payload.update(extra)
    json_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    prefix = struct.pack(HEADER_PREFIX_FORMAT, len(json_bytes))
    return prefix + json_bytes


def read_response_from_socket(
    sock: socket.socket,
    max_response_size: int = DEFAULT_MAX_HEADER_SIZE,
) -> dict[str, Any]:
    """Read a status response frame from socket."""
    prefix_bytes = recv_exact(sock, HEADER_PREFIX_SIZE)
    (resp_len,) = struct.unpack(HEADER_PREFIX_FORMAT, prefix_bytes)
    if resp_len > max_response_size:
        raise HeaderTooLargeError(f"Response size {resp_len} exceeds limit {max_response_size}")
    resp_bytes = recv_exact(sock, resp_len)
    try:
        data = json.loads(resp_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            raise ProtocolError(f"Expected dict response, got {type(data).__name__}")
        return data
    except Exception as err:
        raise ProtocolError(f"Invalid response frame: {err}") from err


def format_bytes(num_bytes: int) -> str:
    """Format bytes into a human-readable string (B, KiB, MiB, GiB)."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit in ["KiB", "MiB", "GiB", "TiB"]:
        num_bytes /= 1024.0
        if num_bytes < 1024.0 or unit == "TiB":
            return f"{num_bytes:.2f} {unit}"
    return f"{num_bytes:.2f} TiB"


def format_throughput(num_bytes: int, duration_seconds: float) -> str:
    """Calculate and format throughput in bytes/s and bits/s."""
    if duration_seconds <= 0:
        return "inf B/s"
    bytes_per_sec = num_bytes / duration_seconds
    formatted_bytes_sec = format_bytes(int(bytes_per_sec)) + "/s"
    mbps = (bytes_per_sec * 8) / (1_000_000)
    return f"{formatted_bytes_sec} ({mbps:.2f} Mbps)"

