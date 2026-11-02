# AirDrop — Local File Transfer, LAN Discovery & BLE Proximity

A robust, cross-platform file transfer system with zero-configuration multi-tier discovery (mDNS + Bluetooth Low Energy) built in Python 3.11+.

- **Phase 0**: High-speed, bounded-memory TCP streaming file transfer protocol with atomic file replacement, path traversal protection, pre-flight disk headroom checks, and SHA-256 integrity verification.
- **Phase 1**: Automatic LAN discovery using mDNS/DNS-SD (Multicast DNS Service Discovery) with zero manual IP entry, live status tracking, duplicate name handling, and instant departure detection via goodbye packets.
- **Phase 2**: Bluetooth Low Energy (BLE) peripheral advertising and central scanning, unified multi-protocol device registry, reachability state lifecycle management, and privacy-preserving ephemeral tokens.

---

## Architecture Overview

```
+-------------------------------------------------------------------------+
|                        Unified Device Registry                          |
|  - Deduplication: merges mDNS + BLE beacons via ephemeral node_id       |
|  - Lifecycle States: DISCOVERED -> REACHABLE -> CONNECTED -> UNAVAILABLE |
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
                      +-----------------------------+
                      |     TCP Streaming Engine    |
                      | - Length-prefixed JSON frame|
                      | - 64 KiB bounded chunks     |
                      | - Atomic .part writer       |
                      | - SHA-256 Checksum ACK      |
                      +-----------------------------+
```

---

## Phase 2: BLE Discovery Specification

### 1. Application Service UUID
AirDrop registers an exclusive, standardized 128-bit service identifier:
- **Service UUID**: `f7826da6-4fa2-4e98-8024-bc5b71e0893e`
- **Local Name Prefix**: `AD-<node_id>` (e.g. `AD-a1b2c3d4`)

### 2. Privacy & Ephemeral Identifiers
- **Zero Personal Data**: BLE advertisements strictly broadcast the short, session-scoped `node_id` (4 to 8 bytes hex).
- **No Identifiable Information**: Email addresses, phone numbers, usernames, device hardware serials, and filenames are **never** included in BLE advertisement packets.
- **Session Tokens**: Every time the receiver starts, a fresh, non-deterministic `node_id` is generated.

### 3. Separation of Concerns
- **Discovery Only**: BLE is strictly utilized for proximity awareness and peer discovery.
- **No File Transfer over BLE**: File payloads are **never** transmitted over BLE.
- **Reachability Barrier**: A device discovered *only* via BLE remains in the `DISCOVERED` state. The sender cannot initiate a TCP transfer until the device resolves a valid LAN IP endpoint (transitioning to `REACHABLE`).

### 4. Device State Lifecycle

| State | Description | Can Transfer? |
| :--- | :--- | :--- |
| `DISCOVERED` | Device seen via Bluetooth beacon (has RSSI / proximity), but no IP address is known yet. | **No** (Transfer blocked until endpoint resolved) |
| `REACHABLE` | Resolved IPv4 address and TCP port (via mDNS or hybrid beacon). Ready for connection. | **Yes** |
| `CONNECTED` | Active TCP socket file transfer currently in progress. | In Progress |
| `UNAVAILABLE`| Receiver stopped, mDNS goodbye packet received, or advertisement TTL expired (>30s). | **No** |

---

## Operating System Support & Platform Limitations

| Platform | BLE Scanning | BLE Advertising | Implementation & Requirements |
| :--- | :--- | :--- | :--- |
| **macOS** | Supported | Supported | Scanning via `bleak` (CoreBluetooth). Advertising via native PyObjC `CBPeripheralManager`. Requires Bluetooth permissions in **System Settings > Privacy & Security > Bluetooth**. |
| **Linux** | Supported | Supported | Scanning via `bleak` (BlueZ via D-Bus). Advertising via BlueZ `LEAdvertisingManager1`. User must have permissions for D-Bus / Bluetooth (or run `bluetoothd -E`). |
| **Windows** | Supported | Supported | Scanning and advertising via Windows Runtime (WinRT) Bluetooth APIs (Windows 10 1709+ or Windows 11). |
| **VM / Docker** | Graceful Fallback | Graceful Fallback | Virtual machines and headless containers generally lack physical Bluetooth hardware access. The application automatically detects this, sets status to `UNSUPPORTED`, and operates via mDNS seamlessly. |

---

## Project Structure

