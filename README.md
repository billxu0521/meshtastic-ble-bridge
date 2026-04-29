# meshtastic-ble-bridge

A Bluetooth Low Energy → TCP bridge that lets your Mac connect directly to a Meshtastic device over BLE, then exposes it as a local TCP server so tools like [meshmonitor](https://github.com/Yeraze/meshmonitor) can connect without needing Wi-Fi or a phone hotspot.

```
meshmonitor / any TCP client
        ↕  TCP  127.0.0.1:4403
  meshtastic-ble-bridge
        ↕  BLE  (CoreBluetooth)
    Meshtastic device
```

## Why does this exist?

Meshtastic tools (meshmonitor, meshtastic-web) connect via TCP/Wi-Fi. macOS has no official Meshtastic desktop app, and WebBluetooth is blocked by Apple. This bridge translates between BLE GATT characteristics and the standard Meshtastic TCP stream protocol so both sides speak their native language.

## Requirements

- macOS 12 or later
- [uv](https://github.com/astral-sh/uv) (`brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh | sh`)
- A Meshtastic device with Bluetooth enabled

## Installation

```bash
git clone https://github.com/<your-username>/meshtastic-ble-bridge
cd meshtastic-ble-bridge
uv sync
```

macOS will prompt for Bluetooth permission on first run — click **Allow**.

## Usage

### 1. Find your device

```bash
uv run ble_tcp_bridge.py scan
```

```
Found 1 Meshtastic device(s):

  Name   : Meshtastic_A1B2
  Address: 12345678-ABCD-1234-EFGH-ABCDEFGH1234
```

### 2. Start the bridge

```bash
uv run ble_tcp_bridge.py connect --device Meshtastic_A1B2
```

```
13:05:01 [INFO] Scanning for device: Meshtastic_A1B2
13:05:03 [INFO] Connecting to Meshtastic_A1B2 (12345678-ABCD-...)
13:05:04 [INFO] BLE connected.
13:05:04 [INFO] TCP server listening on 127.0.0.1:4403
```

### 3. Connect meshmonitor

Point meshmonitor (or any Meshtastic TCP client) to `127.0.0.1:4403`.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--device` | *(required)* | BLE device name or macOS CoreBluetooth UUID |
| `--host` | `127.0.0.1` | TCP bind address |
| `--port` | `4403` | TCP port |
| `--reconnect-delay` | `5` | Seconds between BLE reconnect attempts |
| `--verbose` | off | Enable DEBUG logging |

## How it works

Meshtastic devices expose three BLE GATT characteristics:

| Characteristic | UUID | Direction |
|---|---|---|
| TORADIO | `f75c76d2-…` | Mac → Device (send commands) |
| FROMRADIO | `2c55e69e-…` | Device → Mac (receive data) |
| FROMNUM | `ed9da18c-…` | Device → Mac (notification: new data ready) |

All messages use the same 4-byte framing on both BLE and TCP:

```
[0x94] [0xC3] [len_high] [len_low] [protobuf payload...]
```

The bridge:
1. Subscribes to **FROMNUM** notifications to know when data is ready
2. Reads **FROMRADIO** in a drain loop until empty (with 0.5 s polling fallback — macOS CoreBluetooth occasionally drops notifications)
3. Wraps raw BLE payloads in stream framing and forwards to all TCP clients
4. Strips framing from TCP client data before writing raw protobufs to **TORADIO**

## Project structure

```
meshtastic-ble-bridge/
├── ble_tcp_bridge.py   # CLI entry point
├── bridge/
│   ├── constants.py    # BLE UUIDs and defaults
│   ├── framing.py      # Frame encode / decode
│   ├── ble_handler.py  # BLE connection and read/write loops
│   └── tcp_server.py   # asyncio TCP server with multi-client broadcast
├── pyproject.toml
└── uv.lock
```

## Troubleshooting

**Device not found during scan**
Ensure the Meshtastic device has Bluetooth enabled and is not already connected to a phone. On macOS the address shown is a CoreBluetooth UUID, not a MAC address — this is normal.

**meshmonitor shows "Connection Error"**
Wait a few seconds after starting the bridge before connecting meshmonitor; the BLE handshake needs to complete first.

**Bridge disconnects frequently**
Move the Mac closer to the device, or increase `--reconnect-delay` to reduce reconnect storms.

## License

MIT
