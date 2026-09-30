"""Which kind a folder is, and the rules that kind holds it to.

THE KIND IS THE MANIFEST THAT IS PRESENT: exactly one of ``SKILL.md``,
``theme.json`` and ``.claude-plugin/plugin.json`` at the folder root. A
loadout manifest is refused (this catalog publishes no loadout through
the submission rules) and so is a folder with none or several.

THIS IS A PORT OF THE HOSTED VALIDATORS in the product repository
(``hosted/catalog/api/validate_kinds.py``, ``validate_theme.py``,
``validate_plugin.py`` and the skill half of ``validate_upload.py``), on
the same order of checks: kind, name, paths and caps, then the kind's own
rules. ``tests/fixtures/kind_vectors.json`` is the one vectors file both
run, pinned by sha256 on both sides, so the two cannot drift silently.

WHERE EACH HALF IS USED. ``verify_release`` runs the theme and plugin
rules over the folder AT THE SIGNED COMMIT, so a theme or plugin nobody
would accept from the front door cannot be signed into the index by hand
either. The skill rules are here so the same vectors cover all three
kinds and the batch tool can gate a skill submission; a skill release
already in this repository keeps its own gates (the review, the grade),
because Adam's own skills legitimately carry scripts.

Pure over plain values, except ``load_folder`` which reads a directory.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from . import plugins, themes
from .content_rules import FORBIDDEN_NAMES, FORBIDDEN_SEGMENTS, content_problem
from .kind_errors import MAX_DESCRIPTION_CHARS, KindRefused
from .statements import SKILL_NAME_RE

KIND_SKILL = "skill"
KIND_THEME = "theme"
KIND_PLUGIN = "plugin"

MIB = 1024 * 1024
SKILL_MANIFEST = "SKILL.md"
#: A folder carrying this is a loadout, which the submission rules refuse.
LOADOUT_MANIFEST = "loadout.json"
MAX_PATH_LENGTH = 200

#: Per kind: its manifest and caps. ``members`` bounds the file count,
#: ``file`` one decoded file and ``total`` the decoded sum. The hosted
#: table also carries the transport ``body`` cap; that bounds a base64
#: request and has no meaning for a folder in git.
KIND_LIMITS: Dict[str, Dict[str, Any]] = {
    KIND_SKILL: {"manifest": SKILL_MANIFEST, "members": 2000, "file": 256 * 1024, "total": MIB},
    KIND_THEME: {"manifest": themes.MANIFEST, "members": 32, "file": 512 * 1024, "total": MIB},
    KIND_PLUGIN: {"manifest": plugins.MANIFEST, "members": 500, "file": 256 * 1024, "total": MIB},
}
MANIFEST_KINDS = {limits["manifest"]: kind for kind, limits in KIND_LIMITS.items()}

_FRONTMATTER_RE = re.compile(r"^---[^\S\n]*\n(.*?\n)---[^\S\n]*\n", re.DOTALL)

#: Every theme the app ships, by folder name, and the skill names a harness
#: already ships. Reserved names are per kind; one bare-name namespace is
#: shared by all kinds.
BUNDLED_THEME_IDS = frozenset(
    {
        "acid_trip",
        "alien",
        "ascii-abyss",
        "ascii-astral",
        "ascii-bloom",
        "ascii-creator",
        "ascii-forge",
        "ascii-gold-master",
        "ascii-mantis",
        "ascii-oracle",
        "ascii-raven",
        "ascii-relic",
        "ascii-ronin",
        "black_market",
        "black_ops",
        "blade_runner",
        "calming",
        "cannabis",
        "carnivore",
        "carnivore-light",
        "claude",
        "claw",
        "codex",
        "corporate_v2",
        "dracula",
        "gameboy",
        "green_crt",
        "hermes",
        "ice_forge",
        "jagermeister",
        "legacy_apple",
        "legacy_windows",
        "lovecraft",
        "matrix",
        "metal",
        "neon_city",
        "neural",
        "pokemon",
        "riot",
        "snes",
        "terminal",
    }
)

RESERVED_SKILL_NAMES = frozenset(
    {
        "imagegen",
        "openai-docs",
        "plugin-creator",
        "review-agent",
        "skill-creator",
        "skill-installer",
        "init",
        "simplify",
        "code-review",
        "security-review",
        "loop",
        "schedule",
        "keybindings-help",
        "update-config",
        "claude-api",
        "design",
        "dataviz",
        "artifact-design",
        "artifact-diagramming",
        "artifact-capabilities",
        "workflow-authoring",
        "claude-in-chrome",
        "run",
        "fewer-permission-prompts",
    }
)

RESERVED_NAMES = {KIND_SKILL: RESERVED_SKILL_NAMES, KIND_THEME: BUNDLED_THEME_IDS, KIND_PLUGIN: frozenset()}


def detect_kind(paths: Iterable[str], declared: Any = None) -> str:
    """Name the kind of a file list by which manifest it carries.

    Description: case-insensitive path match only, so it can run before any bytes are
      read. Exactly one manifest must be present; a declared kind must
      agree.
    Inputs: paths (iterable of str); declared (Any) an optional kind the
      caller expects.
    Output: str, "skill", "theme" or "plugin".
    Raises: KindRefused 400 kind_not_supported, kind_mismatch or
      submission_invalid.
    Example: detect_kind(["theme.json"]) -> "theme"
    """
    if declared is not None and declared not in KIND_LIMITS:
        raise KindRefused(400, "kind_not_supported", "this catalog publishes skills, themes and plugins")
    found = {p.lower() for p in paths}
    if LOADOUT_MANIFEST in found:
        raise KindRefused(400, "kind_not_supported", "this catalog does not publish loadouts")
    kinds = sorted(MANIFEST_KINDS[m] for m in MANIFEST_KINDS if m.lower() in found)
    if not kinds:
        raise KindRefused(400, "submission_invalid", "the folder carries no SKILL.md, theme.json or .claude-plugin/plugin.json")
    if len(kinds) > 1:
        raise KindRefused(400, "submission_invalid", f"the folder carries more than one manifest: {kinds}")
    if declared is not None and declared != kinds[0]:
        raise KindRefused(400, "kind_mismatch", f"declared {declared!r} but the folder is a {kinds[0]}")
    return kinds[0]


def _check_name(kind: str, name: Any) -> None:
    """Hold a name to the shared grammar and the kind's reserved list.

    Inputs: kind (str); name (Any).
    Raises: KindRefused 400 submission_invalid, 409 name_reserved.
    Example: _check_name("theme", "matrix") -> raises 409
    """
    if not isinstance(name, str) or not SKILL_NAME_RE.match(name):
        raise KindRefused(400, "submission_invalid", "name must match " + SKILL_NAME_RE.pattern)
    if name.lower() in RESERVED_NAMES[kind]:
        raise KindRefused(409, "name_reserved", f"this app already ships a {kind} with that name")


def _check_path(path: str, seen: Dict[str, str]) -> None:
    """Hold one member path to a relative, ascii, traversal free shape.

    Inputs: path (str); seen (dict) case folded paths so far, mutated.
    Raises: KindRefused 400 submission_invalid.
    Example: _check_path("a/b.md", {}) -> None
    """
    problem = ""
    if not path:
        problem = "every file needs a non empty path"
    elif len(path) > MAX_PATH_LENGTH:
        problem = f"a path is longer than {MAX_PATH_LENGTH} characters"
    elif not path.isascii():
        problem = f"a path is not ascii: {path!r}"
    elif any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        problem = "a path carries a control character"
    elif "\\" in path:
        problem = f"a path carries a backslash: {path!r}"
    elif path.startswith("/") or any(s in ("", ".", "..") for s in path.split("/")):
        problem = f"a path is not a plain relative path: {path!r}"
    elif path.lower() in seen:
        problem = f"two files share the path {path!r}"
    if problem:
        raise KindRefused(400, "submission_invalid", problem)
    seen[path.lower()] = path


def frontmatter(text: str) -> Dict[str, str]:
    """Read the top level keys of a leading YAML front matter block.

    Inputs: text (str) the manifest text.
    Output: dict of key to value, empty when there is no block.
    Example: frontmatter("---\\nname: x\\n---\\nbody") -> {"name": "x"}
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip() or line[:1].isspace() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip().strip("'\"")
    return fields


