"""A hero image beside the item it illustrates, and what it takes to publish one.

WHY THIS EXISTS. A catalog card has only ever had a glyph. Each item can now
carry one landscape hero image, made by the publisher's generator or uploaded
by the author, that the app draws as the card band and the detail banner. The
image is cosmetic: it is never part of install consent and never installed.

WHERE IT LIVES: ``media/<folder>/<handle>/<name>/hero.webp`` plus a sibling
``media.json``, a tree of its own OUTSIDE the digested item folder. That is on
purpose. The folder digest and the signed release statement stay untouched,
nothing image shaped is copied into ``~/.claude/skills``, and replacing a
picture needs no version bump. ``<folder>`` is the item's kind folder
(``skills``, ``themes``, ``plugins``, ``loadouts``), the same one releases use.

WHAT THE INDEX CARRIES: ``card.media = {sha256, w, h, type, bytes, source}``.
A SHA-256 and never a URL. The app derives where to fetch from the host that
served the index, so a signed index can never aim the app at another host.
The index key signs it with the rest of the card.

WHAT THE BUILD REFUSES. Every file is checked here, in the job that has no
secrets, and an image that fails is DROPPED from its card with a notice while
the item still publishes: a cosmetic problem must never block a release, and
must never put bytes in the index that nothing stands behind. Checked: the
RIFF/WEBP envelope with a size that matches the file, only the chunks that
paint pixels (no EXIF, XMP, ICC or animation), real dimensions inside the
window, a byte cap, and a ``media.json`` whose sha256, size, dimensions and
item id all match the bytes. Shipped bytes are the publisher tool's own
encoder output; this check is the second lock on that door, so it reads the
container itself and trusts no field a file declares about itself.

THIS READER USES NO IMAGE LIBRARY. A codec is the attack surface of this class
of bug; the builder only needs the container, the chunk list and the canvas
size, all of which are a few fixed bytes.
"""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

#: Where media lives, a sibling of ``releases/`` and ``reviews/``.
MEDIA_DIR = "media"

#: The one image per item, and its record.
HERO_FILE = "hero.webp"
META_FILE = "media.json"

#: The record's schema tag.
MEDIA_SCHEMA = "carnivore.catalog.media/1"

#: The only two origins an image can have.
SOURCES = ("generated", "author")

#: The only type the index names.
MEDIA_TYPE = "image/webp"

#: A hero is at most this many bytes. The publisher tool encodes to 300 KiB
#: or less; this is the hard ceiling for an author's replacement.
MAX_BYTES = 512 * 1024

#: Pixel window. The master is 1536x1024 and cards crop it with
#: ``object-fit: cover``, so any landscape ratio in this window draws.
MIN_SIDE = 480
MAX_SIDE = 4096
MIN_RATIO = 1.2
MAX_RATIO = 3.2

#: Chunks that paint pixels. Everything else (EXIF, XMP, ICCP, ANIM, ANMF and
#: anything unknown) refuses the file.
_PIXEL_CHUNKS = (b"VP8 ", b"VP8L", b"VP8X", b"ALPH")

#: VP8X flag bits that declare ICC, EXIF, XMP or animation.
_VP8X_REFUSED_FLAGS = 0x20 | 0x08 | 0x04 | 0x02


class MediaInvalid(Exception):
    """An image or its record failed a check, carrying why for the job log."""


def media_dir(root: Path, folder: str, item_id: str) -> Path:
    """Where one item's hero and record sit.

    :param root: the repository root.
    :param folder: the item's kind folder, e.g. ``skills``.
    :param item_id: ``handle/name``.
    :returns: the directory (it may not exist).
    :raises MediaInvalid: when the id is not exactly two safe components.

    Example: media_dir(Path("."), "skills", "a/b") -> Path("media/skills/a/b")
    """
    parts = item_id.split("/")
    if len(parts) != 2 or any(
        not p or p in (".", "..") or "\\" in p for p in parts
    ):
        raise MediaInvalid(f"item id {item_id!r} is not handle/name")
    return root / MEDIA_DIR / folder / parts[0] / parts[1]