```
AirDrop/
├── requirements.txt           # zeroconf>=0.136.0, bleak>=3.0.0
├── src/
│   ├── __init__.py            # Package indicator
│   ├── protocol.py            # Framing, binary encode/decode, custom errors, metrics formatters
│   ├── file_io.py             # Atomic file writer, chunk streamer, path safety, disk checks, SHA-256
│   ├── registry.py            # Unified Device Registry, deduplication, DISCOVERED/REACHABLE states
│   ├── ble_discovery.py       # BLE UUID, BleAdvertiser, BleScanner, CoreBluetooth/BlueZ, MockBleBus
│   ├── discovery.py           # Multi-protocol peer browser, mDNS advertiser, interactive picker
│   ├── receiver.py            # TCP server socket listener, client handler, multi-protocol advertiser
│   └── sender.py              # TCP client, interactive picker, file streamer, SHA-256 verifier
├── tests/
│   ├── __init__.py
│   ├── test_protocol.py       # Framing, encoding, limits, socket primitives
│   ├── test_file_io.py        # Sanitization, path escape protection, atomic commits, disk checks
│   ├── test_transfer.py       # End-to-end transfers: empty, small, binary, 5 MiB large, sequential
│   ├── test_security_errors.py # Path traversal, truncated streams, bad headers, disconnects
│   ├── test_discovery.py      # mDNS advertisement, peer browser, duplicate names, goodbye events
│   └── test_ble_and_registry.py # BLE parsing, registry deduplication, state transitions, error handling
└── README.md
```

---

## Installation

```bash
cd AirDrop
pip install -r requirements.txt
```

---

## Running the Automated Test Suite

Run all 66 unit and integration tests across Phase 0, Phase 1, and Phase 2:

```bash
python3 -m unittest discover -v -s tests
```

Tests cover:
- Protocol framing, 64 KiB chunking, atomic commits, and disk space pre-checks.
- Path traversal rejection (`../../etc/passwd`, Windows drive paths, null bytes).
- 0-byte, small text, arbitrary binary, and 5 MiB large file transfers over loopback.
- mDNS service announcement, duplicate hostnames, and goodbye packet removal.
- BLE advertisement parsing, privacy validation, and mock bus simulation.
- Unified registry merging (mDNS + BLE deduplication into a single device).
- Enforcing that BLE-only `DISCOVERED` devices cannot trigger a TCP transfer without an IP endpoint.
- Handling of Bluetooth disabled, unauthorized/permission denied, and unsupported hardware.

---

## Two-Computer Demonstration (mDNS + BLE)

Connect **Computer A** (Receiver) and **Computer B** (Sender) to the same local Wi-Fi or Ethernet network.

### 1. On Computer A (Receiver)

Start the receiver. By default, it advertises over both mDNS and BLE:

```bash
cd AirDrop
python3 -m src.receiver --name "Studio-Mac" --dest-dir ./received
```

Optional flags:
- `--no-ble`: Disable BLE advertising and broadcast via mDNS only.
- `--no-advertise`: Disable all background advertisements (manual IP transfer only).
- `--single`: Automatically exit after receiving one transfer.

---

### 2. On Computer B (Sender)

#### Option A: Interactive Selection (Unified Table)
Pass the file you want to transfer:

```bash
cd AirDrop
python3 -m src.sender /path/to/project_archive.zip
```

Example output:
```
Scanning for nearby AirDrop devices (2.5s)...

Discovered Devices (mDNS + BLE):
+---+--------------+-----------+-----------+--------------------+----------+----------+
| # | Display Name | State     | Discovery | Endpoint           | Signal   | Node ID  |
+===+==============+===========+===========+====================+==========+==========+
| 1 | Studio-Mac   | REACHABLE | mDNS+BLE  | 192.168.1.45:5001  | -58 dBm  | a8f21c09 |
+---+--------------+-----------+-----------+--------------------+----------+----------+

Connect to 'Studio-Mac' (192.168.1.45:5001)? [Y/n]: y
Target acquired: 'Studio-Mac' (192.168.1.45:5001)
Starting transfer of 'project_archive.zip' (8.40 MiB, 8808038 bytes)...
Waiting for receiver acknowledgment...
Integrity verified: SHA-256 matches receiver (39c81b...)
============================================================
Transfer Succeeded: project_archive.zip
Destination:       192.168.1.45:5001
Bytes transferred: 8.40 MiB (8808038 bytes)
Transfer duration: 0.082 s
Average throughput:102.44 MiB/s (859.35 Mbps)
SHA-256 digest:    39c81b...
============================================================
```

#### Option B: Target by Name Directly
```bash
python3 -m src.sender --to "Studio-Mac" /path/to/project_archive.zip
```

#### Option C: Real-Time Multi-Protocol Peer Monitor
Monitor peers appearing, signaling, and departing over both mDNS and BLE:

```bash
python3 -m src.discovery --watch
```

---

## Troubleshooting & Permissions

1. **Bluetooth Disabled**:
   - If Bluetooth is turned off on macOS or Windows, the application logs a notification and continues operating using mDNS.
   - Turn Bluetooth ON in your operating system settings.
2. **macOS Bluetooth Permissions**:
   - On macOS 14 (Sonoma) and macOS 15 (Sequoia), the terminal executing Python must have permission to access Bluetooth.
   - Go to **System Settings > Privacy & Security > Bluetooth** and ensure your Terminal application (or Python) is toggled **ON**.
3. **Local Network / Firewall**:
   - Allow incoming UDP port `5353` (mDNS) and TCP port `5001` (File Transfer).
   - Ensure "Client / AP Isolation" is turned off on your local Wi-Fi router.
