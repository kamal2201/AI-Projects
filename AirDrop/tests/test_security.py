"""Automated security tests for mTLS authenticated encryption, trust model, and approval flow."""

import os
from pathlib import Path
import shutil
import socket
import ssl
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock

from src.file_io import compute_file_sha256
from src.protocol import (
    AirDropError,
    AuthenticationError,
    ConcurrencyLimitError,
    TransferDeclinedError,
)
from src.receiver import Receiver
from src.security import (
    SecurityManager,
    TrustedPeerStore,
    compute_cert_fingerprint,
    compute_sas_pin,
    generate_self_signed_cert,
)
from src.sender import Sender


class TestCryptoAndTrustPrimitives(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="airdrop_sec_test_")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cert_generation_and_permissions(self):
        cert_path = Path(self.temp_dir) / "test.crt"
        key_path = Path(self.temp_dir) / "test.key"

        cert_pem, key_pem = generate_self_signed_cert(
            cert_path=cert_path,
            key_path=key_path,
            node_id="node123",
            display_name="TestNode",
        )

        self.assertTrue(cert_path.exists())
        self.assertTrue(key_path.exists())

        # Verify key permissions are 0600 (owner read/write only)
        key_mode = oct(key_path.stat().st_mode & 0o777)
        self.assertEqual(key_mode, "0o600")

        # Verify fingerprint formatting
        fp = compute_cert_fingerprint(cert_pem)
        self.assertTrue(fp.startswith("SHA256:"))
        self.assertEqual(len(fp.split(":")), 33)  # "SHA256" + 32 hex bytes

    def test_sas_pin_symmetry(self):
        """Both peers must compute the exact same 6-digit PIN regardless of argument order."""
        cert_a = "CERT_A_DUMMY_DATA"
        cert_b = "CERT_B_DUMMY_DATA"

        pin1 = compute_sas_pin(cert_a, cert_b)
        pin2 = compute_sas_pin(cert_b, cert_a)

        self.assertEqual(pin1, pin2)
        self.assertEqual(len(pin1), 6)
        self.assertTrue(pin1.isdigit())

    def test_trusted_peer_store_lifecycle(self):
        store_path = Path(self.temp_dir) / "trusted.json"
        store = TrustedPeerStore(store_path)

        cert_path = Path(self.temp_dir) / "peer.crt"
        key_path = Path(self.temp_dir) / "peer.key"
        cert_pem, _ = generate_self_signed_cert(cert_path, key_path, "peer01", "PeerOne")

        # Add peer
        peer = store.add_peer("peer01", "PeerOne", cert_pem.decode("ascii"))
        self.assertEqual(peer.node_id, "peer01")
        self.assertTrue(store.is_trusted("peer01", peer.fingerprint))

        # Check CA bundle
        bundle = store.get_trusted_ca_bundle_pem()
        self.assertIn("BEGIN CERTIFICATE", bundle)

        # Persistent reload
        store2 = TrustedPeerStore(store_path)
        self.assertTrue(store2.is_trusted("peer01", peer.fingerprint))

        # Remove peer
        self.assertTrue(store2.remove_peer("peer01"))
        self.assertFalse(store2.is_trusted("peer01", peer.fingerprint))


