"""Turn a proven repository into the index document, and nothing more.

This module does no cryptography of its own. Every version it lists has
already survived :mod:`index_builder.releases`, and every revocation it
carries has already been checked against the publisher's own key. What is
left is arrangement: grouping versions into items, deciding which one is
``latest``, and writing the exact wire shape the app parses.

TWO ORDERING RULES, BOTH DELIBERATE. Items and versions are sorted, and the
sort is total, because two builds of the same commit must produce the same
bytes: an index whose field order wandered would be a different document to
sign every time and nobody could tell a rebuild from a change. And
``latest`` is the highest VERSION rather than the newest commit, because a
fix published for an old line must not become what everybody installs.

AN UNVERIFIABLE REVOCATION FAILS THE BUILD. The app ignores one, because it
is reading a document from a server and a forged revocation that stuck would
be permanent. This job is reading its OWN repository under CODEOWNERS, where
the dangerous direction is the other one: a revocation quietly dropped here
leaves a version somebody already decided was bad sitting in the index,
installable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .frontmatter import card_and_fm, parse_front_matter
from .minisign_verify import MinisignFormatError, parse_signature, verify
from .publishers import PublisherRecord
from .releases import (
    KIND_SKILL,
    SKILLS_DIR,
    ReleaseRefused,
    VerifiedRelease,
)
from .statements import revoke_statement

#: The wire value of the index's ``schema`` field.
SCHEMA = "carnivore.catalog.index/1"

#: Where revocation statements live.
REVOCATIONS_DIR = "revocations"

#: Splits a version into its numeric and non numeric runs for ordering.
_VERSION_PART = re.compile(r"(\d+)")


def version_sort_key(version: str) -> Tuple[object, ...]:
    """Order versions so 1.10.0 sorts after 1.9.0 rather than before it.

    Description: splits on digit runs and compares the numeric runs as
      integers and everything else as text. This is not a semver parser
      and does not pretend to be one: it gives a TOTAL, stable order over
      whatever strings publishers actually use, which is what ``latest``
      needs. A publisher who wants precise precedence uses plain numbers.
    Inputs: version (str).
    Output: a tuple usable as a sort key.
    Example: sorted(["1.9.0", "1.10.0"], key=version_sort_key)[-1] -> "1.10.0"
    """
    parts: List[object] = []
    for chunk in _VERSION_PART.split(version):
        if not chunk:
            continue
        parts.append((0, int(chunk), "") if chunk.isdigit() else (1, 0, chunk))
    return tuple(parts)


@dataclass(frozen=True)
class AssembledIndex:
    """The index document, plus what the job log needs to say about it.

    - ``document``: the whole index, ready to serialise.
    - ``item_count``, ``version_count``: what it actually carries.
    - ``untrusted_handles``: handles with no active key, whose versions
      could not be verified and are therefore ABSENT from the document.
    """

    document: Dict[str, object]
    item_count: int
    version_count: int
    untrusted_handles: Tuple[str, ...]


def _publishers_block(
    publishers: Dict[str, PublisherRecord],
) -> Dict[str, Dict[str, object]]:
    """Render the index's publishers block, keys verbatim as declared.

    :param publishers: every declared publisher.
    :returns: the block, one entry per handle, handles sorted.

    Every key is carried, including revoked and retired ones, because the
    app shows a reader which key signed what and a key that vanished from
    the index would make an old, still valid signature unexplainable.
    """
    return {
        handle: {
            "github_login": record.github_login,
            "keys": [dict(key) for key in record.keys],
        }
        for handle, record in sorted(publishers.items())
    }


def _verified_revocations(
    repo_root: Path, publishers: Dict[str, PublisherRecord],
) -> Dict[str, List[Dict[str, str]]]:
    """Read every revocation in the repository and prove each one.

    Description: each file names a kind, a subject and a date, and carries
      the statement text and a whole ``.minisig``. The statement is
      REBUILT from the fields and the carried text must equal it, so a
      genuine statement revoking one thing cannot be pasted into a file
      naming another. Then the signature is verified under an active key
      of the handle whose folder the file sits in.
    Inputs: repo_root (Path). publishers (dict).
    Output: the index's ``revocations`` block, with ``keys`` and
      ``versions`` lists.
    Raises: ReleaseRefused when any revocation cannot be proven, because
      dropping one silently leaves a bad version installable.
    Example: _verified_revocations(root, records)["versions"] -> []
    """
    block: Dict[str, List[Dict[str, str]]] = {"keys": [], "versions": []}
    folder = repo_root / REVOCATIONS_DIR
    if not folder.is_dir():
        return block

    for path in sorted(folder.glob("*/*.json")):
        where = str(path.relative_to(repo_root))
        handle = path.parent.name
        record = publishers.get(handle)
        if record is None:
            raise ReleaseRefused(
                f"{where}: there is no publishers/{handle}.json to verify it against"
            )
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ReleaseRefused(f"{where}: is not a JSON object")

        kind = raw.get("kind")
        subject = raw.get("subject")
        since = raw.get("since")
        statement = raw.get("statement")
        signature_text = raw.get("sig")
        for field, value in (
            ("kind", kind), ("subject", subject), ("since", since),
            ("statement", statement), ("sig", signature_text),
        ):
            if not isinstance(value, str) or not value:
                raise ReleaseRefused(f"{where}: {field} is missing or not a string")
        assert isinstance(kind, str) and isinstance(subject, str)
        assert isinstance(since, str) and isinstance(statement, str)
        assert isinstance(signature_text, str)

        try:
            expected = revoke_statement(kind=kind, subject=subject, since=since)
        except ValueError as exc:
            raise ReleaseRefused(f"{where}: these fields cannot form a statement: {exc}") from exc
        if statement.encode("utf-8") != expected:
            raise ReleaseRefused(
                f"{where}: the statement it carries is not the one these fields name"
            )
        try:
            signature = parse_signature(signature_text)
            key = record.active_keys.get(signature.key_id)
            if key is None:
                raise ReleaseRefused(
                    f"{where}: signed by key {signature.key_id}, which is not an "
                    f"active key of {handle}"
                )
            ok = verify(expected, signature, key, expect_prehashed=True)
        except MinisignFormatError as exc:
            raise ReleaseRefused(f"{where}: the signature is malformed: {exc}") from exc
        if not ok:
            raise ReleaseRefused(
                f"{where}: the signature does not verify under {handle}'s key"
            )

        if kind == "key":
            block["keys"].append({
                "key_id": subject, "since": since,
                "statement": statement, "sig": signature_text,
            })
        else:
            item_id, _, version = subject.rpartition("@")
            if not item_id or not version:
                raise ReleaseRefused(
                    f"{where}: a version revocation's subject must read "
                    f"<publisher>/<name>@<version>"
                )
            block["versions"].append({
                "item": item_id, "version": version, "since": since,
                "statement": statement, "sig": signature_text,
            })
    return block


def _version_entry(
    release: VerifiedRelease, repo_slug: str, review: Optional[Dict[str, object]],
) -> Dict[str, object]:
    """Render one proven release as an index version entry.

    :param release: what the verifier proved.
    :param repo_slug: ``owner/repo``, the same string the statement signed.
    :param review: the review block, or None when none has been written.
    :returns: the entry.

    The review is attached here rather than built here: this job assembles
    an unreviewed index first and the review step fills it in afterwards,
    which is what keeps the review strictly after the publisher signature.

    THE GRADE IS ALREADY DECIDED by the time this runs. It was taken in the
    verification worktree, over the bytes at this version's own commit, so
    it is copied through rather than computed here: computing it here would
    grade whatever the working tree holds and attach that answer to every
    version, including the old ones it does not describe.
    """
    entry: Dict[str, object] = {
        "v": release.version,
        "src": {
            "repo": repo_slug,
            "path": f"{SKILLS_DIR}/{release.handle}/{release.name}",
            "commit": release.commit,
        },
        "digest": release.digest,
        "size": release.size,
        "files": release.files,
        "scripts": release.scripts,
        "published_at": release.published_at,
        "sig": dict(release.sig),
        "grade": dict(release.grade),
    }
    if review is not None:
        entry["review"] = review
    return entry


def assemble(
    repo_root: Path,
    *,
    publishers: Dict[str, PublisherRecord],
    releases: Sequence[VerifiedRelease],
    repo_slug: str,
    serial: int,
    generated_at: Optional[str] = None,
) -> AssembledIndex:
    """Build the whole index document from proven parts.

    Description: groups the proven releases into items, reads each item's
      card and front matter out of the SKILL.md AT ITS LATEST COMMIT, and
      writes the document. The front matter is read from the checked in
      working tree at the latest version's commit path, which is the tree
      the build is running on, so a card can never describe a different
      folder from the one the digest covers.
    Inputs: repo_root (Path). publishers (dict). releases (sequence of
      VerifiedRelease). repo_slug (str). serial (int). generated_at (str
      or None) - supplied only by tests; the default is now, in UTC.
    Output: AssembledIndex.
    Raises: ReleaseRefused when an item's SKILL.md cannot be read.
    Example: assemble(root, publishers={}, releases=[], repo_slug="a/b",
      serial=1).item_count -> 0
    """
    grouped: Dict[Tuple[str, str], List[VerifiedRelease]] = {}
    for release in releases:
        grouped.setdefault((release.handle, release.name), []).append(release)

    items: List[Dict[str, object]] = []
    version_count = 0
    for (handle, name), group in sorted(grouped.items()):
        ordered = sorted(group, key=lambda r: version_sort_key(r.version))
        latest = ordered[-1]
        skill_md = repo_root / SKILLS_DIR / handle / name / "SKILL.md"
        if not skill_md.is_file():
            raise ReleaseRefused(
                f"{SKILLS_DIR}/{handle}/{name}/SKILL.md is missing from the "
                f"working tree, so there is nothing to build a card from"
            )
        try:
            front = parse_front_matter(skill_md)
        except ValueError as exc:
            raise ReleaseRefused(str(exc)) from exc
        card, fm = card_and_fm(front, name=name)

        items.append({
            "id": f"{handle}/{name}",
            "kind": KIND_SKILL,
            "name": name,
            "publisher": handle,
            "latest": latest.version,
            "card": card,
            "fm": fm,
            "versions": [_version_entry(r, repo_slug, None) for r in ordered],
        })
        version_count += len(ordered)

    stamp = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    document: Dict[str, object] = {
        "schema": SCHEMA,
        "serial": serial,
        "generated_at": stamp,
        "publishers": _publishers_block(publishers),
        "revocations": _verified_revocations(repo_root, publishers),
        "items": items,
    }
    untrusted = tuple(
        handle for handle, record in sorted(publishers.items())
        if not record.active_keys
    )
    return AssembledIndex(
        document=document,
        item_count=len(items),
        version_count=version_count,
        untrusted_handles=untrusted,
    )


def write_index(document: Dict[str, object], path: Path) -> bytes:
    """Serialise the index to disk in the one spelling that gets signed.

    Description: two builds of the same content must produce the same
      bytes, so the spelling is fixed here and nowhere else: two space
      indent, keys in the order the builder wrote them, non ASCII left as
      itself rather than escaped, and exactly one trailing newline. The
      signature covers these bytes, so a change to any of it invalidates
      every signature made before it.
    Inputs: document (dict). path (Path) - where to write.
    Output: bytes - what was written, so the caller can sign or hash the
      same object it wrote rather than re-reading the file.
    Example: write_index({"schema": SCHEMA}, tmp / "index.json")
    """
    payload = json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload
