"""Release statements, and the only reason this job will list a version.

THE WHOLE SECURITY OF THE CATALOG IS IN THIS FILE. Everything else assembles
JSON. This is where a version is either proven or refused, and it is proven
against the repository's own git history rather than against anything the
contributor wrote down.

WHY THE STATEMENT LIVES OUTSIDE THE SKILL FOLDER. The statement names the
folder's digest. If it lived inside the folder it would be part of what is
being digested, and no digest could ever be correct: the file changes the
number it is trying to state. So releases live at
``releases/<handle>/<name>/<version>.json`` and the skill folder stays
exactly what gets installed.

WHAT ONE RELEASE FILE HAS TO SURVIVE, IN THIS ORDER:

1. It parses, and every field has the shape it claims.
2. The statement text it carries is EXACTLY the bytes these fields render
   to. A genuine statement for skill A pasted into a file that names skill B
   fails here, before any cryptography runs, so the log says "this is not
   the statement these fields name" rather than "bad signature" and sends
   the reader to the right place.
3. The signature verifies under an ACTIVE key belonging to THAT handle. Not
   any key in the repository: the handle's own. A key that is not the
   handle's cannot release under the handle's name.
4. The commit it names is in this repository and is an ancestor of HEAD.
   A commit that exists only on somebody's fork or on a closed pull request
   is not history this repository is willing to publish.
5. The folder at that commit, checked out and re-digested with the app's OWN
   digest function, produces the digest the statement signed.

Any one of those failing refuses the version. There is no partial listing
and no "list it as unverified": an unverified version in the index is a
version somebody will install.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .digest import DigestEntry, digest_directory
from .minisign_verify import (
    MinisignFormatError,
    PublicKey,
    Signature,
    parse_signature,
    verify,
)
from .publishers import PublisherRecord
from .statements import COMMIT_RE, DIGEST_RE, release_statement

#: Where release statements live, one folder per handle.
RELEASES_DIR = "releases"

#: Where the skill folders themselves live.
SKILLS_DIR = "skills"

#: The only kind this catalog publishes today. The app refuses anything
#: else, so writing one would be publishing something nobody can install.
KIND_SKILL = "skill"

#: A version is listed as a script bearer when a member sits under this
#: folder or carries the owner execute bit. Both are counted because the
#: app's install core refuses either one until the consent slice ships.
SCRIPTS_PREFIX = "scripts/"

#: The mode string the digest uses for an executable member.
MODE_EXECUTABLE = "100755"


class ReleaseRefused(Exception):
    """One release could not be proven, with the reason a human needs.

    Raised rather than returned because every caller's correct response is
    the same: stop, print this, and do not publish. A refusal that could be
    ignored by a caller that forgot to check would be a hole.
    """


@dataclass(frozen=True)
class VerifiedRelease:
    """One version this job is willing to publish.

    - ``handle``, ``name``, ``version``: the identity, all three taken
      from the signed statement rather than from the file's path.
    - ``commit``: the 40 hex commit whose tree was re-digested.
    - ``digest``: the digest the statement signed and the tree produced.
    - ``entries``: the digest entries, which is where the file count, the
      byte size and the script count come from.
    - ``sig``: the four field signature block for the index.
    - ``statement``: the exact bytes that were signed.
    - ``published_at``: the commit's own committer date, in UTC.
    - ``size``, ``files``, ``scripts``: counts derived from the entries.
    """

    handle: str
    name: str
    version: str
    commit: str
    digest: str
    entries: Tuple[DigestEntry, ...]
    sig: Dict[str, str]
    statement: bytes
    published_at: str
    size: int
    files: int
    scripts: int


def _git(repo_root: Path, *args: str) -> str:
    """Run one git command in the repository and return its stdout.

    :param repo_root: the repository to run in.
    :param args: the git arguments, already split.
    :returns: stdout, stripped of the trailing newline.
    :raises ReleaseRefused: when git exits non zero, carrying its stderr.

    Every git call in this module goes through here so that no caller can
    read a zero exit out of a command whose stderr it discarded.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ReleaseRefused(
            f"git {' '.join(args)} failed: {result.stderr.strip() or 'no stderr'}"
        )
    return result.stdout.rstrip("\n")


def _require(condition: bool, message: str) -> None:
    """Refuse with a message unless the condition holds.

    :param condition: what must be true.
    :param message: what to say when it is not.
    :raises ReleaseRefused: when the condition is false.
    """
    if not condition:
        raise ReleaseRefused(message)


def _signature_block(raw: object, where: str) -> Dict[str, str]:
    """Validate the four field signature block a release file carries.

    :param raw: the parsed ``sig`` value.
    :param where: the file path, for the message.
    :returns: the block with exactly the four fields, as strings.
    :raises ReleaseRefused: when a field is missing or the wrong type.

    ``tc`` may be empty, which is what minisign writes when a signature
    was made with no trusted comment. The other three may not.
    """
    _require(isinstance(raw, dict), f"{where}: sig is not a mapping")
    assert isinstance(raw, dict)
    block: Dict[str, str] = {}
    for field in ("key_id", "sig", "tc", "gsig"):
        value = raw.get(field)
        _require(isinstance(value, str), f"{where}: sig.{field} is not a string")
        assert isinstance(value, str)
        if field != "tc":
            _require(bool(value), f"{where}: sig.{field} is empty")
        block[field] = value
    return block


