"""Hero images: the builder drops a bad one, accepts a clean one, deploys by sha256.

The WebP files are built by hand, container only. The builder never decodes
pixels, so a container with a valid VP8 keyframe header is exactly what it sees.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

from index_builder.media import (
    MEDIA_SCHEMA, MediaInvalid, attach_media, card_media, check_hero, stage_media,
)
from index_builder.releases import FOLDER_FOR_KIND

ITEM = "adoom666/work"


def _chunk(tag: bytes, body: bytes) -> bytes:
    return tag + struct.pack("<I", len(body)) + body + (b"\0" if len(body) & 1 else b"")


def _webp(w: int = 1536, h: int = 1024, extra: bytes = b"") -> bytes:
    vp8 = b"\x10\x00\x00" + b"\x9d\x01\x2a" + struct.pack("<HH", w, h) + b"\0" * 8
    body = b"WEBP" + _chunk(b"VP8 ", vp8) + extra
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _put(root: Path, data: bytes, **over: object) -> None:
    where = root / "media" / "skills" / "adoom666" / "work"
    where.mkdir(parents=True)
    (where / "hero.webp").write_bytes(data)
    meta = {
        "schema": MEDIA_SCHEMA, "item": ITEM, "source": "generated",
        "sha256": hashlib.sha256(data).hexdigest(), "w": 1536, "h": 1024, "bytes": len(data),
    }
    meta.update(over)
    (where / "media.json").write_text(json.dumps(meta), encoding="utf-8")


def test_a_clean_hero_is_carded_and_staged_by_sha256(tmp_path: Path) -> None:
    data = _webp()
    _put(tmp_path, data)
    block = card_media(tmp_path, "skills", ITEM)
    assert block == {
        "sha256": hashlib.sha256(data).hexdigest(), "w": 1536, "h": 1024,
        "type": "image/webp", "bytes": len(data), "source": "generated",
    }
    items = [{"id": ITEM, "kind": "skill", "card": {"title": "t"}}]
    notes: list[str] = []
    assert attach_media(tmp_path, FOLDER_FOR_KIND, items, notes.append) == 1
    assert items[0]["card"]["media"] == block
    out = tmp_path / "deploy"
    assert stage_media(tmp_path, FOLDER_FOR_KIND, {"items": items}, out) == 1
    assert (out / f"{block['sha256']}.webp").read_bytes() == data


@pytest.mark.parametrize("extra", [b"EXIF", b"XMP ", b"ICCP"])
def test_a_hero_with_a_metadata_chunk_is_refused(extra: bytes) -> None:
    with pytest.raises(MediaInvalid, match="only chunk"):
        check_hero(_webp(extra=_chunk(extra, b"secret!!")))


def test_trailing_bytes_and_a_bad_ratio_are_refused() -> None:
    with pytest.raises(MediaInvalid, match="RIFF size"):
        check_hero(_webp() + b"junk")
    with pytest.raises(MediaInvalid, match="ratio"):
        check_hero(_webp(1024, 1536))


def test_a_sha_mismatch_drops_the_media_but_not_the_item(tmp_path: Path) -> None:
    _put(tmp_path, _webp(), sha256="0" * 64)
    with pytest.raises(MediaInvalid, match="sha256"):
        card_media(tmp_path, "skills", ITEM)
    items = [{"id": ITEM, "kind": "skill", "card": {"title": "t"}}]
    notes: list[str] = []
    assert attach_media(tmp_path, FOLDER_FOR_KIND, items, notes.append) == 0
    assert "media" not in items[0]["card"] and "dropped" in notes[0]


def test_staging_refuses_a_carded_sha_the_file_does_not_match(tmp_path: Path) -> None:
    _put(tmp_path, _webp())
    index = {"items": [{"id": ITEM, "kind": "skill", "card": {"media": {"sha256": "1" * 64}}}]}
    with pytest.raises(MediaInvalid, match="card names"):
        stage_media(tmp_path, FOLDER_FOR_KIND, index, tmp_path / "out")
