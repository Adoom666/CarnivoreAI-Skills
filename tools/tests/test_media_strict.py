"""The builder takes only the generator's exact shape: one lossy VP8 chunk, nothing else."""

from __future__ import annotations

import struct

import pytest

from index_builder.media import MediaInvalid, check_hero


def ch(t: bytes, b: bytes) -> bytes:
    return t + struct.pack("<I", len(b)) + b + (b"\0" if len(b) & 1 else b"")


def riff(*chunks: bytes) -> bytes:
    body = b"WEBP" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def vp8l(w: int, h: int, pay: bytes = b"\0" * 8) -> bytes:
    return ch(b"VP8L", b"\x2f" + struct.pack("<I", (w - 1) | ((h - 1) << 14)) + pay)


def vp8x(w: int, h: int, flags: int = 0) -> bytes:
    return ch(b"VP8X", bytes([flags, 0, 0, 0]) + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little"))


def vp8(w: int, h: int, pay: bytes = b"\0" * 8, frame: bytes = b"\x10\x00\x00") -> bytes:
    return ch(b"VP8 ", frame + b"\x9d\x01\x2a" + struct.pack("<HH", w, h) + pay)


def test_a_generator_shaped_image_passes() -> None:
    assert check_hero(riff(vp8(1536, 1024, b"\x55" * 4001))) == (1536, 1024)


CRAFTED = {
    "oversize frame inside a small canvas": riff(vp8x(1536, 1024), vp8l(16384, 16384)),
    "two frames": riff(vp8(1536, 1024), vp8(16384, 16383)),
    "payload after the image data": riff(vp8(1536, 1024), ch(b"JUNK", b"<script>")),
    "garbage vp8 data": riff(vp8(1536, 1024, b"\xff" * 4000, frame=b"\x01\x00\x00")),
    "extended format": riff(vp8x(1536, 1024), vp8(1536, 1024)),
    "lossless": riff(vp8l(1536, 1024)),
    "alph without vp8x": riff(ch(b"ALPH", b"\0" * 4), vp8(1536, 1024)),
    "vp8 scaling bits": riff(vp8(1536 | 0x4000, 1024)),
}


@pytest.mark.parametrize("name", list(CRAFTED))
def test_crafted_files_are_refused(name: str) -> None:
    with pytest.raises(MediaInvalid):
        check_hero(CRAFTED[name])
