import struct
from .constants import START1, START2, HEADER_LEN, MAX_PAYLOAD


def encode_frame(payload: bytes) -> bytes:
    length = len(payload)
    header = struct.pack(">BBBB", START1, START2, (length >> 8) & 0xFF, length & 0xFF)
    return header + payload


def decode_frames(buf: bytes) -> tuple:
    payloads = []
    while len(buf) >= HEADER_LEN:
        # Search for start sequence
        idx = buf.find(bytes([START1, START2]))
        if idx == -1:
            buf = b""
            break
        if idx > 0:
            buf = buf[idx:]

        if len(buf) < HEADER_LEN:
            break

        plen = (buf[2] << 8) | buf[3]
        if plen > MAX_PAYLOAD or plen == 0:
            # Invalid frame — skip start bytes and keep searching
            buf = buf[2:]
            continue

        total = HEADER_LEN + plen
        if len(buf) < total:
            break

        payloads.append(bytes(buf[HEADER_LEN:total]))
        buf = buf[total:]

    return payloads, buf