def webp_size(data: bytes) -> Tuple[int, int]:
    """Read a WebP's pixel size, refusing anything but a plain still image.

    :param data: the whole file.
    :returns: (width, height).
    :raises MediaInvalid: on a bad envelope, a size mismatch, a metadata or
        animation chunk, an unknown chunk, or dimensions it cannot read.

    Example: webp_size(open("hero.webp", "rb").read()) -> (1536, 1024)
    """
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise MediaInvalid("not a RIFF/WEBP file")
    if struct.unpack("<I", data[4:8])[0] != len(data) - 8:
        raise MediaInvalid("the RIFF size does not match the file, so bytes are appended or cut")
    pos = 12
    size: Optional[Tuple[int, int]] = None
    seen_pixels = False
    while pos < len(data):
        if pos + 8 > len(data):
            raise MediaInvalid("a chunk header runs past the end of the file")
        tag = data[pos:pos + 4]
        length = struct.unpack("<I", data[pos + 4:pos + 8])[0]
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length:
            raise MediaInvalid(f"chunk {tag!r} runs past the end of the file")
        if tag not in _PIXEL_CHUNKS:
            raise MediaInvalid(
                f"chunk {tag!r} is not allowed (no EXIF, XMP, ICC, animation or unknown chunks)")
        if tag == b"VP8X":
            if length != 10 or pos != 12:
                raise MediaInvalid("malformed VP8X chunk")
            if body[0] & _VP8X_REFUSED_FLAGS:
                raise MediaInvalid("VP8X declares metadata or animation")
            size = (
                int.from_bytes(body[4:7], "little") + 1,
                int.from_bytes(body[7:10], "little") + 1,
            )
        elif tag == b"VP8 ":
            if length < 10 or body[3:6] != b"\x9d\x01\x2a":
                raise MediaInvalid("malformed VP8 frame header")
            w, h = struct.unpack("<HH", body[6:10])
            if size is None:
                size = (w & 0x3FFF, h & 0x3FFF)
            seen_pixels = True
        elif tag == b"VP8L":
            if length < 5 or body[0] != 0x2F:
                raise MediaInvalid("malformed VP8L header")
            bits = struct.unpack("<I", body[1:5])[0]
            if size is None:
                size = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            seen_pixels = True
        pos += 8 + length + (length & 1)
    if pos != len(data) or not seen_pixels or size is None:
        raise MediaInvalid("no image data, or trailing bytes after the last chunk")
    return size


def check_hero(data: bytes) -> Tuple[int, int]:
    """Hold hero bytes to the cap, the container rules and the pixel window.

    :param data: the whole file.
    :returns: (width, height).
    :raises MediaInvalid: on any failure.

    Example: check_hero(good_bytes) -> (1536, 1024)
    """
    if len(data) > MAX_BYTES:
        raise MediaInvalid(f"{len(data)} bytes is over the {MAX_BYTES} byte cap")
    w, h = webp_size(data)
    if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE:
        raise MediaInvalid(f"{w}x{h} is outside the {MIN_SIDE} to {MAX_SIDE} pixel window")
    if not MIN_RATIO <= w / h <= MAX_RATIO:
        raise MediaInvalid(f"{w}x{h} is not a landscape ratio between {MIN_RATIO} and {MAX_RATIO}")
    return w, h


