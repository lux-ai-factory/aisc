"""Small real images for template logos: a PNG Pillow can open, the head of a JPEG, an SVG of a declared
size. The renderer (report_renderer/style.py logo_problem) refuses a logo it cannot read, so the tests
save logos that are images."""
from __future__ import annotations

import base64
import struct
import zlib


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png(width: int = 1, height: int = 1) -> bytes:
    """A grey PNG of this size (8-bit greyscale, every row filter 0)."""
    rows = (b"\x00" + b"\x80" * width) * height
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(rows, 9)) + _chunk(b"IEND", b""))


def jpeg_head(width: int, height: int) -> bytes:
    """The start of a baseline JPEG up to its frame header (SOF0), which is where its size is."""
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    sof0 = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8" + app0 + sof0 + b"\xff\xd9"


def svg(attributes: str) -> bytes:
    return f'<svg xmlns="http://www.w3.org/2000/svg" {attributes}><rect width="10" height="10"/></svg>'.encode()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


PNG_1x1 = b64(png())
