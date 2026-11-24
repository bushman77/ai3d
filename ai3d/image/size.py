"""Image sizes without third-party libraries (PNG and JPEG headers)."""
from __future__ import annotations

from pathlib import Path
import struct


def image_size(path: Path) -> tuple[int, int] | None:
    """(width, height) of a PNG or JPEG, or None if unknown/unreadable."""
    try:
        data = Path(path).read_bytes()[:65536]
    except OSError:
        return None
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + length
    return None


def edit_dims(reference: tuple[int, int] | None, base: int, multiple: int = 64) -> tuple[int, int]:
    """Output size with the reference's aspect ratio and about base x base pixels.

    Qwen-Image-Edit crops when the output shape differs from the input: a
    tall full-body figure drawn into a square loses the top of the head.
    """
    if not reference or min(reference) <= 0:
        return base, base
    w, h = reference
    scale = (base * base / (w * h)) ** 0.5
    def snap(v):
        return max(multiple, int(round(v * scale / multiple)) * multiple)
    return snap(w), snap(h)
