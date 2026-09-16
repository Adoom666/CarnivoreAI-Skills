"""A review committed beside the release it describes, and what binds it there.

WHY THIS EXISTS. The security review costs a model call, and until now every
call was made at BUILD time: the job read the live index, carried forward a
review whose digest still matched, and called the model for everything else.
That works, but it puts the spend on the wrong side of the decision. Adam's
ruling of 2026-09-16 is that APPROVAL is what triggers the AI work, so a
submitted skill sits in a bucket until a human approves it, the scan runs
ONCE against the bytes being approved, and the result is committed. This
module is the committed half of that, and it is useful on its own: the build
now reads a review it already paid for instead of buying it again.

A REVIEW IS BOUND TO A DIGEST, NEVER TO A VERSION STRING. The artifact
carries the digest of the folder it actually read, and a build refuses to
reuse one whose digest is not the digest of the version being built. A
version string can be moved onto different bytes; a digest cannot. A review
of different bytes is not a review of these bytes, and publishing it as one
would put a model's description of a skill nobody is installing above the
skill somebody is.

A MALFORMED ARTIFACT IS ABSENT, NEVER TRUSTED. Every way this file can be
wrong, an unparseable file, a warning kind outside the closed list, a missing
summary, a digest that is not a digest, returns None and says in the job log
WHICH file and WHY. It never half reads one. The consequence of absent is a
model call, which is the safe direction; the consequence of trusting a broken
one is a security review the app renders that nothing stands behind.

AN UNAVAILABLE COMMITTED REVIEW IS NOT REUSED, for the same reason
``review.existing_review`` does not reuse one from the live index: a review
that could not be obtained is a transient failure, not a verdict, and
freezing one into the repository would mean those bytes were never reviewed
again. So the build retries it. The status is still WRITTEN when a writer
records one, because recording honestly that a scan failed is the point of
having the value at all.

WHY IT IS NOT UNDER ``releases/``. ``releases.find_release_files`` globs
``releases/*/*/*.json`` and every file it finds must verify as a signed
release statement. A review file dropped in that tree would be read as a
release, fail to parse as one, and refuse the entire build. So the artifact
mirrors that tree one level out, at ``reviews/<handle>/<name>/<version>.json``,
which keeps the pairing obvious without putting an unsigned file inside the
set of signed ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .review import (
    MAX_DETAIL_CHARS,
    MAX_SUMMARY_CHARS,
    MAX_WARNINGS,
    STATUS_REVIEWED,
    STATUS_UNAVAILABLE,
    WARNING_KINDS,
)
from .statements import DIGEST_RE

#: Where committed reviews live, mirroring ``releases/`` one level out.
REVIEWS_DIR = "reviews"

#: The field that binds a review to the bytes it read. It is not part of the
#: index's review block; it is what decides whether that block may be used.
DIGEST_FIELD = "digest"


class ReviewArtifactInvalid(Exception):
    """A committed review could not be read, carrying why for the job log."""


@dataclass(frozen=True)
class Review:
    """One committed review: the block, and the bytes it was taken over.

    - ``digest``: the folder digest this review actually read. A build
      compares it with the digest of the version being built and refuses
      the review on a mismatch.
    - ``block``: exactly the ``review`` block the index carries, with no
      ``digest`` in it. The binding is this module's business; what the app
      renders is unchanged by it.
    """

    digest: str
    block: Dict[str, object]


def _component(value: str, field: str) -> str:
    """Hold one path component to something that cannot escape the tree.

    :param value: the handle, name or version.
    :param field: which one, for the message.
    :returns: the value.
    :raises ReviewArtifactInvalid: when it is empty or carries a separator
        or a dot segment, either of which would let a caller address a file
        outside ``reviews/``.

    Example: _component("1.0.0", "version") -> "1.0.0"
    """
    if not value or value in (".", "..") or "/" in value or "\\" in value:
        raise ReviewArtifactInvalid(f"{field} {value!r} is not one path component")
    return value


def review_path(repo_root: Path, handle: str, name: str, version: str) -> Path:
    """Where one version's committed review lives.

    Description: mirrors the release tree, so the signed statement and the
      review of the same bytes sit at the same coordinates one directory
      apart and a human can see at a glance whether a version has one.
    Inputs: repo_root (Path). handle (str). name (str). version (str).
    Output: Path - ``<root>/reviews/<handle>/<name>/<version>.json``.
    Raises: ReviewArtifactInvalid when any component could escape the tree.
    Example: review_path(root, "adoom666", "sme", "1.0.0")
    """
    return (
        repo_root
        / REVIEWS_DIR
        / _component(handle, "handle")
        / _component(name, "name")
        / f"{_component(version, 'version')}.json"
    )


def parse_artifact(raw: object, where: str) -> Review:
    """Read a committed review strictly, or refuse the whole thing.

    Description: holds the artifact to the SAME rules the index's review
      block is held to by :mod:`index_builder.review`, plus the digest that
      binds it. STRICTLY: one bad field discards the whole file rather than
      the offending part, exactly as ``parse_review`` discards a whole model
      answer, because a half understood security review shown as a whole one
      is worse than none.
    Inputs: raw (object) - the parsed JSON. where (str) - the path, for the
      message.
    Output: Review.
    Raises: ReviewArtifactInvalid naming the file and the reason.
    Example: parse_artifact({"digest": "a" * 64, "status": "unavailable"}, "p")
    """
    if not isinstance(raw, dict):
        raise ReviewArtifactInvalid(f"{where}: is not a JSON object")

    digest = raw.get(DIGEST_FIELD)
    if not isinstance(digest, str) or not DIGEST_RE.match(digest):
        raise ReviewArtifactInvalid(
            f"{where}: {DIGEST_FIELD} is missing or is not a 64 character "
            f"hex digest, so there is nothing binding this review to any bytes"
        )

    status = raw.get("status")
    if status == STATUS_UNAVAILABLE:
        return Review(digest=digest, block={"status": STATUS_UNAVAILABLE})
    if status != STATUS_REVIEWED:
        raise ReviewArtifactInvalid(
            f"{where}: status is {status!r}, not {STATUS_REVIEWED!r} or "
            f"{STATUS_UNAVAILABLE!r}"
        )

    summary = raw.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewArtifactInvalid(f"{where}: carries no summary")

    model = raw.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ReviewArtifactInvalid(
            f"{where}: carries no model, so nobody can tell what reviewed it"
        )

    reviewed_at = raw.get("reviewed_at")
    if not isinstance(reviewed_at, str) or not reviewed_at.strip():
        raise ReviewArtifactInvalid(f"{where}: carries no reviewed_at")

    raw_warnings = raw.get("warnings", [])
    if not isinstance(raw_warnings, list):
        raise ReviewArtifactInvalid(f"{where}: warnings is not a list")
    if len(raw_warnings) > MAX_WARNINGS:
        raise ReviewArtifactInvalid(
            f"{where}: carries {len(raw_warnings)} warnings, more than the "
            f"{MAX_WARNINGS} this index carries"
        )

    warnings: List[Dict[str, str]] = []
    for entry in raw_warnings:
        if not isinstance(entry, dict):
            raise ReviewArtifactInvalid(f"{where}: a warning is not an object")
        kind = entry.get("kind")
        detail = entry.get("detail")
        if kind not in WARNING_KINDS:
            raise ReviewArtifactInvalid(
                f"{where}: the warning kind {kind!r} is not one of the seven "
                f"the app can render"
            )
        if not isinstance(detail, str) or not detail.strip():
            raise ReviewArtifactInvalid(f"{where}: a warning carries no detail")
        assert isinstance(kind, str)
        warnings.append({"kind": kind, "detail": detail.strip()[:MAX_DETAIL_CHARS]})

    return Review(
        digest=digest,
        block={
            "status": STATUS_REVIEWED,
            "summary": summary.strip()[:MAX_SUMMARY_CHARS],
            "warnings": warnings,
            "model": model.strip(),
            "reviewed_at": reviewed_at.strip(),
        },
    )


def read_review(
    repo_root: Path, handle: str, name: str, version: str,
) -> Optional[Review]:
    """Read one version's committed review, treating a broken one as absent.

    Description: an absent file returns None silently, because most versions
      have no committed review and that is not news. A file that EXISTS and
      cannot be read returns None too, but says so in the job log naming the
      path and the reason, because that one is a mistake somebody has to
      fix. Neither case is ever an exception: the caller's correct response
      to both is the same, call the model.
    Inputs: repo_root (Path). handle (str). name (str). version (str).
    Output: Review, or None when there is none to trust.
    Example: read_review(root, "adoom666", "sme", "1.0.0")
    """
    try:
        path = review_path(repo_root, handle, name, version)
    except ReviewArtifactInvalid as exc:
        print(f"::warning::{exc}")
        return None
    if not path.is_file():
        return None
    where = f"{REVIEWS_DIR}/{handle}/{name}/{version}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"::warning::{where}: could not be read as JSON ({exc}), so it "
              f"is treated as absent and this version is reviewed again")
        return None
    try:
        return parse_artifact(raw, where)
    except ReviewArtifactInvalid as exc:
        print(f"::warning::{exc}. It is treated as absent and this version "
              f"is reviewed again.")
        return None


def committed_review(
    repo_root: Path, handle: str, name: str, version: str, digest: str,
) -> Optional[Dict[str, object]]:
    """Find a committed review that describes exactly these bytes.

    Description: the digest gate. Mirrors ``review.existing_review`` for the
      committed tree: the review must exist, must parse, must carry the
      digest of the version being built, and must be a REVIEWED one. An
      unavailable review is not reused, so a scan that failed once is
      retried rather than frozen into the repository.
    Inputs: repo_root (Path). handle (str). name (str). version (str).
      digest (str) - the digest of the version being built.
    Output: the review block to publish, or None.
    Example: committed_review(root, "adoom666", "sme", "1.0.0", digest)
    """
    found = read_review(repo_root, handle, name, version)
    if found is None:
        return None
    if not digest or found.digest != digest:
        print(
            f"::warning::{REVIEWS_DIR}/{handle}/{name}/{version}.json reviewed "
            f"digest {found.digest[:12]}, but this version's digest is "
            f"{(digest or 'unknown')[:12]}. A review of different bytes is not "
            f"a review of these bytes, so it is ignored and the model runs."
        )
        return None
    if found.block.get("status") != STATUS_REVIEWED:
        return None
    return found.block


def write_review(
    repo_root: Path, handle: str, name: str, version: str, review: Review,
) -> Path:
    """Commit one version's review beside where its release statement goes.

    Description: writes the review block and the digest that binds it, in
      the same spelling the index is written in, so a file written here and
      a block read back from it are the same thing with no normalisation
      step in between. The parent directories are created; an existing file
      is replaced, because re-reviewing the same bytes is how a corrected
      scan lands.
    Inputs: repo_root (Path). handle (str). name (str). version (str).
      review (Review) - the block and the digest it was taken over.
    Output: Path - what was written.
    Raises: ReviewArtifactInvalid when the review does not hold to the same
      rules a read one is held to, so this function can never write a file
      that ``read_review`` would then refuse.
    Example: write_review(root, "adoom666", "sme", "1.0.0", review)
    """
    path = review_path(repo_root, handle, name, version)
    document: Dict[str, object] = {DIGEST_FIELD: review.digest}
    document.update(review.block)
    # prove the artifact against the read path before it lands, so a writer
    # can never leave a file the build would log as malformed.
    parse_artifact(document, str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
    )
    return path
