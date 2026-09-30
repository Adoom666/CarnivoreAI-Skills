"""Validation of a submitted theme folder: theme.json plus raster images.

A THEME IS DATA, NEVER CODE. The folder holds one ``theme.json`` and
raster images at the root, nothing else. No script, no stylesheet, no svg
and no html can be published (the 2026-09-22 ban on ``effects.js``), so
the only way a theme reaches the screen is through values the app itself
applies as custom properties and terminal colours. Those values are held
to a conservative character rule here because a submitted string is
attacker controlled text that ends up inside a stylesheet.

Images are checked by extension AND by magic bytes, and their pixel
dimensions are read from the header so a tiny lossless file cannot expand
to a huge bitmap in the viewer. Nothing is decoded.

MEASURED 2026-09-30 against the 41 bundled themes: the largest background
is 465 KiB at 1254 x 1254 (webp), every preview is 240 x 240, the largest
theme.json is 4.3 KiB and uses 77 distinct cssVars keys. The caps in
``kind_rules`` (512 KiB per image, 1 MiB total) fit every real theme.

Pure over plain values. THIS IS A PORT of ``hosted/catalog/api/validate_theme.py`` in the
product repository, held to it by ``tests/fixtures/kind_vectors.json``, which
both repositories run and pin by sha256.
"""

from __future__ import annotations

import json
import re
import struct
from typing import Any, Dict, Optional, Tuple

from .kind_errors import MAX_DESCRIPTION_CHARS, KindRefused

MANIFEST = "theme.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 8_000_000

#: Extensions that would carry code or markup: 409 scripts_not_supported.
SCRIPT_EXTENSIONS = (".js", ".mjs", ".cjs", ".svg", ".html", ".htm", ".css")
IMAGE_EXTENSIONS = (".webp", ".png", ".jpg")

#: Top level keys a submitted theme.json may carry. ``effects`` (a script),
#: ``mascot`` (an svg) and ``themeCss`` are deliberately absent.
ALLOWED_KEYS = frozenset(
    {"id", "name", "description", "author", "version", "cssVars", "xterm", "background"}
)

#: The custom properties a theme may set: the union of the bundled themes'
#: keys. ``tests/hosted_catalog/test_validate_kinds.py`` holds it to the
#: shipped tree, so a property added to the app goes red there.
KNOWN_CSS_VARS = frozenset(
    """--ascii-display --badge-color-claude --badge-color-codex
--badge-color-hermes --badge-color-openclaw --color-accent
--color-accent-bg --color-accent-bg-active --color-accent-bg-faint
--color-accent-bg-hover --color-accent-bg-soft --color-accent-border
--color-accent-border-mid --color-accent-border-soft
--color-accent-border-strong --color-accent-glow
--color-accent-glow-strong --color-accent-shadow-soft
--color-accent-strong --color-badge-external-bg --color-badge-external-fg
--color-badge-owned-bg --color-badge-owned-fg --color-badge-tmux-bg
--color-badge-tmux-fg --color-bg --color-bg-card --color-bg-elevated
--color-bg-hover --color-bg-overlay --color-bg-overlay-faint
--color-bg-overlay-soft --color-bg-page --color-border
--color-border-subtle --color-danger --color-danger-bg
--color-danger-bg-hover --color-danger-border --color-danger-glow
--color-danger-soft --color-danger-strong --color-danger-strong-bg
--color-fg --color-fg-faint --color-fg-muted --color-fg-subtle
--color-header-bg --color-info --color-info-bg --color-info-border
--color-on-accent --color-status-connected --color-status-connected-glow
--color-status-error --color-status-error-glow --color-status-pending
--color-status-pending-glow --color-success --color-syntax-blue
--color-syntax-cyan --color-tabstrip-bg --color-warning --color-warning-bg
--color-warning-border --font-mono --radius-full --radius-lg --radius-md
--radius-pill --radius-sm --shadow-modal --usage-scale-1 --usage-scale-2
--usage-scale-3 --usage-scale-4 --usage-scale-5""".split()
)