#: A skill folder installs into the same directory a plugin does, so a
#: plugin manifest inside one would make Claude Code load it as a plugin.
_SKILL_FORBIDDEN_SEGMENTS = (FORBIDDEN_SEGMENTS - {"scripts"}) | {".claude-plugin"}


def _check_skill_inert(members: Dict[str, bytes]) -> None:
    """Refuse a skill that can run code without a per-use decision.

    Inputs: members (dict) path to bytes.
    Raises: KindRefused 409 skill_not_safe listing up to ten paths.
    Example: _check_skill_inert({"SKILL.md": b"!`ls`"})
    """
    problems = []
    for path, data in members.items():
        parts = path.split("/")
        if any(p.lower() in _SKILL_FORBIDDEN_SEGMENTS for p in parts) or FORBIDDEN_NAMES.match(parts[-1]):
            problems.append(f"{path} (path not allowed)")
        elif path.lower().endswith(".md"):
            reason = content_problem(path, data)
            if reason:
                problems.append(f"{path} ({reason})")
    if problems:
        raise KindRefused(409, "skill_not_safe", "a skill may not carry: " + "; ".join(problems[:10]))


def _validate_skill(name: str, members: Dict[str, bytes]) -> str:
    """Skill rules: no scripts, one root SKILL.md whose front matter agrees.

    Inputs: name (str) the checked name; members (dict) path to bytes.
    Output: str, the SKILL.md text.
    Raises: KindRefused 409 scripts_not_supported, 400 submission_invalid.
    Example: _validate_skill("hello", {"SKILL.md": b"---\\nname: hello\\n..."})
    """
    if any(path.split("/", 1)[0] == "scripts" for path in members):
        raise KindRefused(409, "scripts_not_supported", "this catalog does not publish executable content")
    _check_skill_inert(members)
    nested = [p for p in members if p.endswith("/" + SKILL_MANIFEST)]
    if nested:
        raise KindRefused(400, "submission_invalid", f"{SKILL_MANIFEST} must be at the folder root, found {nested[0]!r}")
    try:
        text = members[SKILL_MANIFEST].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise KindRefused(400, "submission_invalid", f"{SKILL_MANIFEST} is not utf-8") from exc
    fields = frontmatter(text)
    if not fields:
        raise KindRefused(400, "submission_invalid", f"{SKILL_MANIFEST} carries no yaml front matter block")
    if fields.get("name") != name:
        raise KindRefused(400, "submission_invalid", f"front matter names {fields.get('name')!r}, not {name!r}")
    description = fields.get("description", "")
    if not description or len(description) > MAX_DESCRIPTION_CHARS:
        raise KindRefused(400, "submission_invalid", f"the description must be 1 to {MAX_DESCRIPTION_CHARS} characters")
    return text


