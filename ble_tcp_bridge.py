#!/usr/bin/env python3
"""Meshtastic BLE-to-TCP bridge — connects a Meshtastic device via BLE and
exposes it as a TCP server so tools like meshmonitor can connect locally."""

import argparse
import asyncio
import logging
import signal
import sys

from bridge.ble_handler import BLEHandler, scan_devices
from bridge.tcp_server import TCPServer
from bridge.constants import DEFAULT_HOST, DEFAULT_PORT, BLE_RECONNECT_DELAY


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


async def cmd_scan(args):
    _setup_logging(getattr(args, "verbose", False))
    devices = await scan_devices(timeout=args.timeout)
    if not devices:
        print("No Meshtastic devices found.")
        return
    print(f"Found {len(devices)} Meshtastic device(s):\n")
    for d in devices:
        print(f"  Name   : {d.name or '(unknown)'}")
        print(f"  Address: {d.address}")
        print()


async def cmd_connect(args):
    _setup_logging(args.verbose)
    log = logging.getLogger("bridge")

    ble_to_tcp: asyncio.Queue = asyncio.Queue(maxsize=64)
    tcp_to_ble: asyncio.Queue = asyncio.Queue(maxsize=64)

    ble = BLEHandler(
        device_identifier=args.device,
        outbound_queue=tcp_to_ble,
        inbound_queue=ble_to_tcp,
        reconnect_delay=args.reconnect_delay,
    )
    tcp = TCPServer(
        host=args.host,
        port=args.port,
        inbound_queue=ble_to_tcp,
        outbound_queue=tcp_to_ble,
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    ble_task = asyncio.ensure_future(ble.run())
    tcp_task = asyncio.ensure_future(tcp.run())

    log.info(f"Bridge starting — BLE device: {args.device}")
    log.info(f"meshmonitor can connect to {args.host}:{args.port}")
    log.info("Press Ctrl-C to stop.")

    await stop_event.wait()
    log.info("Shutting down...")

    ble_task.cancel()
    tcp_task.cancel()
    await asyncio.gather(ble_task, tcp_task, return_exceptions=True)
    log.info("Stopped.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ble_tcp_bridge",
        description="Bridge a Meshtastic BLE device to a local TCP port.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- scan ---
    p_scan = sub.add_parser("scan", help="Scan for nearby Meshtastic BLE devices")
    p_scan.add_argument(
        "--timeout", type=float, default=10.0,
        help="Scan duration in seconds (default: 10)",
    )
    p_scan.add_argument("--verbose", action="store_true")

    # --- connect ---
    p_conn = sub.add_parser("connect", help="Start the BLE-to-TCP bridge")
    p_conn.add_argument(
        "--device", required=True,
        help="BLE device name (e.g. Meshtastic_1234) or macOS CoreBluetooth UUID",
    )
    p_conn.add_argument(
        "--host", default=DEFAULT_HOST,
        help=f"TCP bind address (default: {DEFAULT_HOST})",
    )
    p_conn.add_argument(
        "--port", type=int, default=DEFAULT_PORT,
        help=f"TCP port (default: {DEFAULT_PORT})",
    )
    p_conn.add_argument(
        "--reconnect-delay", type=float, default=BLE_RECONNECT_DELAY,
        dest="reconnect_delay",
        help=f"Seconds between BLE reconnect attempts (default: {BLE_RECONNECT_DELAY})",
    )
    p_conn.add_argument("--verbose", action="store_true", help="Enable debug logging")

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "scan":
            asyncio.run(cmd_scan(args))
        elif args.command == "connect":
            asyncio.run(cmd_connect(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