XTERM_KEYS = frozenset(
    """background foreground cursor black red green yellow blue magenta cyan white
brightBlack brightRed brightGreen brightYellow brightBlue brightMagenta brightCyan
brightWhite selectionBackground""".split()
)

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_BAD_CHARS_RE = re.compile(r"[{};\\<>\x00-\x1f\x7f]")
#: Anything that makes the browser fetch or evaluate: url(), image-set(),
#: element(), expression(), @import.
_BAD_FUNC_RE = re.compile(
    r"@import|\b(?:url|image-set|image|src|element|paint|cross-fade|expression)\s*\(",
    re.IGNORECASE,
)
_IMAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
MAX_VALUE_CHARS = 256


def _refuse(code: str, detail: str, status: int = 400) -> None:
    """Raise the refusal for a theme rule.

    Inputs: code (str) stable code; detail (str) sentence; status (int).
    Output: never returns.
    Raises: KindRefused.
    Example: _refuse("theme_invalid", "id must equal the name")
    """
    raise KindRefused(status, code, detail)


def _safe_string(value: Any, what: str, limit: int = MAX_VALUE_CHARS) -> str:
    """Hold one manifest string to the conservative character rule.

    Inputs: value (Any) untrusted; what (str) for the message; limit (int)
      the longest accepted length.
    Output: str, the value unchanged.
    Raises: KindRefused 400 theme_value_unsafe.
    Example: _safe_string("#fff", "cssVars --color-fg") -> "#fff"
    """
    if not isinstance(value, str) or not value or len(value) > limit:
        _refuse("theme_value_unsafe", f"{what} must be a string of 1 to {limit} characters")
    if _BAD_CHARS_RE.search(value) or _BAD_FUNC_RE.search(value):
        _refuse(
            "theme_value_unsafe",
            f"{what} carries a character or function a theme may not use",
        )
    return value


def image_dimensions(path: str, data: bytes) -> Tuple[int, int]:
    """Check an image's magic bytes against its extension and read its size.

    Description: header parsing only, nothing is decoded. Supports the
      three accepted formats: png (IHDR), webp (VP8, VP8L, VP8X) and jpeg
      (first SOF marker).
    Inputs: path (str) the member path; data (bytes) its content.
    Output: (width, height) in pixels.
    Raises: KindRefused 400 theme_image_invalid on bad magic or a
      truncated header, 400 theme_image_too_large past the pixel caps.
    Example: image_dimensions("a.png", png_bytes) -> (240, 240)
    """
    ext = path[path.rfind(".") :].lower()
    dims: Optional[Tuple[int, int]] = None
    try:
        if ext == ".png" and data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            dims = struct.unpack(">II", data[16:24])
        elif ext == ".webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            kind = data[12:16]
            if kind == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
                w, h = struct.unpack("<HH", data[26:30])
                dims = (w & 0x3FFF, h & 0x3FFF)
            elif kind == b"VP8L" and data[20:21] == b"\x2f":
                bits = struct.unpack("<I", data[21:25])[0]
                dims = ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
            elif kind == b"VP8X":
                dims = (
                    int.from_bytes(data[24:27], "little") + 1,
                    int.from_bytes(data[27:30], "little") + 1,
                )
        elif ext == ".jpg" and data[:3] == b"\xff\xd8\xff":
            dims = _jpeg_dimensions(data)
    except struct.error:
        dims = None
    if not dims or not dims[0] or not dims[1]:
        _refuse("theme_image_invalid", f"{path!r} is not a valid {ext[1:]} image")
    if max(dims) > MAX_IMAGE_SIDE or dims[0] * dims[1] > MAX_IMAGE_PIXELS:
        _refuse(
            "theme_image_too_large",
            f"{path!r} is {dims[0]} x {dims[1]} pixels; the cap is "
            f"{MAX_IMAGE_SIDE} a side and {MAX_IMAGE_PIXELS} in total",
        )
    return dims


