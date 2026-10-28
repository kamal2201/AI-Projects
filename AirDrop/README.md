# AirDrop — Local File Transfer & LAN Discovery

A robust, minimal, cross-platform file transfer system with zero-configuration LAN discovery built in Python 3.11+.

- **Phase 0**: Reliable TCP streaming file transfer protocol with bounded memory chunking, atomic file replacement, path traversal protection, and SHA-256 integrity verification.
- **Phase 1**: Automatic LAN discovery using mDNS/DNS-SD (Multicast DNS Service Discovery) with zero manual IP entry, live status tracking, duplicate name handling, and instant departure detection.

---

## Key Features

1. **Automatic LAN Discovery (mDNS/DNS-SD)**:
   - Advertises the custom service type `_airdrop-file._tcp.local.`.
   - Discovers active receivers automatically across the local Wi-Fi or Ethernet network.
   - Live CLI list with display name, IP address, port, and availability status (`AVAILABLE` / `UNAVAILABLE`).
   - Clean shutdown with DNS-SD goodbye packets (TTL=0) so departed peers disappear immediately.
   - Periodic background sweep for unannounced dropouts.
   - Handles multi-interface environments, filtering inactive virtual/tunnel interfaces.
   - Disambiguates duplicate hostnames via collision-safe instance naming.
   - **Privacy First**: Advertises zero personal data, usernames, or file paths.