def _as_signature(block: Dict[str, str], where: str) -> Signature:
    """Rebuild a minisign Signature from the index's four field block.

    Description: the index carries a signature as four fields rather than
      as a whole ``.minisig`` file, so this reassembles the two line file
      the parser expects. ``sig`` is line two of the original file
      verbatim, ``tc`` is the trusted comment text without its prefix and
      ``gsig`` is the base64 of the raw 64 byte global signature, which is
      exactly line four.
    Inputs: block (dict) - the four validated fields. where (str) - the
      file path, for the message.
    Output: Signature.
    Raises: ReleaseRefused when the reassembled file does not parse.
    Example: _as_signature(block, "releases/a/b/1.0.0.json").key_id
    """
    text = (
        "untrusted comment: signature from the index builder\n"
        f"{block['sig']}\n"
        f"trusted comment: {block['tc']}\n"
        f"{block['gsig']}\n"
    )
    try:
        return parse_signature(text)
    except MinisignFormatError as exc:
        raise ReleaseRefused(f"{where}: the signature block is malformed: {exc}") from exc


def _key_for(
    publisher: PublisherRecord, signature: Signature, where: str,
) -> PublicKey:
    """Find the handle's own active key that this signature names.

    :param publisher: the handle's declaration.
    :param signature: the parsed signature, carrying the key id it claims.
    :param where: the file path, for the message.
    :returns: the pinned public key.
    :raises ReleaseRefused: when the handle has no such active key.

    The key is looked up by the id the SIGNATURE names, and then the
    verifier checks the id again against the key it is handed, so a
    signature cannot borrow a key it does not name.
    """
    key = publisher.active_keys.get(signature.key_id)
    if key is None:
        known = ", ".join(sorted(publisher.active_keys)) or "none"
        raise ReleaseRefused(
            f"{where}: signed by key {signature.key_id} "
            f"which is not an active key of {publisher.handle} "
            f"(active keys: {known})"
        )
    return key


def _checked_out_digest(
    repo_root: Path, commit: str, relpath: str, where: str,
) -> Tuple[str, Tuple[DigestEntry, ...]]:
    """Re-digest a skill folder as it stood at one commit.

    Description: adds a detached worktree at the commit in a temporary
      directory, runs the app's OWN ``digest_directory`` over the folder,
      and removes the worktree whether or not the digest succeeded. Using
      the app's function rather than a git tree walk is the point: the
      number the publisher signed and the number the app will compute
      after it downloads the tarball have to come from the same code, and
      the shared vector file proves this copy is that code.
    Inputs: repo_root (Path). commit (str) - 40 hex. relpath (str) - the
      folder, relative to the repository root. where (str) - the release
      file, for the message.
    Output: (digest hex, the entries).
    Raises: ReleaseRefused when the worktree cannot be made or the folder
      is not there at that commit.
    Example: _checked_out_digest(root, sha, "skills/adoom666/work", where)
    """
    with tempfile.TemporaryDirectory(prefix="carnivore-release-") as tmp:
        checkout = Path(tmp) / "tree"
        _git(repo_root, "worktree", "add", "--detach", "--quiet",
             str(checkout), commit)
        try:
            folder = checkout / relpath
            _require(
                folder.is_dir(),
                f"{where}: {relpath} is not a folder at commit {commit}",
            )
            return digest_directory(folder)
        finally:
            subprocess.run(
                ["git", "-C", str(repo_root), "worktree", "remove",
                 "--force", str(checkout)],
                capture_output=True, text=True, check=False,
            )


