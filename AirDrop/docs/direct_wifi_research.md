# Direct Wi-Fi Transport: Platform Research & Architecture

## 1. Objective
Investigate and document the supported direct-connect (peer-to-peer / routerless) APIs across target operating systems (macOS, Linux, Windows), evaluate Apple AWDL accessibility, establish an abstracted transport architecture separating connection establishment from data transmission, and provide seamless fallback to LAN TCP.

---

## 2. Platform Analysis & API Availability

### 2.1 macOS (Darwin)
- **Apple Wireless Direct Link (AWDL)**:
  - **What it is**: Apple's proprietary link-layer protocol operating on the `awdl0` virtual interface. It powers native Apple AirDrop, AirPlay, and Sidecar.
  - **Public API Status**: **NO PUBLIC API EXISTS**.
  - **Why third-party apps cannot use AWDL directly**:
    - The interfaces, daemons (`sharingd`, `wifip2pd`, `airdropd`), and frameworks (`Apple80211.framework`, `WiFiP2P.framework`) are private to Apple.
    - Using them requires private entitlements (`com.apple.private.network.wifi-p2p`, `com.apple.sharing.airdrop`) signed by Apple, unavailable to third-party developers.
    - While projects like OpenDrop / OWL reverse-engineered AWDL frame exchange, they require custom Linux Wi-Fi dongles capable of raw 802.11 frame injection and active channel-hopping synchronization. On macOS, raw link-layer injection on `awdl0` is strictly restricted by the kernel.
  - **Officially Supported Public Alternative on macOS**:
    - **Wi-Fi SoftAP / Local Hotspot (Routerless Direct Link)**:
      - macOS allows creating a direct Wi-Fi Access Point (SoftAP) directly from the Wi-Fi card without an infrastructure router (System Settings > General > Sharing > Internet Sharing, or via `networksetup`).
      - Once the peer connects directly to this SSID, a direct point-to-point Wi-Fi connection is formed (typically on `192.168.2.x` or IPv6 Link-Local `fe80::...%en0`).
      - Transfers achieve raw 802.11ac / 802.11ax physical speeds (hundreds of Mbps to over 1 Gbps) with zero dependency on an external router.

### 2.2 Linux
- **Wi-Fi Direct (Wi-Fi P2P)**:
  - **Public API Status**: **OFFICIALLY SUPPORTED**.
  - **Implementation**:
    - Supported by `wpa_supplicant` via the P2P management interface and by NetworkManager (`nmcli`).
    - Standard operations:
      - Autonomous Group Owner creation: `wpa_cli -i wlan0 p2p_group_add`
      - NetworkManager one-command Hotspot: `nmcli dev wifi hotspot ifname wlan0 ssid AirDropDirect password <passphrase>`
  - **Hardware Requirements**:
    - Wi-Fi driver supporting P2P or AP mode (verify via `iw list | grep -E "P2P|AP"`).
    - Elevated privileges (`sudo` or polkit authorization) to interact with NetworkManager / `wpa_supplicant`.

### 2.3 Windows
- **Wi-Fi Direct**:
  - **Public API Status**: **OFFICIALLY SUPPORTED**.
  - **Implementation**:
    - Supported in Windows 10 (version 1709+) and Windows 11 via the Windows Runtime (WinRT) namespace `Windows.Devices.WiFiDirect`.
    - Key classes: `WiFiDirectAdvertisementPublisher`, `WiFiDirectConnectionListener`, `WiFiDirectDevice`.
    - Also supports Mobile Hotspot / Hosted Network via `netsh wlan` or `Windows.Networking.NetworkOperators.NetworkOperatorTetheringManager`.
  - **Hardware Requirements**:
    - Wi-Fi adapter driver with NDIS 6.30+ Wi-Fi Direct support (`netsh wlan show drivers` -> `Wi-Fi Direct Supported: Yes`).

---

## 3. Compatibility Matrix

| Platform | Direct Mechanism | API Status | Routerless? | Setup / Permission Requirements | Fallback Behavior |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **macOS (11.0+)** | Wi-Fi SoftAP / Local Hotspot | Public (`networksetup`, System Settings) | **Yes** | Manual or helper SSID creation; Wi-Fi interface enabled | Automatic LAN TCP fallback if not connected |
| **Linux (Kernel 4.x+)** | Wi-Fi Direct P2P / SoftAP | Public (`wpa_supplicant`, `nmcli`) | **Yes** | Wi-Fi adapter with P2P/AP mode; `sudo` or polkit rights | Automatic LAN TCP fallback if P2P unavailable |
| **Windows (10/11)** | Wi-Fi Direct / Mobile Hotspot | Public (WinRT `WiFiDirect`) | **Yes** | NDIS 6.30+ Wi-Fi adapter; Windows Bluetooth/Wi-Fi toggle ON | Automatic LAN TCP fallback if Direct fails |
| **VM / Headless / Cloud** | None (No physical Wi-Fi radio) | N/A | No | No physical wireless interface | **Immediate automatic fallback to LAN TCP** |

---

## 4. Transport Abstraction Design

### 4.1 Separation of Concerns
1. **Connection Establishment (`TransportClient` / `TransportServer`)**:
   - Handles physical/network routing, interface selection, socket binding, handshakes, timeouts, and failover logic.
2. **Data Streaming (`Protocol` + `FileIO`)**:
   - Agnostic to transport mechanism. Once a `TransportConnection` is active, it runs identical 4-byte prefixed JSON framing, 64 KiB chunk streaming, and SHA-256 integrity verification.

### 4.2 Failover Policy
```
+-------------------------------------------------------------------+
|               Sender Initiates Transfer                           |
+---------------------------------+---------------------------------+
                                  |
               Attempt Direct Wi-Fi Connection
               (e.g., direct SSID IP 192.168.2.1:5001)
                                  |
             +--------------------+--------------------+
             |                                         |
         [Success]                                  [Failed]
             |                                         |
             v                                         v
   Transport: DIRECT_WIFI                   Log exact reason:
   Proceed with File Stream                 - ConnectionRefusedError
                                            - Timeout / Route unreachable
                                            - Interface down
                                                       |
                                                       v
                                            Attempt Fallback: LAN TCP
                                            (e.g., LAN IP 192.168.1.50:5001)
                                                       |
                                           +-----------+-----------+
                                           |                       |
                                       [Success]               [Failed]
                                           |                       |
                                           v                       v
                                  Transport: LAN_TCP       Raise AirDropError
                                  Proceed with Stream      Transfer Aborted
```

### 4.3 Atomic Integrity Guarantee
- If a direct Wi-Fi link drops mid-stream (e.g. peer walks out of range or disconnects):
  1. The socket emits `ConnectionClosedError` or timeout.
  2. `AtomicFileWriter` detects incomplete byte count.
  3. Temporary `.part` file is unlinked immediately.
  4. Incomplete/corrupted files are **never** committed or marked successful.