2. **Phase 0 Binary Streaming Protocol**:
   - Fixed 4-byte big-endian header length framing (`>I`).
   - JSON metadata header (`filename`, `filesize`).
   - Constant-memory 64 KiB bounded chunk streaming.
   - Full SHA-256 end-to-end verification.
   - Atomic file writer (`.part` temp file in target folder, replaced via `os.replace` only upon complete verification).
   - Strict path traversal rejection (`..`, `/`, `\`, null bytes).
   - Pre-flight disk space headroom verification.

---

## Project Structure

```
AirDrop/
├── requirements.txt      # zeroconf>=0.136.0 (pure Python mDNS/DNS-SD engine)
├── src/
│   ├── __init__.py       # Package indicator
│   ├── protocol.py       # Framing, binary encode/decode, custom errors, metrics formatters
│   ├── file_io.py        # Atomic file writer, chunk streamer, path safety, disk checks, SHA-256
│   ├── discovery.py      # mDNS service advertiser, peer browser, registry, interactive picker
│   ├── receiver.py       # TCP server socket listener, client session handler, mDNS advertiser
│   └── sender.py         # TCP client, interactive LAN discovery, file streamer, SHA-256 verifier
├── tests/
│   ├── __init__.py
│   ├── test_protocol.py  # Framing, encoding, limits, socket primitives
│   ├── test_file_io.py   # Sanitization, path escape protection, atomic commits, disk checks
│   ├── test_transfer.py  # End-to-end transfers: empty, small, binary, 5 MiB large, sequential
│   ├── test_security_errors.py # Path traversal, truncated streams, bad headers, disconnects
│   └── test_discovery.py # mDNS advertisement, peer browser, duplicate names, goodbye events
└── README.md
```

---

## Installation

Ensure Python 3.11+ is installed, then install the single lightweight dependency (`zeroconf`):

```bash
cd AirDrop
pip install -r requirements.txt
```

---

## Running the Automated Test Suite

Run all 54 unit and integration tests:

```bash
python3 -m unittest discover -v -s tests
```

Tests cover:
- Protocol encoding, validation, oversized headers, and socket framing.
- Path traversal rejection (`../../etc/passwd`, Windows drive paths, null bytes).
- Chunked streaming, disk space checking, and atomic temporary writes.
- 0-byte, small text, arbitrary binary, and 5 MiB large file transfers.
- Network disconnects, truncated payloads, and checksum mismatches.
- mDNS service registration, duplicate instance names, live LAN discovery, and goodbye packet removal.

---

## Two-Computer Demonstration (Zero IP Entry)

Connect **Computer A** (Receiver) and **Computer B** (Sender) to the same Wi-Fi or Ethernet network.

### 1. On Computer A (Receiver)

Start the receiver. By default, it automatically advertises itself over mDNS:

```bash
cd AirDrop
python3 -m src.receiver --name "Office-Mac" --dest-dir ./received
```

Output:
```
============================================================
AirDrop Receiver listening on 0.0.0.0:5001
Destination directory: /Users/.../received
Max file size: 100.00 GiB
============================================================
mDNS service registered: 'Office-Mac' (192.168.1.45:5001)
```

*(You can press Ctrl-C at any time; the receiver will broadcast a goodbye packet and shut down cleanly).*

---

### 2. On Computer B (Sender)

#### Option A: Interactive Selection
Simply pass the file you want to send. The sender scans the LAN, shows discovered devices, and prompts you to select the target:

```bash
cd AirDrop
python3 -m src.sender /path/to/my_presentation.pdf
```

Example interactive session:
```
Scanning local network for AirDrop devices (2.5s)...

Discovered Devices:
+---+--------------+--------------+------+-----------+
| # | Display Name | IP Address   | Port | Status    |
+===+==============+==============+======+===========+
| 1 | Office-Mac   | 192.168.1.45 | 5001 | AVAILABLE |
+---+--------------+--------------+------+-----------+

Connect to 'Office-Mac'? [Y/n]: y
Target acquired: 'Office-Mac' (192.168.1.45:5001)
Starting transfer of 'my_presentation.pdf' (14.20 MiB, 14889728 bytes)...
Waiting for receiver acknowledgment...
Integrity verified: SHA-256 matches receiver (a4f91b...)
============================================================
Transfer Succeeded: my_presentation.pdf
Destination:       192.168.1.45:5001
Bytes transferred: 14.20 MiB (14889728 bytes)
Transfer duration: 0.128 s
Average throughput:110.94 MiB/s (930.60 Mbps)
SHA-256 digest:    a4f91b5c21...
============================================================
```

#### Option B: Target by Name Directly
Send directly to a peer by name without entering an IP address:

```bash
python3 -m src.sender --to "Office-Mac" /path/to/my_presentation.pdf
```

#### Option C: Direct IP/Port (Phase 0 Fallback)
If you prefer direct connection without discovery:

```bash
python3 -m src.sender 192.168.1.45 5001 /path/to/my_presentation.pdf
```

---

### 3. Monitoring LAN Peers Live

To monitor active peers appearing and departing in real time:

```bash
python3 -m src.discovery --watch
```

When Computer A stops its receiver (Ctrl-C), its status immediately updates to `UNAVAILABLE` or departs from the table.

---

## Network, Firewall & Multicast Troubleshooting

mDNS / DNS-SD operates via UDP multicast on IP address `224.0.0.251` and port `5353`. TCP file transfers operate on the receiver's configured port (default `5001`).

### 1. macOS
- **Local Network Permission**: When running on macOS 14+, macOS may prompt: *"python3 would like to find and connect to devices on your local network"*. Click **Allow**.
- If denied previously, enable it under **System Settings > Privacy & Security > Local Network > python3**.

### 2. Windows
- **Firewall Prompt**: When starting the receiver or discovery, Windows Defender Firewall will prompt to allow network access.
  - Check **Private networks** (home or work).
  - If blocked, open **Windows Defender Firewall with Advanced Security**:
    - Add an Inbound Rule for **UDP port 5353** (mDNS).
    - Add an Inbound Rule for **TCP port 5001** (File Transfer).

### 3. Linux
- If using `ufw`, open mDNS and the file transfer port:
  ```bash
  sudo ufw allow 5353/udp comment "mDNS"
  sudo ufw allow 5001/tcp comment "AirDrop Transfer"
  ```
- If `avahi-daemon` is running, `zeroconf` can coexist on port 5353 using `SO_REUSEPORT`.

### 4. Wi-Fi Router Settings (AP / Client Isolation)
- Many corporate, guest, or school Wi-Fi networks enable **Client Isolation** (or **AP Isolation**), which blocks devices on the same Wi-Fi network from communicating with one another.
- Ensure both computers are on the same standard private LAN (or a mobile hotspot) where peer-to-peer traffic is permitted.

---

## Protocol & Safety Reference

| Scenario | Handled By | Behavior |
| :--- | :--- | :--- |
| **Peer Departure** | mDNS Goodbye (TTL=0) | Device marked unavailable or unlisted within milliseconds of receiver shutdown. |
| **Peer Silent Dropout** | TTL Sweeper | Unrefreshed devices marked `UNAVAILABLE` after 30s timeout. |
| **Duplicate Hostnames** | Instance Renaming | Short random node ID suffix ensures zero DNS-SD conflicts (`Host-a1b2`). |
| **Path Traversal Attack** | `file_io.sanitize_filename` | Drops connection and rejects files containing `..`, `/`, `\`, or null bytes. |
| **Header Overflow** | `protocol.read_header_from_socket` | Rejects headers > 64 KiB before allocation. |
| **Truncated Stream** | `AtomicFileWriter` | Unlinks incomplete `.part` file; no corrupted file left. |
| **Disk Exhaustion** | `file_io.check_disk_space` | Pre-checks free disk space + 10 MiB margin before accepting bytes. |
| **Checksum Verification** | SHA-256 Engine | Sender and receiver match full payload hash byte-for-byte. |
