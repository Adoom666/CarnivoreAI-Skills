"""Who may publish, and which key the index signature must be under.

TWO DIFFERENT FILES, TWO DIFFERENT JOBS. ``publishers/<handle>.json`` says
which keys a publisher signs releases with; the build job verifies a release
statement against those and against nothing else. ``publishers/_index.json``
pins the key the INDEX is signed with, which the signing job checks its own
output against before anything is deployed.

AN EMPTY KEY LIST IS AN HONEST STATE, NOT AN ERROR. Adam generates the
keypairs himself and pastes the public halves in; an agent never holds a
private key. Until a handle has a key, its items are assembled and listed as
UNTRUSTED rather than hidden, which is the same posture the app takes for a
key it has not pinned: hiding them teaches nobody anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .minisign_verify import MinisignFormatError, PublicKey, parse_public_key

#: The folder holding both kinds of file.
PUBLISHERS_DIR = "publishers"

#: The file that pins the index signing key. The leading underscore keeps it
#: out of the handle namespace, which cannot start with one.
INDEX_KEY_FILE = "_index.json"

#: The only key status that may verify a release. Anything else is carried
#: into the index for the reader and never used to accept a signature.
STATUS_ACTIVE = "active"


@dataclass(frozen=True)
class PublisherRecord:
    """One publisher as the repository declares them.

    - ``handle``: the folder name under ``skills/`` and ``releases/``.
    - ``github_login``: who the handle belongs to, for the index.
    - ``keys``: every key as declared, verbatim, for the index document.
    - ``active_keys``: the parsed subset a signature may verify under,
      keyed by key id.
    """

    handle: str
    github_login: str
    keys: Tuple[Dict[str, str], ...]
    active_keys: Dict[str, PublicKey]


def _parse_record(handle: str, raw: object) -> PublisherRecord:
    """Turn one publisher file's parsed JSON into a record.

    :param handle: the handle taken from the FILENAME, never from the body.
    :param raw: the parsed JSON.
    :returns: the record.
    :raises ValueError: when a required field is missing or malformed.

    The handle comes from the filename so a file cannot claim to be a
    publisher it is not; a body whose ``handle`` disagrees is an error
    rather than a silent rename.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"publishers/{handle}.json must be a mapping")
    declared = raw.get("handle")
    if declared != handle:
        raise ValueError(
            f"publishers/{handle}.json declares handle {declared!r}, "
            f"which is not its filename"
        )
    login = raw.get("github_login")
    if not isinstance(login, str) or not login:
        raise ValueError(f"publishers/{handle}.json has no github_login")

    keys_raw = raw.get("keys", [])
    if not isinstance(keys_raw, list):
        raise ValueError(f"publishers/{handle}.json: keys must be a list")

    keys: List[Dict[str, str]] = []
    active: Dict[str, PublicKey] = {}
    for entry in keys_raw:
        if not isinstance(entry, dict):
            raise ValueError(f"publishers/{handle}.json: a key entry is not a mapping")
        for field in ("key_id", "alg", "pub", "added", "status"):
            if not isinstance(entry.get(field), str) or not entry[field]:
                raise ValueError(
                    f"publishers/{handle}.json: a key entry has no {field}"
                )
        keys.append({field: entry[field] for field in
                     ("key_id", "alg", "pub", "added", "status")})
        if entry["status"] != STATUS_ACTIVE:
            continue
        try:
            parsed = parse_public_key(entry["pub"])
        except MinisignFormatError as exc:
            raise ValueError(
                f"publishers/{handle}.json: key {entry['key_id']} is malformed: {exc}"
            ) from exc
        if parsed.key_id != entry["key_id"]:
            raise ValueError(
                f"publishers/{handle}.json: key entry says {entry['key_id']} "
                f"but the key itself is {parsed.key_id}"
            )
        active[parsed.key_id] = parsed

    return PublisherRecord(
        handle=handle,
        github_login=login,
        keys=tuple(keys),
        active_keys=active,
    )


def load_publishers(repo_root: Path) -> Dict[str, PublisherRecord]:
    """Read every publisher declaration in the repository.

    Description: reads ``publishers/*.json`` except the index key file, one
      record per handle taken from the filename. A malformed file raises
      rather than being skipped: a publisher the job cannot read is a
      publisher whose releases it would silently drop.
    Inputs: repo_root (Path).
    Output: dict of handle to PublisherRecord, empty when the folder holds
      nothing.
    Raises: ValueError on a malformed declaration.
    Example: load_publishers(Path("."))["adoom666"].github_login -> "Adoom666"
    """
    folder = repo_root / PUBLISHERS_DIR
    records: Dict[str, PublisherRecord] = {}
    if not folder.is_dir():
        return records
    for path in sorted(folder.glob("*.json")):
        if path.name == INDEX_KEY_FILE:
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        records[path.stem] = _parse_record(path.stem, raw)
    return records


def load_index_key(repo_root: Path) -> Optional[PublicKey]:
    """Read the pinned index signing key, or None when none is pinned.

    Description: reads ``publishers/_index.json``. A file that is absent,
      or present with an empty ``pub``, means NO KEY IS PINNED YET, which
      is the state this repository ships in until Adam pastes his public
      half. That is returned as None and every caller decides for itself
      what to do about it; the signing job skips, and the serial step
      refuses to count from a live index it cannot check.
    Inputs: repo_root (Path).
    Output: PublicKey, or None when no key is pinned.
    Raises: ValueError when a key IS pinned but does not parse, or when the
      declared key id disagrees with the key itself. A wrongly pinned key
      must fail loudly, never fall back to unpinned, which would widen
      trust silently.
    Example: load_index_key(Path(".")) -> None
    """
    path = repo_root / PUBLISHERS_DIR / INDEX_KEY_FILE
    if not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{PUBLISHERS_DIR}/{INDEX_KEY_FILE} must be a mapping")
    pub = raw.get("pub")
    if not isinstance(pub, str) or not pub.strip():
        return None
    try:
        parsed = parse_public_key(pub)
    except MinisignFormatError as exc:
        raise ValueError(
            f"{PUBLISHERS_DIR}/{INDEX_KEY_FILE}: the pinned key is malformed: {exc}"
        ) from exc
    declared = raw.get("key_id")
    if isinstance(declared, str) and declared and declared != parsed.key_id:
        raise ValueError(
            f"{PUBLISHERS_DIR}/{INDEX_KEY_FILE}: says key id {declared} "
            f"but the key itself is {parsed.key_id}"
        )
    return parsed