def validate_folder(
    name: Any, members: Dict[str, bytes], declared: Any = None
) -> Tuple[str, str]:
    """Validate a whole folder of any supported kind.

    Description: kind first (from the paths), then the name, then paths and
      caps in member order, then the kind's own rules; the same order the
      hosted validator runs, so the same folder gets the same verdict.
    Inputs: name (Any) the item name; members (dict) path to bytes, in
      order; declared (Any) an optional kind the caller expects.
    Output: (kind, manifest text).
    Raises: KindRefused for every refusal, with the hosted status and code.
    Example: validate_folder("neon", {"theme.json": b"{...}"})[0] -> "theme"
    """
    kind = detect_kind(members, declared)
    limits = KIND_LIMITS[kind]
    _check_name(kind, name)
    if len(members) > limits["members"]:
        raise KindRefused(400, "submission_invalid", f"a folder may carry at most {limits['members']} files")
    seen: Dict[str, str] = {}
    total = 0
    for path, data in members.items():
        _check_path(path, seen)
        if len(data) > limits["file"]:
            raise KindRefused(413, "body_too_large", f"{path!r} is larger than {limits['file']} bytes")
        total += len(data)
        if total > limits["total"]:
            raise KindRefused(413, "body_too_large", "the folder is larger than its cap")
    if kind == KIND_SKILL:
        return kind, _validate_skill(name, members)
    check = themes.validate_theme if kind == KIND_THEME else plugins.validate_plugin
    return kind, check(name, members)


def load_folder(folder: Path) -> Dict[str, bytes]:
    """Read a checked out folder into path to bytes, refusing what git could hide.

    Description: a symlink or other non regular file is refused (the digest
      skips one, so it would be shipped unexamined), and so is an
      executable file, because a theme or plugin carries none. Sizes are
      read from the inode first, so a huge file is refused before it is
      read.
    Inputs: folder (Path) an existing directory.
    Output: dict of posix relpath to bytes, sorted by path.
    Raises: KindRefused 400 submission_invalid, 413 body_too_large.
    Example: load_folder(Path("themes/adoom666/neon"))["theme.json"]
    """
    found: Dict[str, Path] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        for entry in [*dirnames, *filenames]:
            info = os.lstat(os.path.join(dirpath, entry))
            rel = os.path.relpath(os.path.join(dirpath, entry), folder).replace(os.sep, "/")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                raise KindRefused(400, "submission_invalid", f"{rel} is not a regular file")
            if info.st_mode & stat.S_IXUSR:
                raise KindRefused(409, "scripts_not_supported", f"{rel} is executable")
            total += info.st_size
            if total > MIB or len(found) >= 2000:
                raise KindRefused(413, "body_too_large", "the folder is larger than its cap")
            found[rel] = Path(dirpath) / entry
    return {rel: found[rel].read_bytes() for rel in sorted(found)}