def card_media(root: Path, folder: str, item_id: str) -> Optional[Dict[str, object]]:
    """Prove one item's media and return its ``card.media`` block.

    :param root: the repository root.
    :param folder: the item's kind folder.
    :param item_id: ``handle/name``.
    :returns: the block, or None when the item has no media directory.
    :raises MediaInvalid: when media exists but any check fails.

    Example: card_media(root, "skills", "a/b")["sha256"] -> "9f..."
    """
    where = media_dir(root, folder, item_id)
    if not where.is_dir():
        return None
    hero, meta_path = where / HERO_FILE, where / META_FILE
    if not hero.is_file() or hero.is_symlink() or not meta_path.is_file():
        raise MediaInvalid(f"{where} needs a regular {HERO_FILE} and {META_FILE}")
    data = hero.read_bytes()
    w, h = check_hero(data)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MediaInvalid(f"{META_FILE} is unreadable: {exc}") from exc
    if not isinstance(meta, dict) or meta.get("schema") != MEDIA_SCHEMA:
        raise MediaInvalid(f"{META_FILE} schema is not {MEDIA_SCHEMA}")
    if meta.get("item") != item_id:
        raise MediaInvalid(f"{META_FILE} names {meta.get('item')!r}, not {item_id!r}")
    if meta.get("source") not in SOURCES:
        raise MediaInvalid(f"{META_FILE} source must be one of {SOURCES}")
    digest = hashlib.sha256(data).hexdigest()
    for key, actual in (("sha256", digest), ("w", w), ("h", h), ("bytes", len(data))):
        if meta.get(key) != actual:
            raise MediaInvalid(f"{META_FILE} {key} is {meta.get(key)!r} but the file is {actual!r}")
    return {
        "sha256": digest, "w": w, "h": h, "type": MEDIA_TYPE,
        "bytes": len(data), "source": meta["source"],
    }


def attach_media(
    root: Path,
    folder_for_kind: Dict[str, str],
    items: List[Dict[str, object]],
    notice: Callable[[str], None],
) -> int:
    """Put ``card.media`` on every item that has proven media.

    :param root: the repository root.
    :param folder_for_kind: kind -> kind folder.
    :param items: the index's items, edited in place.
    :param notice: called with a line for an item whose media was dropped or
        missing; media must never block a release, so nothing raises.
    :returns: how many items got media.

    Example: attach_media(root, FOLDER_FOR_KIND, items, print) -> 7
    """
    attached, missing = 0, []
    for item in items:
        item_id, folder = str(item["id"]), folder_for_kind.get(str(item.get("kind")))
        if folder is None:
            continue
        try:
            block = card_media(root, folder, item_id)
        except MediaInvalid as exc:
            notice(f"media dropped for {item_id}, it publishes without an image: {exc}")
            continue
        if block is None:
            missing.append(item_id)
            continue
        item["card"]["media"] = block  # type: ignore[index]
        attached += 1
    if missing:
        notice(f"{len(missing)} item(s) have no media: {', '.join(missing)}")
    return attached


def stage_media(
    root: Path, folder_for_kind: Dict[str, str], index: Dict[str, object], out: Path,
) -> int:
    """Copy each carded image to ``<out>/<sha256>.webp`` for deployment.

    :param root: the repository root.
    :param folder_for_kind: kind -> kind folder.
    :param index: the (signed) index document.
    :param out: the directory to fill, normally ``deploy/v1/media``.
    :returns: how many files were staged.
    :raises MediaInvalid: when a card names media whose bytes are missing or
        do not hash to the named sha256, because a dangling sha would be
        signed and deployed with nothing behind it.

    Example: stage_media(root, FOLDER_FOR_KIND, doc, Path("deploy/v1/media")) -> 7
    """
    count = 0
    for item in index.get("items", []):  # type: ignore[union-attr]
        block = item.get("card", {}).get("media")
        if not block:
            continue
        folder = folder_for_kind.get(str(item.get("kind")))
        if folder is None:
            raise MediaInvalid(f"{item.get('id')} has media but an unknown kind")
        try:
            data = (media_dir(root, folder, str(item["id"])) / HERO_FILE).read_bytes()
        except OSError as exc:
            raise MediaInvalid(f"{item.get('id')} names media but its file is unreadable: {exc}") from exc
        check_hero(data)
        digest = hashlib.sha256(data).hexdigest()
        if digest != block.get("sha256"):
            raise MediaInvalid(f"{item['id']} card names {block.get('sha256')} but the file is {digest}")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{digest}.webp").write_bytes(data)
        count += 1
    return count
