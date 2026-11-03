"""Cryptographic identity, certificate management, mTLS, and trust model for AirDrop."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import datetime
import hashlib
import ipaddress
import json
import logging
import os
from pathlib import Path
import shutil
import ssl
import sys
import time
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("airdrop.security")

DEFAULT_AIRDROP_DIR = Path(os.environ.get("AIRDROP_DIR", Path.home() / ".airdrop"))
DEFAULT_CREDS_DIR = DEFAULT_AIRDROP_DIR / "credentials"
DEFAULT_TRUST_FILE = DEFAULT_AIRDROP_DIR / "trusted_peers.json"


def compute_cert_fingerprint(cert_data: bytes | str) -> str:
    """Compute standard SHA-256 fingerprint for X.509 certificate.

    Returns format 'SHA256:xx:xx:xx:...'.
    """
    if isinstance(cert_data, str):
        cert_bytes = cert_data.encode("utf-8")
    else:
        cert_bytes = cert_data

    # Parse to DER representation
    if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
        cert = x509.load_pem_x509_certificate(cert_bytes)
        der_bytes = cert.public_bytes(serialization.Encoding.DER)
    else:
        der_bytes = cert_bytes

    digest = hashlib.sha256(der_bytes).hexdigest().upper()
    colon_separated = ":".join(digest[i : i + 2] for i in range(0, len(digest), 2))
    return f"SHA256:{colon_separated}"


def compute_sas_pin(cert_pem_a: bytes | str, cert_pem_b: bytes | str) -> str:
    """Compute a 6-digit decimal Short Authentication String (SAS) from two certificates.

    The certificates are sorted so both peers arrive at the exact same PIN.
    """
    bytes_a = cert_pem_a.encode("utf-8") if isinstance(cert_pem_a, str) else cert_pem_a
    bytes_b = cert_pem_b.encode("utf-8") if isinstance(cert_pem_b, str) else cert_pem_b

    # Canonical order
    if bytes_a < bytes_b:
        combined = bytes_a + bytes_b
    else:
        combined = bytes_b + bytes_a

    digest = hashlib.sha256(combined).digest()
    numeric_val = int.from_bytes(digest[:4], "big")
    pin = (numeric_val % 900000) + 100000
    return str(pin)


def generate_self_signed_cert(
    cert_path: Path,
    key_path: Path,
    node_id: str,
    display_name: str,
    ip_addresses: list[str] | None = None,
    valid_days: int = 365,
) -> tuple[bytes, bytes]:
    """Generate a self-signed X.509 certificate and private key.

    Secures private key with 0600 permissions.
    """
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(cert_path.parent, 0o700)

    # Generate 2048-bit RSA private key
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    common_name = f"AirDrop-{node_id}"
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "AirDrop P2P"),
    ])

    san_entries: list[x509.GeneralName] = [
        x509.DNSName("localhost"),
        x509.DNSName(f"{common_name}.local"),
        x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
    ]
    if ip_addresses:
        for ip_str in ip_addresses:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                san_entries.append(x509.IPAddress(ip_obj))
            except ValueError:
                pass

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1))
        .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=valid_days))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
    )

    cert = builder.sign(key, hashes.SHA256())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )

    # Write key with strict 0600 permissions
    key_path.write_bytes(key_pem)
    os.chmod(key_path, 0o600)

    # Write cert with 0644 permissions
    cert_path.write_bytes(cert_pem)
    os.chmod(cert_path, 0o644)

    logger.debug("Generated self-signed certificate: %s", cert_path)
    return cert_pem, key_pem


@dataclass
class TrustedPeer:
    """Represents a paired, cryptographically verified peer."""

    node_id: str
    display_name: str
    fingerprint: str
    cert_pem: str
    paired_at: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TrustedPeer:
        return cls(**data)


class TrustedPeerStore:
    """Persistent storage for trusted peer identities and X.509 certificates."""

    def __init__(self, store_path: Path | None = None) -> None:
        self.store_path = store_path or DEFAULT_TRUST_FILE
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.store_path.parent, 0o700)
        self._peers: dict[str, TrustedPeer] = {}
        self._load()

    def _load(self) -> None:
        if not self.store_path.exists():
            return
        try:
            with open(self.store_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            for item in raw:
                peer = TrustedPeer.from_dict(item)
                self._peers[peer.node_id] = peer
        except Exception as err:
            logger.warning("Failed to load trusted peers file %s: %s", self.store_path, err)

    def _save(self) -> None:
        try:
            data = [p.to_dict() for p in self._peers.values()]
            temp_path = self.store_path.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, self.store_path)
        except Exception as err:
            logger.error("Failed to save trusted peers: %s", err)

    def add_peer(self, node_id: str, display_name: str, cert_pem: str) -> TrustedPeer:
        """Add or update trusted peer with certificate."""
        fingerprint = compute_cert_fingerprint(cert_pem)
        peer = TrustedPeer(
            node_id=node_id,
            display_name=display_name,
            fingerprint=fingerprint,
            cert_pem=cert_pem.strip() + "\n",
            paired_at=time.time(),
        )
        self._peers[node_id] = peer
        self._save()
        logger.info("Peer '%s' (%s) trusted with fingerprint %s", display_name, node_id, fingerprint)
        return peer

    def get_peer(self, node_id: str) -> TrustedPeer | None:
        return self._peers.get(node_id)

    def get_peer_by_fingerprint(self, fingerprint: str) -> TrustedPeer | None:
        clean = fingerprint.upper().strip()
        for p in self._peers.values():
            if p.fingerprint.upper() == clean:
                return p
        return None

    def is_trusted(self, node_id: str, cert_fingerprint: str) -> bool:
        peer = self.get_peer(node_id)
        if not peer:
            return False
        return peer.fingerprint.upper() == cert_fingerprint.upper()

    def remove_peer(self, node_id: str) -> bool:
        if node_id in self._peers:
            del self._peers[node_id]
            self._save()
            return True
        return False

    def list_peers(self) -> list[TrustedPeer]:
        return list(self._peers.values())

    def get_trusted_ca_bundle_pem(self) -> str:
        """Combine all trusted peer certificates into a single PEM bundle for TLS verification."""
        parts = [p.cert_pem.strip() for p in self._peers.values() if p.cert_pem]
        return "\n\n".join(parts) + "\n" if parts else ""

    def reset(self) -> None:
        self._peers.clear()
        if self.store_path.exists():
            try:
                self.store_path.unlink()
            except Exception:
                pass


class SecurityManager:
    """Manages local cryptographic credentials, mTLS context creation, and peer authentication."""

    def __init__(
        self,
        base_dir: Path | None = None,
        node_id: str | None = None,
        display_name: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir or DEFAULT_AIRDROP_DIR).resolve()
        self.creds_dir = self.base_dir / "credentials"
        self.cert_path = self.creds_dir / "airdrop.crt"
        self.key_path = self.creds_dir / "airdrop.key"
        self.peer_store = TrustedPeerStore(self.base_dir / "trusted_peers.json")

        self.creds_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.creds_dir, 0o700)

        self.node_id = node_id or self._load_or_create_node_id()
        self.display_name = display_name or f"AirDrop-{self.node_id[:6]}"

        # Initialize credentials
        self._init_credentials()

    def _load_or_create_node_id(self) -> str:
        node_file = self.creds_dir / "node_id.txt"
        if node_file.exists():
            return node_file.read_text(encoding="utf-8").strip()
        new_id = hashlib.sha256(os.urandom(32)).hexdigest()[:8]
        node_file.write_text(new_id, encoding="utf-8")
        os.chmod(node_file, 0o600)
        return new_id

    def _init_credentials(self) -> None:
        if not self.cert_path.exists() or not self.key_path.exists():
            logger.info("Initializing fresh cryptographic identity for node '%s'...", self.node_id)
            generate_self_signed_cert(
                cert_path=self.cert_path,
                key_path=self.key_path,
                node_id=self.node_id,
                display_name=self.display_name,
            )

    def get_local_cert_pem(self) -> str:
        return self.cert_path.read_text(encoding="utf-8")

    def get_local_fingerprint(self) -> str:
        return compute_cert_fingerprint(self.cert_path.read_bytes())

    def create_server_ssl_context(self, require_client_cert: bool = True) -> ssl.SSLContext:
        """Create secure TLS server context.

        Requires mutual authentication (mTLS) with pinned certificates.
        """
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(certfile=str(self.cert_path), keyfile=str(self.key_path))

        # Restrict to TLS 1.2 and TLS 1.3
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        if require_client_cert:
            ctx.verify_mode = ssl.CERT_REQUIRED
            ca_bundle = self.peer_store.get_trusted_ca_bundle_pem()
            if ca_bundle.strip():
                ctx.load_verify_locations(cadata=ca_bundle)
            else:
                # If no peers trusted yet, load self cert so verification mechanism remains active
                ctx.load_verify_locations(cadata=self.get_local_cert_pem())

        return ctx

    def create_client_ssl_context(self) -> ssl.SSLContext:
        """Create secure TLS client context presenting local certificate and verifying peer."""
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        ctx.load_cert_chain(certfile=str(self.cert_path), keyfile=str(self.key_path))

        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = False  # P2P dynamic endpoints; verification handled by pinned cert

        ca_bundle = self.peer_store.get_trusted_ca_bundle_pem()
        if ca_bundle.strip():
            ctx.load_verify_locations(cadata=ca_bundle)
        else:
            ctx.load_verify_locations(cadata=self.get_local_cert_pem())

        return ctx

    def reset_all(self) -> None:
        """Remove credentials and trusted peers, then reinitialize."""
        self.peer_store.reset()
        if self.creds_dir.exists():
            shutil.rmtree(self.creds_dir, ignore_errors=True)
        self.creds_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.creds_dir, 0o700)
        self.node_id = self._load_or_create_node_id()
        self._init_credentials()
        logger.info("Security credentials and trust store have been reset.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AirDrop Security & Trust Manager - Inspect and configure cryptographic pairing."
    )
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="Display local cryptographic fingerprint and node ID",
    )
    parser.add_argument(
        "--list-trusted",
        action="store_true",
        help="List all paired and trusted peer devices",
    )
    parser.add_argument(
        "--export-cert",
        metavar="OUTPUT_PATH",
        help="Export local public certificate to a PEM file for manual pairing",
    )
    parser.add_argument(
        "--trust-cert",
        nargs=3,
        metavar=("NODE_ID", "DISPLAY_NAME", "CERT_FILE"),
        help="Trust a peer by importing their public certificate file",
    )
    parser.add_argument(
        "--revoke",
        metavar="NODE_ID",
        help="Revoke trust for a specified peer node ID",
    )
    parser.add_argument(
        "--reset-all",
        action="store_true",
        help="Nuclear reset: erase all credentials and trusted peers",
    )

    args = parser.parse_args()

    mgr = SecurityManager()

    if args.fingerprint:
        print("=" * 60)
        print("AirDrop Cryptographic Identity")
        print("=" * 60)
        print(f"Node ID:     {mgr.node_id}")
        print(f"Fingerprint: {mgr.get_local_fingerprint()}")
        print(f"Cert Path:   {mgr.cert_path}")
        print(f"Key Path:    {mgr.key_path}")
        print("=" * 60)
        return

    if args.list_trusted:
        peers = mgr.peer_store.list_peers()
        if not peers:
            print("No trusted peers currently registered.")
            return
        print("=" * 80)
        print("Trusted AirDrop Peers")
        print("=" * 80)
        for p in peers:
            paired_date = datetime.datetime.fromtimestamp(p.paired_at).strftime("%Y-%m-%d %H:%M:%S")
            print(f"- Name:        {p.display_name} ({p.node_id})")
            print(f"  Fingerprint: {p.fingerprint}")
            print(f"  Paired at:   {paired_date}")
            print("-" * 80)
        return

    if args.export_cert:
        out = Path(args.export_cert)
        out.write_text(mgr.get_local_cert_pem(), encoding="utf-8")
        print(f"Exported local public certificate to {out}")
        return

    if args.trust_cert:
        node_id, name, cert_file = args.trust_cert
        p_path = Path(cert_file)
        if not p_path.exists():
            print(f"Error: Certificate file does not exist: {p_path}")
            sys.exit(1)
        cert_pem = p_path.read_text(encoding="utf-8")
        peer = mgr.peer_store.add_peer(node_id, name, cert_pem)
        pin = compute_sas_pin(mgr.get_local_cert_pem(), cert_pem)
        print(f"Successfully trusted '{name}' ({node_id})!")
        print(f"SHA-256 Fingerprint: {peer.fingerprint}")
        print(f"Short Auth PIN:     {pin}")
        return

    if args.revoke:
        if mgr.peer_store.remove_peer(args.revoke):
            print(f"Successfully revoked peer '{args.revoke}'.")
        else:
            print(f"Peer '{args.revoke}' not found in trusted store.")
        return

    if args.reset_all:
        confirm = input("Are you sure you want to erase all credentials and reset trust? [y/N]: ").strip().lower()
        if confirm in ("y", "yes"):
            mgr.reset_all()
            print("Reset complete. Generated fresh cryptographic identity.")
        else:
            print("Operation aborted.")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
