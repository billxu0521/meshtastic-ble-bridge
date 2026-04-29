import asyncio
import logging

from .framing import encode_frame, decode_frames

log = logging.getLogger(__name__)


class TCPServer:
    def __init__(
        self,
        host: str,
        port: int,
        inbound_queue: asyncio.Queue,
        outbound_queue: asyncio.Queue,
    ):
        self._host = host
        self._port = port
        self._inbound = inbound_queue
        self._outbound = outbound_queue
        self._writers: set = set()
        self._lock = asyncio.Lock()

    async def run(self):
        server = await asyncio.start_server(
            self._handle_client, self._host, self._port
        )
        addr = server.sockets[0].getsockname()
        log.info(f"TCP server listening on {addr[0]}:{addr[1]}")

        async with server:
            await asyncio.gather(
                server.serve_forever(),
                self._broadcast_loop(),
            )

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ):
        addr = writer.get_extra_info("peername")
        log.info(f"TCP client connected: {addr}")
        async with self._lock:
            self._writers.add(writer)

        rx_buf = b""
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                rx_buf += chunk
                payloads, rx_buf = decode_frames(rx_buf)
                for payload in payloads:
                    log.info(f"TCP→BLE: {len(payload)} bytes")
                    try:
                        self._outbound.put_nowait(payload)
                    except asyncio.QueueFull:
                        log.warning("Outbound queue full — dropping TCP->BLE frame")
        except (ConnectionResetError, asyncio.IncompleteReadError, OSError):
            pass
        finally:
            async with self._lock:
                self._writers.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            log.info(f"TCP client disconnected: {addr}")

    async def _broadcast_loop(self):
        while True:
            payload = await self._inbound.get()
            frame = encode_frame(payload)
            async with self._lock:
                dead = set()
                for writer in self._writers:
                    try:
                        writer.write(frame)
                        await writer.drain()
                    except (ConnectionResetError, BrokenPipeError, OSError):
                        dead.add(writer)
                self._writers -= dead