class TestAuthenticatedTlsTransfer(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="airdrop_mtls_")
        self.recv_dir = Path(self.temp_root) / "receiver"
        self.send_dir = Path(self.temp_root) / "sender"
        self.dest_files = Path(self.temp_root) / "dest_files"
        self.dest_files.mkdir(parents=True)

        # Initialize separate identities for Receiver and Sender
        self.recv_sec = SecurityManager(base_dir=self.recv_dir, node_id="recv01", display_name="RecvHost")
        self.send_sec = SecurityManager(base_dir=self.send_dir, node_id="send01", display_name="SendHost")

        # Mutual Trust: pair them with each other
        self.recv_sec.peer_store.add_peer("send01", "SendHost", self.send_sec.get_local_cert_pem())
        self.send_sec.peer_store.add_peer("recv01", "RecvHost", self.recv_sec.get_local_cert_pem())

        # Start Receiver with TLS
        self.receiver = Receiver(
            host="127.0.0.1",
            port=0,
            dest_dir=self.dest_files,
            use_tls=True,
            allow_plain_tcp=False,
            security_manager=self.recv_sec,
            auto_accept=True,
            advertise=False,
            enable_ble=False,
        )

        self.recv_thread = threading.Thread(target=self.receiver.start, daemon=True)
        self.recv_thread.start()

        start = time.time()
        while self.receiver.active_port is None and (time.time() - start < 5.0):
            time.sleep(0.01)

        self.port = self.receiver.active_port
        self.assertIsNotNone(self.port)

    def tearDown(self):
        self.receiver.stop()
        self.recv_thread.join(timeout=2.0)
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_successful_authenticated_tls_transfer(self):
        """Mutual TLS transfer succeeds, verifies fingerprint, and secures file with 0600 mode."""
        test_file = self.send_dir / "confidential.pdf"
        test_file.write_bytes(b"%PDF-1.4 Encrypted authenticated payload test!")

        sender = Sender(
            host="127.0.0.1",
            port=self.port,
            use_tls=True,
            security_manager=self.send_sec,
            prefer_direct=False,
            timeout=5.0,
        )

        res = sender.send_file(test_file, precompute_sha256=True)

        self.assertTrue(res["is_tls"])
        self.assertEqual(res["filesize"], test_file.stat().st_size)

        dest_file = self.dest_files / "confidential.pdf"
        self.assertTrue(dest_file.exists())
        self.assertEqual(compute_file_sha256(test_file), compute_file_sha256(dest_file))

        # Verify strict 0600 file permissions on received file
        file_mode = oct(dest_file.stat().st_mode & 0o777)
        self.assertEqual(file_mode, "0o600")

    def test_recipient_approval_gate_declined(self):
        """Recipient explicitly declines file transfer; transfer terminates with TransferDeclinedError."""
        # Configure receiver to decline
        self.receiver.auto_accept = False
        self.receiver.approval_callback = lambda fname, fsz, sname, nid: False

        test_file = self.send_dir / "declined_doc.txt"
        test_file.write_text("This transfer will be declined by the recipient.")

        sender = Sender(
            host="127.0.0.1",
            port=self.port,
            use_tls=True,
            security_manager=self.send_sec,
            prefer_direct=False,
            timeout=5.0,
        )

        with self.assertRaises(TransferDeclinedError):
            sender.send_file(test_file)

        # File must NOT exist on receiver
        self.assertFalse((self.dest_files / "declined_doc.txt").exists())
        self.assertEqual(len(list(self.dest_files.glob("*.part"))), 0)

    def test_untrusted_peer_rejected(self):
        """An untrusted peer presenting an unknown certificate is rejected during mTLS handshake."""
        # Create rogue sender whose certificate is NOT in receiver's trust store
        rogue_dir = Path(self.temp_root) / "rogue"
        rogue_sec = SecurityManager(base_dir=rogue_dir, node_id="rogue01", display_name="RoguePeer")
        # Rogue only trusts receiver, but receiver does NOT trust rogue
        rogue_sec.peer_store.add_peer("recv01", "RecvHost", self.recv_sec.get_local_cert_pem())

        test_file = rogue_dir / "malicious.bin"
        test_file.write_bytes(b"Unauthorized data payload!")

        sender = Sender(
            host="127.0.0.1",
            port=self.port,
            use_tls=True,
            security_manager=rogue_sec,
            prefer_direct=False,
            timeout=5.0,
        )

        with self.assertRaises(AuthenticationError):
            sender.send_file(test_file)

        # Confirm no file written
        self.assertFalse((self.dest_files / "malicious.bin").exists())

    def test_plaintext_rejected_when_strict_tls_required(self):
        """Plaintext unencrypted connection rejected when strict TLS is active."""
        test_file = self.send_dir / "plain.txt"
        test_file.write_text("Plaintext without TLS")

        # Sender without TLS (use_tls=False)
        sender = Sender(
            host="127.0.0.1",
            port=self.port,
            use_tls=False,
            prefer_direct=False,
            timeout=3.0,
        )

        with self.assertRaises(AirDropError):
            sender.send_file(test_file)

        self.assertFalse((self.dest_files / "plain.txt").exists())

    def test_tampered_payload_fails_sha256_verification(self):
        """If payload is tampered in transit, receiver detects SHA-256 failure and discards file."""
        from src.protocol import encode_header, send_exact, read_response_from_socket

        # Connect with TLS
        client_ctx = self.send_sec.create_client_ssl_context()
        raw_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.connect(("127.0.0.1", self.port))
        tls_sock = client_ctx.wrap_socket(raw_sock, server_side=False)

        try:
            # Declare 100 bytes with specific expected SHA-256
            original_bytes = b"X" * 100
            import hashlib
            expected_hash = hashlib.sha256(original_bytes).hexdigest()

            header_bytes = encode_header(
                "tampered.bin",
                len(original_bytes),
                extra={
                    "sha256": expected_hash,
                    "secure": True,
                    "sender_name": "SendHost",
                    "node_id": "send01",
                },
            )
            send_exact(tls_sock, header_bytes)

            # Read approval response
            approval = read_response_from_socket(tls_sock)
            self.assertEqual(approval.get("status"), "ok")

            # Send tampered bytes (differing from expected hash)
            tampered_bytes = b"Y" * 100
            send_exact(tls_sock, tampered_bytes)

            # Receiver must report error
            resp = read_response_from_socket(tls_sock)
            self.assertEqual(resp.get("status"), "error")
            self.assertIn("Checksum mismatch", resp.get("message", ""))
        finally:
            tls_sock.close()

        # Destination file must NOT exist
        dest_file = self.dest_files / "tampered.bin"
        self.assertFalse(dest_file.exists())
        self.assertEqual(len(list(self.dest_files.glob("*.part"))), 0)

    def test_concurrency_limit_exceeded(self):
        """When server reaches max_concurrent_transfers, subsequent connections receive busy status."""
        self.receiver.max_concurrent_transfers = 1

        # Simulate first connection holding active transfer
        with self.receiver._lock:
            self.receiver._active_transfers = 1

        try:
            test_file = self.send_dir / "busy_test.txt"
            test_file.write_text("Concurrency limit test")

            sender = Sender(
                host="127.0.0.1",
                port=self.port,
                use_tls=True,
                security_manager=self.send_sec,
                prefer_direct=False,
                timeout=3.0,
            )

            with self.assertRaises(AirDropError):
                sender.send_file(test_file)
        finally:
            with self.receiver._lock:
                self.receiver._active_transfers = 0


if __name__ == "__main__":
    unittest.main()
