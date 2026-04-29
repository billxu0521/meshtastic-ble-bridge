import asyncio
import logging

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .constants import (
    SERVICE_UUID, TORADIO_UUID, FROMRADIO_UUID, FROMNUM_UUID,
    BLE_RECONNECT_DELAY, DEFAULT_SCAN_TIMEOUT,
)

log = logging.getLogger(__name__)


async def scan_devices(timeout: float = DEFAULT_SCAN_TIMEOUT):
    log.info(f"Scanning for Meshtastic BLE devices ({timeout:.0f}s)...")
    devices = await BleakScanner.discover(
        timeout=timeout,
        service_uuids=[SERVICE_UUID],
    )
    return devices


class BLEHandler:
    def __init__(
        self,
        device_identifier: str,
        outbound_queue: asyncio.Queue,
        inbound_queue: asyncio.Queue,
        reconnect_delay: float = BLE_RECONNECT_DELAY,
    ):
        self._identifier = device_identifier
        self._outbound = outbound_queue
        self._inbound = inbound_queue
        self._reconnect_delay = reconnect_delay
        self._want_exit = False
        self._fromnum_event: asyncio.Event = asyncio.Event()
        self._inner_tasks = []

    async def run(self):
        try:
            await self._connect_loop()
        except asyncio.CancelledError:
            self._want_exit = True
            raise

    async def _connect_loop(self):
        while not self._want_exit:
            try:
                device = await self._scan_for_device()
                log.info(f"Connecting to {device.name} ({device.address})")
                async with BleakClient(
                    device,
                    disconnected_callback=self._on_disconnect,
                ) as client:
                    log.info("BLE connected.")
                    self._fromnum_event.clear()
                    await client.start_notify(FROMNUM_UUID, self._fromnum_callback)

                    reader = asyncio.ensure_future(self._reader_loop(client))
                    writer = asyncio.ensure_future(self._writer_loop(client))
                    self._inner_tasks = [reader, writer]

                    done, pending = await asyncio.wait(
                        [reader, writer],
                        return_when=asyncio.FIRST_EXCEPTION,
                    )
                    for t in pending:
                        t.cancel()
                        try:
                            await t
                        except (asyncio.CancelledError, Exception):
                            pass
                    for t in done:
                        exc = t.exception()
                        if exc:
                            log.warning(f"BLE task error: {exc}")

            except asyncio.CancelledError:
                return
            except (BleakError, OSError, Exception) as e:
                log.warning(f"BLE error: {e}")

            if not self._want_exit:
                log.info(f"Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)

    def _fromnum_callback(self, sender, data: bytearray):
        log.info(f"FROMNUM notification: {int.from_bytes(bytes(data), 'little')}")
        self._fromnum_event.set()

    def _on_disconnect(self, client: BleakClient):
        log.warning("BLE device disconnected.")
        for t in self._inner_tasks:
            t.cancel()

    async def _reader_loop(self, client: BleakClient):
        while True:
            # Wait for FROMNUM notification; poll every 0.5s as fallback in case
            # CoreBluetooth misses a notification (observed with some firmware versions).
            try:
                await asyncio.wait_for(self._fromnum_event.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
            self._fromnum_event.clear()

            # Drain FROMRADIO until empty
            while True:
                data = bytes(await client.read_gatt_char(FROMRADIO_UUID))
                if not data:
                    break
                log.info(f"BLE→TCP: {len(data)} bytes")
                await self._inbound.put(data)

    async def _writer_loop(self, client: BleakClient):
        while True:
            payload = await self._outbound.get()
            log.info(f"TCP→BLE write: {len(payload)} bytes → TORADIO")
            try:
                await client.write_gatt_char(TORADIO_UUID, payload, response=True)
            except (BleakError, OSError) as e:
                log.error(f"TORADIO write failed: {e}")
                raise
            await asyncio.sleep(0.01)

    async def _scan_for_device(self) -> BLEDevice:
        identifier = self._identifier
        log.info(f"Scanning for device: {identifier}")

        def match(device: BLEDevice, _adv) -> bool:
            return identifier in (device.name or "", device.address)

        try:
            device = await BleakScanner.find_device_by_filter(
                match,
                timeout=DEFAULT_SCAN_TIMEOUT,
                service_uuids=[SERVICE_UUID],
            )
        except Exception as e:
            raise BleakError(f"Scan failed: {e}") from e

        if device is None:
            raise BleakError(f"Device '{identifier}' not found within scan timeout.")
        return device