def verify_release(
    repo_root: Path,
    path: Path,
    *,
    publishers: Dict[str, PublisherRecord],
    repo_slug: str,
) -> VerifiedRelease:
    """Prove one release file, or refuse it with the reason.

    Description: runs the five checks named in the module docstring, in
      that order. The identity it returns comes from the SIGNED statement
      fields, never from the file's own path, so a release file moved into
      another handle's folder is caught by the path check below rather
      than quietly publishing under the folder it was moved to.
    Inputs: repo_root (Path). path (Path) - the release file.
      publishers (dict) - every declared publisher, by handle.
      repo_slug (str) - ``owner/repo``, which the statement signs.
    Output: VerifiedRelease.
    Raises: ReleaseRefused with a message naming the file and the failure.
    Example: verify_release(root, Path("releases/adoom666/work/1.0.0.json"),
      publishers=records, repo_slug="Adoom666/CarnivoreAI-Skills")
    """
    where = str(path.relative_to(repo_root))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseRefused(f"{where}: cannot be read as JSON: {exc}") from exc
    _require(isinstance(raw, dict), f"{where}: is not a JSON object")

    handle = path.parent.parent.name
    name = path.parent.name
    version = path.stem

    publisher = publishers.get(handle)
    _require(
        publisher is not None,
        f"{where}: there is no publishers/{handle}.json, so nothing can "
        f"verify a release under that handle",
    )
    assert publisher is not None

    commit = raw.get("commit")
    digest = raw.get("digest")
    statement_text = raw.get("statement")
    _require(
        isinstance(commit, str) and bool(COMMIT_RE.match(commit)),
        f"{where}: commit must be 40 lowercase hex",
    )
    _require(
        isinstance(digest, str) and bool(DIGEST_RE.match(digest)),
        f"{where}: digest must be 64 lowercase hex",
    )
    _require(
        isinstance(statement_text, str) and bool(statement_text),
        f"{where}: statement is missing",
    )
    assert isinstance(commit, str) and isinstance(digest, str)
    assert isinstance(statement_text, str)

    sig_block = _signature_block(raw.get("sig"), where)
    skill_path = f"{SKILLS_DIR}/{handle}/{name}"

    try:
        expected = release_statement(
            kind=KIND_SKILL,
            publisher=handle,
            name=name,
            version=version,
            repo=repo_slug,
            path=skill_path,
            commit=commit,
            digest=digest,
        )
    except ValueError as exc:
        raise ReleaseRefused(f"{where}: these fields cannot form a statement: {exc}") from exc

    if statement_text.encode("utf-8") != expected:
        raise ReleaseRefused(
            f"{where}: the statement it carries is not the one these fields "
            f"name; a statement signed for one release cannot be reused for "
            f"another"
        )

    signature = _as_signature(sig_block, where)
    key = _key_for(publisher, signature, where)
    try:
        ok = verify(expected, signature, key, expect_prehashed=True)
    except MinisignFormatError as exc:
        raise ReleaseRefused(f"{where}: signature could not be checked: {exc}") from exc
    _require(
        ok,
        f"{where}: the signature does not verify under {handle}'s key "
        f"{signature.key_id}",
    )

    _git(repo_root, "cat-file", "-e", f"{commit}^{{commit}}")
    ancestor = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True, text=True, check=False,
    )
    _require(
        ancestor.returncode == 0,
        f"{where}: commit {commit} is not an ancestor of HEAD, so it is not "
        f"history this repository publishes",
    )

    actual_digest, entries = _checked_out_digest(repo_root, commit, skill_path, where)
    _require(
        actual_digest == digest,
        f"{where}: the folder at {commit} digests to {actual_digest}, not the "
        f"{digest} the statement signed",
    )

    published_at = _git(repo_root, "show", "-s", "--format=%cI", commit)
    size = sum(
        _entry_size(repo_root, commit, skill_path, entry) for entry in entries
    )

    scripts = sum(
        1 for entry in entries
        if entry.relpath.startswith(SCRIPTS_PREFIX) or entry.mode == MODE_EXECUTABLE
    )

    return VerifiedRelease(
        handle=handle,
        name=name,
        version=version,
        commit=commit,
        digest=digest,
        entries=entries,
        sig=sig_block,
        statement=expected,
        published_at=_to_utc_z(published_at),
        size=size,
        files=len(entries),
        scripts=scripts,
    )


def _entry_size(
    repo_root: Path, commit: str, relpath: str, entry: DigestEntry,
) -> int:
    """Read one member's byte size out of the git object database.

    :param repo_root: the repository.
    :param commit: the commit the folder was digested at.
    :param relpath: the skill folder, relative to the root.
    :param entry: the digest entry naming the member.
    :returns: the blob's size in bytes.
    :raises ReleaseRefused: when git cannot size the object.

    Sized from the object database rather than from the temporary
    checkout, because the checkout is gone by the time the counts are
    wanted and re-making it to run ``stat`` would double the work.
    """
    text = _git(repo_root, "cat-file", "-s", f"{commit}:{relpath}/{entry.relpath}")
    try:
        return int(text)
    except ValueError as exc:
        raise ReleaseRefused(
            f"git reported a non numeric size {text!r} for {entry.relpath}"
        ) from exc


def _to_utc_z(iso_text: str) -> str:
    """Normalise a git committer date to an ISO 8601 UTC instant.

    :param iso_text: what ``git show -s --format=%cI`` printed.
    :returns: the same instant spelled ``YYYY-MM-DDTHH:MM:SSZ``.

    The index is read by a client that parses this with
    ``datetime.fromisoformat``, which accepts both spellings; normalising
    means two commits made in two time zones sort the way they read.

    Example: _to_utc_z("2026-09-15T18:04:11-04:00") -> "2026-09-15T22:04:11Z"
    """
    return (
        datetime.fromisoformat(iso_text)
        .astimezone(timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def find_release_files(repo_root: Path, handle: Optional[str] = None) -> List[Path]:
    """List every release file in the repository, in a stable order.

    :param repo_root: the repository root.
    :param handle: when given, only that handle's releases.
    :returns: the paths, sorted, so two builds see the same order.

    Example: find_release_files(Path("."))[0].name -> "1.0.0.json"
    """
    folder = repo_root / RELEASES_DIR
    if handle is not None:
        folder = folder / handle
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*/*/*.json" if handle is None else "*/*.json"))
