# AirDrop Threat Model, Security Architecture & Trust Model

## 1. Threat Model & Risk Analysis

### 1.1 Assets to Protect
1. **File Data in Transit**: Confidential documents, personal media, archives, and binaries transferred between devices.
2. **Device Filesystem & State**: Protecting the recipient computer from arbitrary remote writes, path traversal attacks, and disk exhaustion.
3. **Recipient Autonomy**: Preventing unsolicited files ("cyber-flashing" or payload drops) from being stored without recipient consent.
4. **Peer Cryptographic Identity**: Preventing impersonation of trusted contacts and MitM interception.

---

### 1.2 Adversary Profiles & Capabilities
- **Adversary A (Passive LAN Eavesdropper)**: Monitored or unencrypted local Wi-Fi, public hotspots, or compromised switches capturing packet dumps.
- **Adversary B (Active LAN Man-in-the-Middle)**: Capable of ARP cache poisoning, DNS-SD spoofing, rogue Wi-Fi AP deployment, or TCP connection hijacking.
- **Adversary C (Rogue Unauthenticated Peer)**: Discovers receiver via mDNS/BLE on the same network and attempts to push unsolicited, malicious, or malformed files.
- **Adversary D (Malicious / Corrupted Sender)**: Intentionally alters payload bytes in transit, transmits declared filesizes differing from real payloads, or attempts directory escapes (`../../`).

---

### 1.3 Threat Mitigations Matrix

| Threat | Attack Vector | Security Mechanism / Defense |
| :--- | :--- | :--- |
| **Passive Eavesdropping** | Packet capture on shared Wi-Fi | **TLS 1.3 / 1.2 Encrypted Transport** with modern forward-secret cipher suites (ECDHE-RSA / ECDHE-ECDSA). |
| **Man-in-the-Middle (MitM)** | ARP / DNS spoofing with rogue certificates | **Certificate Fingerprint Pinning & Mutual Authentication**: Certificates are cryptographically bound to peer identities; unknown certificates trigger pairing prompts with out-of-band Short Authentication String (SAS) verification. |
| **Impersonation** | Forged node ID claiming to be trusted contact | **Cryptographic Signature Verification**: Node ID is verified against the peer's pinned public certificate SHA-256 fingerprint; key substitutions trigger security alerts and connection aborts. |
| **Unsolicited Payloads** | Automated push of malicious files | **Mandatory Recipient Approval Gate**: Recipient must explicitly approve file name and size before the transfer begins. |
| **In-Flight Data Tampering** | Bit-flipping or proxy payload modification | **Dual Verification**: Streamed payload is decrypted via authenticated TLS AEAD ciphers AND verified against an end-to-end authenticated SHA-256 digest in the signed header. |
| **Path Traversal Escape** | Malicious filenames (`../../.bashrc`) | **Strict Filename Sanitization**: Directory separators (`/`, `\`), relative tokens (`..`), null bytes, and root paths are rejected before file creation. |
| **Shared Multi-User Exposure**| Another local user reading received files | **Restrictive File Permissions**: Files are created with `0600` (owner read/write only) inside a `0700` restricted directory. |
| **Denial of Service (DoS)** | Giant header / disk filling | **Strict Resource Limits**: Max header size (64 KiB), max file size ceiling (100 GiB), disk headroom pre-checks, and connection concurrency limits. |

---

## 2. Trust Model: TOFU + Short Authentication String (SAS)

AirDrop operates in local, decentralized, peer-to-peer environments where centralized Certificate Authorities (CAs) are absent. The application implements **Trust On First Use (TOFU) with Short Authentication String (SAS) Verification**:

1. **Self-Signed Ephemeral X.509 Certificates**:
   - Each AirDrop node generates its own 2048-bit RSA X.509 certificate and private key on first run.
   - Credentials are stored securely in `~/.airdrop/credentials/` with strict `0600` file permissions.
2. **Mutual Verification (mTLS)**:
   - Both Sender and Receiver present their X.509 certificate during TLS handshake.
   - TLS cipher suites require modern AEAD encryption (`TLS_AES_256_GCM_SHA384`, `ECDHE-RSA-AES256-GCM-SHA384`).
3. **Peer Fingerprint Pinning**:
   - The SHA-256 fingerprint of the peer's DER certificate is computed: `SHA256:xx:xx:xx...`
   - If the peer is already trusted in `~/.airdrop/trusted_peers.json`, the fingerprint must match exactly.
   - If a known device presents a differing certificate, connection is immediately aborted as a potential MitM attack.
4. **First-Time Device Pairing**:
   - When connecting to a first-time device, both parties calculate a 6-digit numeric Short Authentication String (SAS) derived deterministically from the sorted hashes of both certificates:
     $$\text{PIN} = (\text{SHA256}(\text{Cert}_A \mathbin{\Vert} \text{Cert}_B) \pmod{900000}) + 100000$$
   - Users compare this 6-digit PIN out-of-band across screens.
   - Upon explicit confirmation, the peer's fingerprint is committed to `trusted_peers.json`.

---

## 3. Explicit Recipient Approval Flow

Before receiving a single byte of file payload, the receiver executes an interactive or callback-driven approval gate:

```
Sender -> Receiver:  [TLS Handshake (Mutual Certificate Exchange)]
Sender -> Receiver:  [Header Frame: filename="financials.xlsx", filesize=2097152, sha256="..."]
Receiver UI:         "Incoming file transfer from 'Laptop-B':
                      File: 'financials.xlsx' (2.00 MiB)
                      Accept transfer? [y/N]: "
Receiver -> Sender:  [Response Frame: status="ok"] (or status="declined")
[Payload stream commences only if approved]
```

If the recipient enters `n` (or timeout expires), the receiver replies with `{"status": "declined", "message": "Recipient declined file transfer."}` and closes the connection. No partial file is created on disk.

---

## 4. Pairing & Reset Procedures

### 4.1 Checking Local Cryptographic Fingerprint
```bash
python3 -m src.security --fingerprint
```
Displays your local node ID, certificate path, and SHA-256 public key fingerprint.

### 4.2 Listing Trusted Devices
```bash
python3 -m src.security --list-trusted
```

### 4.3 Manually Trusting / Pairing a Peer
```bash
python3 -m src.security --trust-peer <node_id> <display_name> <sha256_fingerprint>
```

### 4.4 Revoking a Specific Peer
```bash
python3 -m src.security --revoke-peer <node_id>
```

### 4.5 Resetting All Cryptographic Trust (Nuclear Reset)
```bash
python3 -m src.security --reset-all
```
Wipes `trusted_peers.json` and regenerates a fresh local certificate and private key.
