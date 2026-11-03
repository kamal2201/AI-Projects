# AirDrop: Peer-to-Peer Local File Transfer

A fast, private, and secure file transfer application for local networks and direct Wi-Fi connections, built in Python 3.11+.

AirDrop allows you to transfer files between computers on the same network—or directly between two computers without any router or internet connection—using encrypted peer-to-peer streaming, automatic local discovery, and cryptographic identity verification.

---

## Table of Contents
1. [Why AirDrop Must Be Open on Both Devices](#why-airdrop-must-be-open-on-both-devices)
2. [Quick Start](#quick-start)
   - [Option A: Graphical Desktop App (Recommended)](#option-a-graphical-desktop-app-recommended)
   - [Option B: Command-Line Interface (CLI)](#option-b-command-line-interface-cli)
3. [How It Works Under the Hood](#how-it-works-under-the-hood)
   - [1. Device Discovery & Proximity (mDNS + BLE)](#1-device-discovery--proximity-mdns--ble)
   - [2. Transport & Connectivity (Direct Wi-Fi + LAN Fallback)](#2-transport--connectivity-direct-wi-fi--lan-fallback)
   - [3. Security, Encryption & Trust Model](#3-security-encryption--trust-model)
   - [4. Streaming Engine & Atomic File Integrity](#4-streaming-engine--atomic-file-integrity)
4. [Step-by-Step Two-Computer Guide](#step-by-step-two-computer-guide)
   - [Standard Network Transfer](#standard-network-transfer)
   - [Routerless Direct Transfer (No Wi-Fi Router)](#routerless-direct-transfer-no-wi-fi-router)
5. [Security, Pairing & Device Trust](#security-pairing--device-trust)
   - [The Pairing Flow & 6-Digit PIN](#the-pairing-flow--6-digit-pin)
   - [Managing Trusted Peers](#managing-trusted-peers)
6. [Throughput Benchmarks](#throughput-benchmarks)
7. [Troubleshooting & Firewall Setup](#troubleshooting--firewall-setup)
8. [Platform Support Matrix](#platform-support-matrix)
9. [Project Architecture & Automated Tests](#project-architecture--automated-tests)

---

## Why AirDrop Must Be Open on Both Devices

Unlike cloud services (Google Drive, Dropbox, or messaging apps), **AirDrop has no central server**. Files never leave your local physical space. For a direct transfer to work:

1. **Neither device is a permanent cloud server**: When you open AirDrop on Computer A, it opens a secure, temporary local port ready to receive incoming data. When closed, that port is shut down.
2. **Discovery broadcasts**: AirDrop continuously announces its availability over local network multicast and Bluetooth Low Energy (BLE) beacons. If the app is closed, the computer remains silent and invisible.
3. **Recipient consent**: Modern operating systems reject unauthorized remote file writes. The receiving application must be running to display the transfer request ("*Accept file 'presentation.pdf' from Laptop-B?*") and decrypt the incoming TLS stream.

---

## Quick Start

### Installation
Ensure Python 3.11+ is installed, then install the lightweight dependencies:

```bash
cd AirDrop
pip install -r requirements.txt
```

*(Dependencies: `zeroconf` for mDNS network discovery, `bleak` for Bluetooth Low Energy scanning, and `cryptography` for mutual TLS certificates).*

---

### Option A: Graphical Desktop App (Recommended)

Run this single command on **both** computers:

```bash
python3 -m src.ui
```

```
+---------------------------------------------------------------------------------------+
| AirDrop P2P                                                   [ Security & Trust ]    |
| Node ID: a8f21c09 | Security: SHA256:7B:3A:9F:C1... | Port: 5001                     |
+-------------------------------------------+-------------------------------------------+
| Nearby Devices (mDNS + BLE)               | Files to Transfer                         |
| +---------------------------------------+ | +---------------------------------------+ |
| | Device     Status    Protocol  Signal | | | project_archive.zip (14.20 MiB)       | |
| | Studio-Mac REACHABLE mDNS+BLE  -58dBm | | | contracts.pdf (1.45 MiB)              | |
| | Phone-Node DISCOVERED BLE       -72dBm| | | presentation.key (8.10 MiB)           | |
| +---------------------------------------+ | +---------------------------------------+ |
| [Select a device to send]                 | [ + Add Files... ]  [ Clear List ]        |
|                                           | 3 files selected (23.75 MiB)              |
|                                           | [ Send to Studio-Mac ]                    |
+-------------------------------------------+-------------------------------------------+
| Transfer Monitor                                                                      |
| Sending 'project_archive.zip': 68% (9.65 MiB / 14.20 MiB)                             |
| [=======================================>                 ]                           |
| Speed: 104.20 MiB/s (874.1 Mbps) | ETA: 0.1s            [ Cancel Transfer ]           |
+---------------------------------------------------------------------------------------+
```

1. Both computers will automatically appear in each other's **Nearby Devices** list.
2. On the sender, click **"+ Add Files..."** and choose one or more files.
3. Select the destination device from the list and click **"Send"**.
4. The receiver will see an **Incoming Transfer Request** popup with the sender's identity, filename, and size.
5. Click **"Accept"** to receive the file.

---

### Option B: Command-Line Interface (CLI)

If you prefer using the terminal or running headless:

**On Computer A (Receiver):**
```bash
python3 -m src.receiver --name "Office-Mac" --dest-dir ./received
```
*(Add `--auto-accept` to automatically accept transfers without prompting, or `--secure` for strict TLS mode).*

**On Computer B (Sender):**
```bash
# Auto-discovers receiver over LAN/BLE and prompts you to select it:
python3 -m src.sender /path/to/my_file.zip

# Or target by name directly:
python3 -m src.sender --to "Office-Mac" /path/to/my_file.zip
```

---

## How It Works Under the Hood

```
+-------------------------------------------------------------------------+
|                         Desktop User Interface                          |
|  - Event-driven thread-safe Queue (root.after polling)                  |
|  - Live Device Radar, Multi-file Queue, Progress & ETA, Consent Modals  |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                        Application Service Layer                        |
|  - DiscoveryService: background mDNS & BLE scanner orchestration        |
|  - ReceiverService: listener thread, incoming consent gate, ACK         |
|  - TransferService: background worker queue, streaming progress, cancel |
|  - SecurityService: local credentials, fingerprinting, SAS pairing      |
+------------------------------------+------------------------------------+
                                     |
           +-------------------------+-------------------------+
           |                                                   |
           v                                                   v
+-----------------------+                           +---------------------+
|   mDNS / DNS-SD       |                           |     BLE Discovery   |
| - RFC 6762 / RFC 6763 |                           | - UUID 128-bit      |
| - Service: _airdrop   |                           | - Bleak Scanner     |
| - Resolves LAN IP/Port|                           | - CoreBluetooth /   |
| - Goodbye (TTL=0)     |                           |   BlueZ Advertiser  |
+-----------+-----------+                           +----------+----------+
            |                                                  |
            +------------------------+-------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                        Transport Abstraction Layer                      |
|  - Primary: Direct Wi-Fi (SoftAP / Wi-Fi Direct routerless link)        |
|  - Fallback: Infrastructure LAN TCP (automatic seamless failover)       |
+------------------------------------+------------------------------------+
                                     |
                                     v
+-------------------------------------------------------------------------+
|                        Security & Hardening Engine                      |
|  - Mutual TLS (mTLS): TLS 1.3 / 1.2 with mandatory client certificates  |
|  - Trust Model: TOFU + Short Authentication String (SAS 6-digit PIN)   |
|  - Recipient Approval Gate: interactive/callback consent before bytes   |
|  - Strict Isolation: 0600 file permissions, 64 KiB header limit        |
+------------------------------------+------------------------------------+
                                     |
                                     v
                      +-----------------------------+
                      |     TCP Streaming Engine    |
                      | - Length-prefixed JSON frame|
                      | - 64 KiB bounded chunks     |
                      | - Atomic .part writer       |
                      | - SHA-256 Checksum ACK      |
                      +-----------------------------+
```

The system operates across four coordinated layers:

### 1. Device Discovery & Proximity (mDNS + BLE)
AirDrop combines local network discovery with short-range radio discovery:
- **Multicast DNS (mDNS / DNS-SD)**: Broadcasts service type `_airdrop-file._tcp.local.` via UDP multicast (`224.0.0.251:5353`). Resolves the receiver's IP address and port without any configuration or central DNS server.
- **Bluetooth Low Energy (BLE)**: Broadcasts proximity beacons with a 128-bit service UUID (`f7826da6-4fa2-4e98-8024-bc5b71e0893e`) and an ephemeral local node ID (`AD-<node_id>`). BLE allows devices to recognize nearby computers even before network traffic flows.
- **Unified Device Registry**: Merges mDNS and BLE beacons into a single entry per physical machine. It tracks four distinct reachability states:
  - `DISCOVERED`: Detected nearby via Bluetooth, but lacks a resolved IP address. (File transfer is blocked until an IP endpoint is established).
  - `REACHABLE`: Has resolved IP and port, ready for high-speed file transfer.
  - `CONNECTED`: Active transfer in progress.
  - `UNAVAILABLE`: Device departed (via DNS-SD goodbye packet with TTL=0) or silent timeout (>30s).
- **Privacy First**: Broadcasts contain **zero personal information**, email addresses, phone numbers, usernames, or file paths.

---

### 2. Transport & Connectivity (Direct Wi-Fi + LAN Fallback)
Connection establishment is decoupled from data transmission:
- **Routerless Direct Wi-Fi**: Both computers can connect directly over their Wi-Fi antennas without an intermediate home or office router.
  - **macOS**: Apple's native AirDrop uses AWDL (`awdl0`), which is completely private to Apple and blocked to third-party apps. AirDrop officially uses **Wi-Fi SoftAP / Local Hotspot** (via `networksetup` or System Settings Sharing), creating a direct 802.11ac/ax point-to-point link.
  - **Linux**: Supports Wi-Fi Direct (P2P) via `wpa_supplicant` and Wi-Fi Hotspot mode via NetworkManager (`nmcli dev wifi hotspot`).
  - **Windows**: Supports Wi-Fi Direct via WinRT `Windows.Devices.WiFiDirect` and Mobile Hotspot.
- **Automatic LAN Fallback**: When sending a file, AirDrop attempts the Direct Wi-Fi connection first. If unreachable (e.g. peer is not connected to the direct hotspot or the radio is busy), it logs the exact failure diagnostic and seamlessly falls back to standard LAN TCP without interrupting the user.

---

### 3. Security, Encryption & Trust Model
AirDrop protects your data against local network sniffers, rogue senders, and malicious files:
- **Mutual TLS (mTLS)**: Transfers are encrypted end-to-end using TLS 1.3 or TLS 1.2 with forward-secret AEAD cipher suites (`TLS_AES_256_GCM_SHA384`, `ECDHE-RSA-AES256-GCM`). Both sender and receiver present cryptographic X.509 certificates (`ssl.CERT_REQUIRED`). Anonymous TLS is strictly prohibited.
- **Certificate Fingerprint Pinning**: Each device generates an RSA X.509 certificate and private key stored with strict `0600` permissions in `~/.airdrop/credentials/`. Paired devices have their SHA-256 certificate fingerprints pinned in `trusted_peers.json`. If a known device ever changes its certificate, the connection is instantly aborted as a potential Man-in-the-Middle (MitM) attack.
- **TOFU + 6-Digit SAS Pairing**: When connecting to a new device for the first time, both computers independently compute an identical 6-digit numeric Short Authentication String (SAS PIN) from the sorted hashes of their certificates. Users compare this PIN across screens to confirm pairing.
- **Mandatory Consent Gate**: Before receiving any payload bytes, the receiver must approve the transfer. If declined, the connection closes and no file is created.
- **Multi-User Protection**: Received files are committed with `0600` file permissions (owner read/write only) inside a `0700` restricted directory, protecting sensitive data on shared workstations.

---

### 4. Streaming Engine & Atomic File Integrity
- **Framing Protocol**: A fixed 4-byte big-endian prefix (`>I`) specifies the length of a UTF-8 JSON header containing `filename`, `filesize`, `sender_name`, `node_id`, and `sha256`.
- **Bounded Chunk Streaming**: Files stream in bounded 64 KiB chunks. Memory footprint remains constant regardless of file size (tested up to multi-gigabyte transfers).
- **Atomic Writes**: Incoming chunks are written to a temporary `.part` file in the destination folder. Only after the transfer completes and the cryptographic hash is verified does `os.replace` atomically commit the file.
- **Automatic Cleanup on Drop**: If the sender disconnects, cancels, or the Wi-Fi link drops mid-stream, the partial `.part` file is immediately unlinked. Incomplete or corrupted files are never left on disk.
- **Cryptographic SHA-256 Checksum**: The sender precomputes the SHA-256 digest (or streams it). The receiver calculates the SHA-256 digest on the fly. If a single bit differs, the receiver discards the file, rejects the transfer, and sends a failure alert.

---

## Step-by-Step Two-Computer Guide

### Standard Network Transfer (Same Wi-Fi or Ethernet)

1. Connect **Computer A** and **Computer B** to the same Wi-Fi network or local Ethernet switch.
2. Launch the application on both computers:
   ```bash
   python3 -m src.ui
   ```
3. Computer A and Computer B will automatically detect each other within seconds.
4. On Computer B, click **"+ Add Files..."**, select your document or video, select Computer A in the device list, and click **"Send"**.
5. On Computer A, an approval popup will appear. Click **"Accept"**.
6. The progress bar will stream the file in real-time, displaying transfer speed (MB/s) and estimated time remaining.

---

### Routerless Direct Transfer (No Wi-Fi Router)

When you are outdoors or on a network where devices cannot see each other:

1. **On Computer A (Receiver)**:
   - Check setup instructions for your OS anytime:
     ```bash
     python3 -m src.receiver --info-direct
     ```
   - **macOS**: Go to **System Settings > General > Sharing > Internet Sharing**, turn on Wi-Fi sharing to create a direct Wi-Fi hotspot, or create an ad-hoc Wi-Fi network.
   - **Linux**: Run `nmcli dev wifi hotspot ifname wlan0 ssid AirDrop-Direct password airdrop12345`
   - **Windows**: Turn on **Mobile Hotspot** in Windows Settings > Network & Internet.
   - Start the receiver:
     ```bash
     python3 -m src.receiver --port 5001 --dest-dir ./received
     ```
2. **On Computer B (Sender)**:
   - Connect Computer B's Wi-Fi directly to Computer A's hotspot.
   - Send the file specifying Computer A's direct hotspot IP (typically `192.168.2.1` on macOS or `192.168.137.1` on Windows):
     ```bash
     python3 -m src.sender --direct-host 192.168.2.1 --direct-port 5001 /path/to/archive.zip
     ```

---

## Security, Pairing & Device Trust

AirDrop provides a dedicated security manager CLI via `src/security.py`:

```bash
python3 -m src.security --help
```

### The Pairing Flow & 6-Digit PIN
To establish permanent cryptographic trust between two machines:

1. **On Computer A**: Export its public certificate:
   ```bash
   python3 -m src.security --export-cert /tmp/compA.crt
   ```
2. **On Computer B**: Trust Computer A's certificate:
   ```bash
   python3 -m src.security --trust-cert "compA_id" "Computer-A" /tmp/compA.crt
   ```
   The terminal will output the mutual **6-digit Short Authentication PIN** (e.g. `342497`).
3. Repeat in reverse so Computer A trusts Computer B. Both machines now verify each other over authenticated mTLS on all future transfers.

### Managing Trusted Peers
```bash
# View your local device's Node ID and SHA-256 fingerprint:
python3 -m src.security --fingerprint

# List all trusted paired computers:
python3 -m src.security --list-trusted

# Revoke trust for a computer:
python3 -m src.security --revoke <node_id>

# Nuclear reset (erases local certificates and all paired peers):
python3 -m src.security --reset-all
```

---

## Throughput Benchmarks

AirDrop includes a built-in benchmark utility (`src/benchmark.py`) to measure raw socket throughput and chunk latency:

```bash
# Run local loopback benchmark matrix:
python3 -m src.benchmark

# Benchmark a remote receiver over the network:
python3 -m src.benchmark --host 192.168.1.50 --port 5001 --size-mib 25
```

### Benchmark Results (Apple Silicon M-Series):
```
+-----------+------------+-----------+--------------+-------------------+-------------------+-----------+
| File Size | Chunk Size | Transport | Duration (s) | Throughput (MB/s) | Throughput (Mbps) | Integrity |
+===========+============+===========+==============+===================+===================+===========+
| 1.00 MiB  | 16.00 KiB  | LOOPBACK  | 0.002        | 504.64            | 4233.2            | PASSED    |
| 1.00 MiB  | 64.00 KiB  | LOOPBACK  | 0.001        | 867.90            | 7280.5            | PASSED    |
| 1.00 MiB  | 256.00 KiB | LOOPBACK  | 0.001        | 1050.51           | 8812.3            | PASSED    |
| 5.00 MiB  | 16.00 KiB  | LOOPBACK  | 0.008        | 655.39            | 5497.8            | PASSED    |
| 5.00 MiB  | 64.00 KiB  | LOOPBACK  | 0.005        | 1098.41           | 9214.1            | PASSED    |
| 5.00 MiB  | 256.00 KiB | LOOPBACK  | 0.004        | 1287.95           | 10804.1           | PASSED    |
| 20.00 MiB | 16.00 KiB  | LOOPBACK  | 0.028        | 711.94            | 5972.2            | PASSED    |
| 20.00 MiB | 64.00 KiB  | LOOPBACK  | 0.023        | 868.46            | 7285.2            | PASSED    |
| 20.00 MiB | 256.00 KiB | LOOPBACK  | 0.021        | 938.93            | 7876.3            | PASSED    |
+-----------+------------+-----------+--------------+-------------------+-------------------+-----------+
```
*(On 802.11ac / 802.11ax direct Wi-Fi links, physical transfer rates typically achieve 40–120+ MB/s depending on radio distance and antenna configuration).*

---

## Troubleshooting & Firewall Setup

### 1. macOS Permissions
- **Local Network Prompt**: On macOS 14 (Sonoma) and macOS 15 (Sequoia), macOS will ask: *"python3 would like to find and connect to devices on your local network"*. Click **Allow**.
- **Bluetooth Permissions**: When running BLE discovery, grant Bluetooth permission under **System Settings > Privacy & Security > Bluetooth** for Terminal / Python.

### 2. Windows Firewall
- Windows Defender Firewall will prompt to allow access on first launch. Check **Private networks**.
- If blocked, add Inbound Rules in Windows Defender Firewall for:
  - **UDP Port 5353** (mDNS Discovery)
  - **TCP Port 5001** (File Transfer)

### 3. Linux Firewall
- If `ufw` is active, allow discovery and transfer ports:
  ```bash
  sudo ufw allow 5353/udp comment "AirDrop mDNS"
  sudo ufw allow 5001/tcp comment "AirDrop Transfer"
  ```

### 4. Wi-Fi Router Settings (AP / Client Isolation)
- Some public, university, or corporate Wi-Fi networks enable **Client Isolation** (or **AP Isolation**), which blocks devices on the same Wi-Fi from talking to each other.
- If devices cannot see each other on public Wi-Fi, use **Routerless Direct Wi-Fi** (Mobile Hotspot) or connect both machines to a personal phone hotspot.

---

## Platform Support Matrix

| Feature | macOS (Darwin 11+) | Linux (Kernel 4.x+) | Windows (10 / 11) | Headless / Docker |
| :--- | :--- | :--- | :--- | :--- |
| **High-Speed TCP Streaming** | Supported | Supported | Supported | Supported |
| **mDNS / DNS-SD Discovery** | Supported (`zeroconf`) | Supported (`zeroconf`) | Supported (`zeroconf`) | Supported (Host Net) |
| **BLE Proximity Discovery** | Supported (CoreBluetooth) | Supported (BlueZ via D-Bus)| Supported (WinRT) | Fallback to mDNS |
| **Routerless Direct Wi-Fi** | Supported (SoftAP / Hotspot) | Supported (Wi-Fi Direct / nmcli)| Supported (Wi-Fi Direct / Hotspot)| Fallback to LAN TCP |
| **Mutual TLS (mTLS) Security** | TLS 1.3/1.2 (`0600` mode) | TLS 1.3/1.2 (`0600` mode) | TLS 1.3/1.2 (NTFS ACLs) | TLS 1.3/1.2 |
| **Desktop Graphical UI** | Native Cocoa Tkinter | X11 / Wayland Tkinter | Native Win32 Tkinter | Headless CLI mode |

---

## Project Architecture & Automated Tests

### Codebase Organization
```
AirDrop/
├── requirements.txt            # zeroconf>=0.136.0, bleak>=3.0.0, cryptography>=41.0.0
├── docs/
│   ├── direct_wifi_research.md # AWDL analysis, platform APIs & Wi-Fi Direct matrix
│   └── threat_model.md         # Risk analysis, trust model, and security architecture
├── src/
│   ├── __init__.py             # Package indicator
│   ├── protocol.py             # Binary framing, JSON encode/decode, custom exceptions
│   ├── file_io.py              # Atomic file writer, chunk streaming, path safety, SHA-256
│   ├── security.py             # X.509 certs, mTLS SSLContexts, trusted peer store, SAS PINs
│   ├── transport.py            # TransportConnection, FailoverTransportClient, DirectWifiManager
│   ├── benchmark.py            # Throughput benchmarking engine across transports and chunk sizes
│   ├── registry.py             # Unified Device Registry, deduplication, DISCOVERED/REACHABLE states
│   ├── ble_discovery.py        # BLE UUID, BleAdvertiser, BleScanner, CoreBluetooth/BlueZ, MockBleBus
│   ├── discovery.py            # Multi-protocol peer browser, mDNS advertiser, interactive picker
│   ├── receiver.py             # TCP receiver, mTLS wrapping, approval gate, concurrency control
│   ├── sender.py               # TCP client, direct transport + fallback, mTLS authentication, SHA-256
│   ├── services.py             # Application services separating UI from networking
│   └── ui.py                   # Desktop GUI with Tkinter/ttk, device radar, progress & ETA
└── tests/
    ├── __init__.py
    ├── test_protocol.py        # Framing, encoding, limits, socket primitives
    ├── test_file_io.py         # Sanitization, path escape protection, atomic commits, disk checks
    ├── test_transfer.py        # End-to-end transfers: empty, small, binary, 5 MiB large, sequential
    ├── test_security_errors.py  # Path traversal, truncated streams, bad headers, disconnects
    ├── test_discovery.py       # mDNS advertisement, peer browser, duplicate names, goodbye events
    ├── test_ble_and_registry.py # BLE parsing, registry deduplication, state transitions, error handling
    ├── test_transport.py       # Direct Wi-Fi, LAN fallback, failover logging, atomic cleanup on drop
    ├── test_security.py        # mTLS transfers, untrusted cert rejection, tampering, approval decline
    └── test_ui.py              # UI widgets, approval modals, progress callbacks, cancellation cleanup
```

---

### Running the Automated Test Suite

AirDrop includes **89 automated unit, integration, and UI tests**:

```bash
cd AirDrop
python3 -m unittest discover -v -s tests
```

All 89 tests execute in under 50 seconds without external network dependencies, verifying:
- Framing protocol, chunking, and header length limits.
- Path traversal rejection (`../../etc/passwd`, Windows drive paths, null bytes).
- 0-byte, small text, arbitrary binary, and multi-megabyte file transfers.
- mDNS service announcements, duplicate hostnames, and goodbye packet removal.
- BLE advertisement parsing, privacy validation, and mock bus simulation.
- Unified registry deduplication merging mDNS and BLE into single devices.
- Direct Wi-Fi connection success, failure diagnostics logging, and transparent LAN TCP fallback.
- Mutual TLS (mTLS) authenticated transfers with strict `0600` file permissions.
- Rejection of untrusted client certificates at the TLS handshake level.
- Recipient consent gate (accept and decline flows).
- In-flight payload bit tampering detection via SHA-256 failure with immediate file unlinking.
- Transfer cancellation with complete temporary `.part` file cleanup.
- Server concurrency limit enforcement.
- Desktop UI widget initialization, device table population, file queuing, and progress bar updates.
