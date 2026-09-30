"""Validation of a submitted plugin folder: an allowlist of inert files.

NOTHING A PLUGIN CARRIES MAY RUN WITHOUT A PER-USE DECISION BY THE USER OR
THE MODEL. That is the whole rule. A plugin is therefore an ALLOWLIST of
paths and manifest keys, never a denylist, so a new way of running code
that Claude Code adds later is refused by default:

* ``.claude-plugin/plugin.json`` (required) with the keys in
  ``MANIFEST_KEYS`` only. ``hooks``, ``mcpServers``, ``lspServers``,
  ``monitors`` and every path override key are refused by that allowlist.
* ``commands/**.md``, ``agents/**.md``, ``skills/<n>/SKILL.md`` plus text
  references beside it, and a root README and LICENSE.
* Any ``hooks``, ``bin``, ``monitors`` or ``scripts`` segment at any depth,
  ``.mcp.json``, ``.lsp.json``, settings files, every other path or
  extension, non UTF-8 bytes, a shebang, front matter keys that grant
  tools or permissions, and the inline shell injection marker are refused.

Every offence is collected first and raised once as 409 ``plugin_not_safe``
listing up to ten paths, so an author fixes everything in one round.
Structural mistakes (no manifest, bad json, wrong name) are 400.

Pure over plain values. THIS IS A PORT of ``hosted/catalog/api/validate_plugin.py`` in the
product repository, held to it by ``tests/fixtures/kind_vectors.json``, which
both repositories run and pin by sha256.
"""

from __future__ import annotations

import json
import re
from typing import Dict, List

from .kind_errors import KindRefused

MANIFEST = ".claude-plugin/plugin.json"
MAX_MANIFEST_BYTES = 64 * 1024
MAX_LISTED = 10

MANIFEST_KEYS = frozenset(
    {"name", "version", "description", "author", "homepage", "repository", "license", "keywords"}
)
#: Path segments that run or configure code, at any depth.
FORBIDDEN_SEGMENTS = frozenset(
    {"hooks", "bin", "monitors", "scripts", ".claude", "node_modules"}
)
FORBIDDEN_NAMES = re.compile(
    r"^(?:\.mcp\.json|\.lsp\.json|settings(?:\.local)?\.json|hooks\.json)$", re.IGNORECASE
)
TEXT_REFERENCE_EXTENSIONS = (".md", ".txt", ".json", ".yaml", ".yml")
_ROOT_DOC_RE = re.compile(r"^(?:readme|license)(?:\.md|\.txt)?$", re.IGNORECASE)
_FORBIDDEN_FRONT_RE = re.compile(
    r"""^\s*["']?(allowed-tools|permissionMode|hooks|mcpServers)["']?\s*:""",
    re.IGNORECASE | re.MULTILINE,
)
#: The inline shell injection form (a bang then a backtick) and the fenced
#: bang block.
_SHELL_RE = re.compile(r"!`|^\s*```!", re.MULTILINE)


def _refuse(code: str, detail: str) -> None:
    """Raise a 400 for a structural mistake.

    Inputs: code (str); detail (str).
    Output: never returns.
    Raises: KindRefused 400.
    Example: _refuse("plugin_invalid", "bad json")
    """
    raise KindRefused(400, code, detail)


def _path_allowed(path: str) -> bool:
    """Whether a path is on the plugin allowlist.

    Inputs: path (str) an already path-checked member path.
    Output: bool.
    Example: _path_allowed("commands/a/b.md") -> True
    """
    parts = path.split("/")
    if path == MANIFEST:
        return True
    if any(p.lower() in FORBIDDEN_SEGMENTS for p in parts) or FORBIDDEN_NAMES.match(parts[-1]):
        return False
    if len(parts) == 1:
        return bool(_ROOT_DOC_RE.match(path))
    lower = path.lower()
    if parts[0] in ("commands", "agents"):
        return lower.endswith(".md")
    if parts[0] == "skills" and len(parts) >= 3:
        return lower.endswith(TEXT_REFERENCE_EXTENSIONS)
    return False


def _content_problem(path: str, data: bytes) -> str:
    """Name what is wrong with a file's bytes, or return an empty string.

    Description: non UTF-8, a shebang, and for markdown the forbidden front
      matter keys and the inline shell marker. The front matter scan reads
      every line of a leading ``---`` block, or the whole file when the
      fence never closes, so an unusual layout cannot hide a key.
    Inputs: path (str); data (bytes).
    Output: str reason, empty when the file is clean.
    Example: _content_problem("a.md", b"#!/bin/sh") -> "shebang"
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "not utf-8"
    text = text.lstrip("﻿")
    if text.startswith("#!"):
        return "shebang"
    if path.lower().endswith(".md"):
        if text.startswith("---"):
            end = re.search(r"^---[^\S\n]*$", text[3:], re.MULTILINE)
            block = text[: end.end() + 3] if end else text
            found = _FORBIDDEN_FRONT_RE.search(block)
            if found:
                return f"front matter key {found.group(1)}"
        if _SHELL_RE.search(text):
            return "inline shell injection"
    return ""


def _manifest_problems(name: str, raw: bytes) -> List[str]:
    """Check plugin.json and return the unsafe-key offences it carries.

    Inputs: name (str) the submission name; raw (bytes) plugin.json.
    Output: list of "path (reason)" strings, empty when the keys are safe.
    Raises: KindRefused 400 plugin_invalid for a structural mistake.
    Example: _manifest_problems("p", b'{"name":"p","hooks":{}}')
    """
    if len(raw) > MAX_MANIFEST_BYTES:
        _refuse("plugin_invalid", "plugin.json is larger than 64 KiB")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _refuse("plugin_invalid", "plugin.json is not utf-8 json")
    if not isinstance(manifest, dict):
        _refuse("plugin_invalid", "plugin.json must be a json object")
    if manifest.get("name") != name:
        _refuse("plugin_invalid", "plugin.json name does not match the submission name")
    problems = [
        f"{MANIFEST} (key {str(key)[:40]})" for key in manifest if key not in MANIFEST_KEYS
    ]
    for key in ("homepage", "repository"):
        value = manifest.get(key)
        if value is not None and not (
            isinstance(value, str) and re.match(r"^https?://", value)
        ):
            problems.append(f"{MANIFEST} ({key} must be an http or https url)")
    return problems


def validate_plugin(name: str, members: Dict[str, bytes]) -> str:
    """Validate a decoded plugin folder and return its plugin.json text.

    Inputs: name (str) the validated submission name; members (dict) path
      to content.
    Output: str, the manifest text.
    Raises: KindRefused 400 plugin_invalid for a structural mistake,
      409 plugin_not_safe naming up to ten offending paths.
    Example: validate_plugin("p", {".claude-plugin/plugin.json": b'{"name":"p"}'})
    """
    raw = members.get(MANIFEST)
    if raw is None:
        _refuse("submission_invalid", "the folder carries no .claude-plugin/plugin.json")
    problems: List[str] = _manifest_problems(name, raw)
    for path, data in members.items():
        if not _path_allowed(path):
            problems.append(f"{path} (path not allowed)")
        elif path != MANIFEST:
            reason = _content_problem(path, data)
            if reason:
                problems.append(f"{path} ({reason})")
    if problems:
        listed = "; ".join(problems[:MAX_LISTED])
        more = f"; and {len(problems) - MAX_LISTED} more" if len(problems) > MAX_LISTED else ""
        raise KindRefused(
            409, "plugin_not_safe", f"a plugin may not carry: {listed}{more}"
        )
    return raw.decode("utf-8")
