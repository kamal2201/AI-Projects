"""Unit tests for AirDrop protocol framing, encoding, decoding, and socket primitives."""

import json
import socket
import struct
import unittest

from src.protocol import (
    DEFAULT_MAX_FILE_SIZE,
    DEFAULT_MAX_HEADER_SIZE,
    HEADER_PREFIX_FORMAT,
    HEADER_PREFIX_SIZE,
    ConnectionClosedError,
    HeaderTooLargeError,
    OversizedFileError,
    ProtocolError,
    decode_header,
    encode_header,
    encode_response,
    format_bytes,
    format_throughput,
    read_header_from_socket,
    read_response_from_socket,
    recv_exact,
    send_exact,
)


class TestProtocolEncoding(unittest.TestCase):
    def test_encode_valid_header(self):
        encoded = encode_header("sample.pdf", 1024)
        prefix = encoded[:HEADER_PREFIX_SIZE]
        (length,) = struct.unpack(HEADER_PREFIX_FORMAT, prefix)
        body = encoded[HEADER_PREFIX_SIZE:]
        self.assertEqual(len(body), length)
        data = json.loads(body.decode("utf-8"))
        self.assertEqual(data["filename"], "sample.pdf")
        self.assertEqual(data["filesize"], 1024)

    def test_encode_with_extra_fields(self):
        extra = {"sha256": "abcdef123456", "custom": "meta"}
        encoded = encode_header("doc.txt", 50, extra=extra)
        decoded = decode_header(encoded[HEADER_PREFIX_SIZE:])
        self.assertEqual(decoded["filename"], "doc.txt")
        self.assertEqual(decoded["filesize"], 50)
        self.assertEqual(decoded["sha256"], "abcdef123456")
        self.assertEqual(decoded["custom"], "meta")

    def test_encode_invalid_filename(self):
        with self.assertRaises(ProtocolError):
            encode_header("", 100)
        with self.assertRaises(ProtocolError):
            encode_header("   ", 100)
        with self.assertRaises(ProtocolError):
            encode_header("file\x00name.txt", 100)
        with self.assertRaises(ProtocolError):
            encode_header(None, 100)  # type: ignore

    def test_encode_invalid_filesize(self):
        with self.assertRaises(ProtocolError):
            encode_header("file.txt", -1)
        with self.assertRaises(ProtocolError):
            encode_header("file.txt", 12.34)  # type: ignore
        with self.assertRaises(ProtocolError):
            encode_header("file.txt", True)  # type: ignore
        with self.assertRaises(ProtocolError):
            encode_header("file.txt", "1024")  # type: ignore

    def test_encode_header_too_large(self):
        with self.assertRaises(HeaderTooLargeError):
            encode_header("file.txt", 10, extra={"huge": "x" * 1000}, max_header_size=100)


class TestProtocolDecoding(unittest.TestCase):
    def test_decode_valid(self):
        raw = json.dumps({"filename": "image.png", "filesize": 4096}).encode("utf-8")
        data = decode_header(raw)
        self.assertEqual(data["filename"], "image.png")
        self.assertEqual(data["filesize"], 4096)

    def test_decode_invalid_utf8(self):
        with self.assertRaises(ProtocolError):
            decode_header(b"\xff\xfe\xfd")

    def test_decode_invalid_json(self):
        with self.assertRaises(ProtocolError):
            decode_header(b"not json")

    def test_decode_non_dict_json(self):
        with self.assertRaises(ProtocolError):
            decode_header(b'["list", "not", "dict"]')
        with self.assertRaises(ProtocolError):
            decode_header(b"12345")

    def test_decode_missing_filename(self):
        with self.assertRaises(ProtocolError):
            decode_header(json.dumps({"filesize": 100}).encode("utf-8"))

    def test_decode_missing_filesize(self):
        with self.assertRaises(ProtocolError):
            decode_header(json.dumps({"filename": "doc.txt"}).encode("utf-8"))

    def test_decode_oversized_file(self):
        raw = json.dumps({"filename": "huge.iso", "filesize": 100_000}).encode("utf-8")
        with self.assertRaises(OversizedFileError):
            decode_header(raw, max_file_size=50_000)


class TestSocketPrimitives(unittest.TestCase):
    def test_send_and_recv_exact(self):
        s1, s2 = socket.socketpair()
        try:
            payload = b"Hello, TCP socket world!" * 100
            send_exact(s1, payload)
            received = recv_exact(s2, len(payload))
            self.assertEqual(received, payload)
        finally:
            s1.close()
            s2.close()

    def test_recv_exact_zero_bytes(self):
        s1, s2 = socket.socketpair()
        try:
            self.assertEqual(recv_exact(s2, 0), b"")
        finally:
            s1.close()
            s2.close()

    def test_recv_exact_early_disconnect(self):
        s1, s2 = socket.socketpair()
        try:
            s1.sendall(b"short")
            s1.close()
            with self.assertRaises(ConnectionClosedError) as ctx:
                recv_exact(s2, 100)
            self.assertEqual(ctx.exception.bytes_read, 5)
            self.assertEqual(ctx.exception.expected_bytes, 100)
        finally:
            s2.close()

    def test_read_header_from_socket_valid(self):
        s1, s2 = socket.socketpair()
        try:
            frame = encode_header("test.bin", 2048)
            s1.sendall(frame)
            header, wire_bytes = read_header_from_socket(s2)
            self.assertEqual(header["filename"], "test.bin")
            self.assertEqual(header["filesize"], 2048)
            self.assertEqual(wire_bytes, len(frame))
        finally:
            s1.close()
            s2.close()

    def test_read_header_header_too_large(self):
        s1, s2 = socket.socketpair()
        try:
            # Craft prefix claiming 1000 bytes header length
            s1.sendall(struct.pack(HEADER_PREFIX_FORMAT, 1000))
            with self.assertRaises(HeaderTooLargeError):
                read_header_from_socket(s2, max_header_size=100)
        finally:
            s1.close()
            s2.close()

    def test_read_header_zero_length(self):
        s1, s2 = socket.socketpair()
        try:
            s1.sendall(struct.pack(HEADER_PREFIX_FORMAT, 0))
            with self.assertRaises(ProtocolError):
                read_header_from_socket(s2)
        finally:
            s1.close()
            s2.close()

    def test_response_encoding_and_decoding(self):
        s1, s2 = socket.socketpair()
        try:
            frame = encode_response("ok", "Success", {"sha256": "dummyhash"})
            s1.sendall(frame)
            resp = read_response_from_socket(s2)
            self.assertEqual(resp["status"], "ok")
            self.assertEqual(resp["message"], "Success")
            self.assertEqual(resp["sha256"], "dummyhash")
        finally:
            s1.close()
            s2.close()


class TestFormattingHelpers(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(500), "500 B")
        self.assertEqual(format_bytes(1024), "1.00 KiB")
        self.assertEqual(format_bytes(1024 * 1024 * 5), "5.00 MiB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 2), "2.00 GiB")

    def test_format_throughput(self):
        s = format_throughput(1024 * 1024, 1.0)
        self.assertIn("1.00 MiB/s", s)
        self.assertIn("Mbps", s)
        self.assertEqual(format_throughput(1024, 0), "inf B/s")


if __name__ == "__main__":
    unittest.main()