def _jpeg_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Walk jpeg markers to the first start-of-frame and return its size.

    Inputs: data (bytes) a file already known to start with ff d8 ff.
    Output: (width, height), or None when no frame header is found.
    Example: _jpeg_dimensions(jpeg_bytes) -> (64, 48)
    """
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            return None
        marker = data[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD9)):
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", data[pos + 5 : pos + 9])
            return w, h
        pos += 2 + length
    return None


def _check_colours(block: Any, allowed: frozenset, what: str, hex_only: bool) -> None:
    """Check a cssVars or xterm object: known keys, safe values.

    Inputs: block (Any) the untrusted object; allowed (frozenset) the key
      set; what (str) for messages; hex_only (bool) xterm values must be hex.
    Output: None.
    Raises: KindRefused 400 theme_invalid or theme_value_unsafe.
    Example: _check_colours({"red": "#f00"}, XTERM_KEYS, "xterm", True)
    """
    if not isinstance(block, dict) or not block:
        _refuse("theme_invalid", f"{what} must be a non empty object")
    for key, value in block.items():
        if key not in allowed:
            _refuse("theme_invalid", f"{what} carries an unknown key {str(key)[:40]!r}")
        _safe_string(value, f"{what} {key}")
        if hex_only and not _HEX_RE.match(value):
            _refuse("theme_value_unsafe", f"{what} {key} must be a hex colour")


def validate_theme(name: str, members: Dict[str, bytes]) -> str:
    """Validate a decoded theme folder and return its theme.json text.

    Description: root files only; ``theme.json`` a UTF-8 object of at most
      64 KiB whose ``id`` equals the submission name; every other file a
      checked raster. Scripts and markup are a 409; any other stray path a
      400 with its own stable code. The background image, when named, must
      be one of the included rasters.
    Inputs: name (str) the validated submission name; members (dict) path
      to content.
    Output: str, the manifest text.
    Raises: KindRefused with a stable code for every refusal.
    Example: validate_theme("mine", {"theme.json": b"{...}", "bg.webp": b"..."})
    """
    for path in members:
        if path.lower().endswith(SCRIPT_EXTENSIONS):
            _refuse(
                "scripts_not_supported",
                "this catalog does not publish scripts, stylesheets or markup",
                409,
            )
    for path, data in members.items():
        if path == MANIFEST:
            continue
        if "/" in path or not path.lower().endswith(IMAGE_EXTENSIONS):
            _refuse(
                "theme_file_not_allowed",
                f"a theme carries theme.json and root level webp, png or jpg only, not {path!r}",
            )
        image_dimensions(path, data)
    raw = members.get(MANIFEST)
    if raw is None:
        _refuse("submission_invalid", "the folder carries no theme.json")
    if len(raw) > MAX_MANIFEST_BYTES:
        _refuse("theme_invalid", "theme.json is larger than 64 KiB", 413)
    try:
        text = raw.decode("utf-8")
        manifest = json.loads(text)
    except (UnicodeDecodeError, ValueError) as exc:
        raise KindRefused(400, "theme_invalid", "theme.json is not utf-8 json") from exc
    if not isinstance(manifest, dict):
        _refuse("theme_invalid", "theme.json must be a json object")
    if "effects" in manifest:
        _refuse("scripts_not_supported", "a theme may not declare effects", 409)
    extra = sorted(str(k)[:40] for k in manifest if k not in ALLOWED_KEYS)
    if extra:
        _refuse("theme_invalid", f"theme.json carries keys a theme may not use: {extra[:5]}")
    if manifest.get("id") != name:
        _refuse("theme_invalid", f"theme.json id {str(manifest.get('id'))[:40]!r} is not {name!r}")
    _safe_string(manifest.get("name"), "name", 80)
    _safe_string(manifest.get("description"), "description", MAX_DESCRIPTION_CHARS)
    for key in ("author", "version"):
        if key in manifest:
            _safe_string(manifest[key], key, 64)
    _check_colours(manifest.get("cssVars"), KNOWN_CSS_VARS, "cssVars", False)
    _check_colours(manifest.get("xterm"), XTERM_KEYS, "xterm", True)
    _check_background(manifest.get("background"), members)
    return text


def _check_background(block: Any, members: Dict[str, bytes]) -> None:
    """Check the optional background block: an included raster and a scrim.

    Inputs: block (Any) the value or None when absent; members (dict).
    Output: None.
    Raises: KindRefused 400 theme_invalid.
    Example: _check_background({"image": "bg.webp", "dim": 0.9}, members)
    """
    if block is None:
        return
    if not isinstance(block, dict) or set(block) - {"image", "dim"}:
        _refuse("theme_invalid", "background carries only image and dim")
    image = block.get("image")
    if (
        not isinstance(image, str)
        or not _IMAGE_NAME_RE.match(image)
        or image == MANIFEST
        or image not in members
    ):
        _refuse("theme_invalid", "background.image must name a raster included in the folder")
    dim = block.get("dim", 0.9)
    if isinstance(dim, bool) or not isinstance(dim, (int, float)) or not 0 <= dim <= 1:
        _refuse("theme_invalid", "background.dim must be a number from 0 to 1")
