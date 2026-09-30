"""Content and path rules shared by every kind that carries markdown or files.

One place decides what makes a submitted file able to run code, so the
skill rules and the plugin rules cannot drift apart. Pure over plain
values. THIS IS A PORT of ``hosted/catalog/api/validate_content.py`` in the
product repository, held to it by ``tests/fixtures/kind_vectors.json``, which
both repositories run and pin by sha256.

FRONT MATTER IS READ STRICTLY, NOT PARSED. The Lambda ships only its own
``*.py`` files, so there is no YAML library. Instead of guessing what a
real YAML parser would make of an odd block, every YAML spelling that can
hide a key is refused outright: flow mappings, anchors, aliases, merge
keys, tags, quoted or explicit keys. What is left is plain ``key: value``
lines, where a forbidden key can only be spelled one way and is matched at
any indent depth.
"""

from __future__ import annotations

import re

#: Path segments that run or configure code, at any depth.
FORBIDDEN_SEGMENTS = frozenset(
    {"hooks", "bin", "monitors", "scripts", ".claude", "node_modules"}
)
FORBIDDEN_NAMES = re.compile(
    r"^(?:\.mcp\.json|\.lsp\.json|settings(?:\.local)?\.json|hooks\.json)$", re.IGNORECASE
)
_FORBIDDEN_FRONT_RE = re.compile(
    r"""^\s*(?:-\s+)*(allowed-tools|permissionMode|hooks|mcpServers)\s*:""",
    re.IGNORECASE | re.MULTILINE,
)
#: YAML spellings that can hide a key from the line match above: a line
#: that opens with a quote, ``?`` (explicit key), ``!`` (tag), ``&``
#: (anchor), ``*`` (alias) or ``<<`` (merge key), and a flow mapping
#: opening a value, a list item or a line.
_HIDING_FRONT_RE = re.compile(
    r"""^\s*(?:-\s+)*(?:["'?!&*]|<<)|(?:^|[:\-\[,])[ \t]*[{&*!]""",
    re.MULTILINE,
)
#: The inline shell injection form (a bang then a backtick) and the fenced
#: bang block, matched anywhere in the text like the harness does.
_SHELL_RE = re.compile(r"!`|```!")


def content_problem(path: str, data: bytes) -> str:
    """Name what is wrong with a file's bytes, or return an empty string.

    Description: non UTF-8, a shebang, and for markdown the forbidden front
      matter keys, every YAML spelling that could hide one, and the inline
      shell marker. The front matter scan reads every line of a leading
      ``---`` block, or the whole file when the fence never closes, so an
      unusual layout cannot hide a key.
    Inputs: path (str); data (bytes).
    Output: str reason, empty when the file is clean.
    Example: content_problem("a.md", b"#!/bin/sh") -> "shebang"
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "not utf-8"
    text = text.lstrip("﻿")
    # A lone CR is a line break to the YAML parser: fold every break to LF.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.startswith("#!"):
        return "shebang"
    if path.lower().endswith(".md"):
        if text.startswith("---"):
            end = re.search(r"^---[^\S\n]*$", text[3:], re.MULTILINE)
            block = text[: end.end() + 3] if end else text
            found = _FORBIDDEN_FRONT_RE.search(block)
            if found:
                return f"front matter key {found.group(1)}"
            if _HIDING_FRONT_RE.search(block[3:]):
                return "front matter syntax not allowed (flow, anchor, alias, tag, merge or quoted key)"
        if _SHELL_RE.search(text):
            return "inline shell injection"
    return ""
