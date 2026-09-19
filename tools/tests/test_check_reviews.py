"""The publish gate: a version publishes only with a review of its own bytes.

THE HOLE THESE TESTS CLOSE. The approval pull reviews the bytes it stages
and refuses to print the publish command on a blocked verdict, and the
committed artifact it writes is bound to the digest of those bytes. An
operator who edits the folder AFTER that review and commits gets bytes with
no committed review for them, and the build's own review of those bytes
wrote a verdict into the index without ever gating on it. So unreviewed
bytes published.

Every case here is a case the gate has to REFUSE, plus the two it has to
let through, because a gate that only ever says yes and a gate that only
ever says no are equally useless and look identical from a green run.

NO MODEL IS CALLED ANYWHERE IN THIS FILE, and none can be: the command
under test holds no key and imports no caller. That is the point of it
running in the verify job on a stranger's pull request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from index_builder import __main__ as cli

HANDLE = "adoom666"
SKILL = "probe"
VERSION = "1.0.0"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


def _index(path: Path, digest: str = DIGEST) -> Path:
    """Write an assembled index naming one published version.

    :param path: the directory to write into.
    :param digest: the folder digest the index claims for that version.
    :returns: the index file.
    """
    document = {"items": [{
        "id": f"{HANDLE}/{SKILL}",
        "publisher": HANDLE,
        "name": SKILL,
        "versions": [{"v": VERSION, "digest": digest}],
    }]}
    out = path / "index.unsigned.json"
    out.write_text(json.dumps(document), encoding="utf-8")
    return out


def _review(
    digest: str,
    *,
    verdict: str = "clean",
    override: bool = False,
) -> Dict[str, object]:
    """A committed review artifact, in the shape write_review leaves one."""
    document: Dict[str, object] = {
        "digest": digest,
        "status": "reviewed",
        "verdict": verdict,
        "summary": "reads the repository and says what is free to pick up.",
        "warnings": [],
        "model": "test/model",
        "reviewed_at": "2026-09-19T00:00:00Z",
    }
    if verdict != "clean":
        document["warnings"] = [{
            "kind": "credential_access",
            "detail": "SKILL.md tells the agent to read ~/.ssh/id_ed25519.",
            "file": "SKILL.md",
            "line": 6,
        }]
    if override:
        document["override"] = {
            "reason": "internal fixture, published deliberately",
            "by": HANDLE,
            "at": "2026-09-19T00:00:00Z",
        }
    return document


def _commit_review(root: Path, document: Optional[Dict[str, object]]) -> None:
    """Write a committed review under reviews/, or write none at all."""
    if document is None:
        return
    path = root / "reviews" / HANDLE / SKILL / f"{VERSION}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def _run(
    tmp_path: Path,
    committed: Optional[Dict[str, object]],
    *,
    index_digest: str = DIGEST,
) -> int:
    """Run the gate over one crafted repository and return its exit code."""
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    _commit_review(root, committed)
    index = _index(root, index_digest)
    return cli.main([
        "--repo-root", str(root), "check-reviews", "--index", str(index),
    ])


def test_a_version_with_no_committed_review_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """THE HOLE ITSELF. Bytes nobody reviewed must not publish.

    This is the shape an operator produces by editing the folder after the
    staged review, and it is the shape that passed before 2026-09-19.
    """
    assert _run(tmp_path, None) == 1
    printed = capsys.readouterr()
    assert cli.REFUSE_ABSENT in printed.err
    assert f"{HANDLE}/{SKILL} {VERSION}" in printed.err


def test_a_committed_review_of_other_bytes_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """The digest binding, and it is the assertion that goes red on a mutation.

    A review of different bytes is not a review of these bytes. Before this
    change it printed `stale, other bytes` and let the build through, which
    is the same outcome as having no review at all dressed as a finding.
    """
    assert _run(tmp_path, _review(OTHER_DIGEST)) == 1
    printed = capsys.readouterr()
    assert cli.REFUSE_STALE in printed.err


def test_the_refusal_names_both_digests(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """An operator cannot act on a refusal that does not say what differs."""
    assert _run(tmp_path, _review(OTHER_DIGEST)) == 1
    printed = capsys.readouterr()
    assert DIGEST[:12] in printed.err, "the folder digest is not in the message"
    assert OTHER_DIGEST[:12] in printed.err, "the reviewed digest is not in it"


def test_a_matching_committed_review_passes(tmp_path: Path) -> None:
    """The green case, so the refusals above are not the only outcome."""
    assert _run(tmp_path, _review(DIGEST)) == 0


def test_a_matching_blocked_review_with_no_override_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """A review that read these exact bytes and refused them still refuses."""
    assert _run(tmp_path, _review(DIGEST, verdict="blocked")) == 1
    printed = capsys.readouterr()
    assert cli.REFUSE_BLOCKED in printed.err


def test_a_matching_blocked_review_with_a_written_override_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """The override waves the build through and NEVER changes the verdict."""
    assert _run(tmp_path, _review(DIGEST, verdict="blocked", override=True)) == 0
    printed = capsys.readouterr()
    assert "blocked" in printed.out, (
        "the override hid the verdict; it must only decide whether the "
        "build stops, never what the review says"
    )


def test_a_review_published_in_the_live_index_does_not_approve_bytes(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """ONLY A COMMITTED REVIEW APPROVES. The ruling, written where it is kept.

    A review the live index carries for the same digest is good enough to
    save a model call, and it is not good enough to admit anything: the
    live index is the artifact this build replaces, so letting it approve
    bytes makes the gate's input its own output. The gate reads reviews/
    and nothing else, and this proves it by handing it an index that
    carries a clean review inline and no committed artifact at all.
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    document = {"items": [{
        "id": f"{HANDLE}/{SKILL}",
        "publisher": HANDLE,
        "name": SKILL,
        "versions": [{
            "v": VERSION,
            "digest": DIGEST,
            "review": _review(DIGEST),
        }],
    }]}
    index = root / "index.unsigned.json"
    index.write_text(json.dumps(document), encoding="utf-8")
    assert cli.main([
        "--repo-root", str(root), "check-reviews", "--index", str(index),
    ]) == 1
    assert cli.REFUSE_ABSENT in capsys.readouterr().err


def test_an_index_with_no_versions_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """A check that looked at nothing has to say it looked at nothing."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    index = root / "index.unsigned.json"
    index.write_text(json.dumps({"items": []}), encoding="utf-8")
    assert cli.main([
        "--repo-root", str(root), "check-reviews", "--index", str(index),
    ]) == 0
    assert "no review was checked" in capsys.readouterr().out


def test_every_refused_version_is_named_not_just_the_first(
    tmp_path: Path, capsys: pytest.CaptureFixture,
) -> None:
    """One run has to list every version that fails, or fixing them loops."""
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    versions: List[Dict[str, object]] = [
        {"v": "1.0.0", "digest": DIGEST},
        {"v": "2.0.0", "digest": OTHER_DIGEST},
    ]
    index = root / "index.unsigned.json"
    index.write_text(json.dumps({"items": [{
        "id": f"{HANDLE}/{SKILL}",
        "publisher": HANDLE,
        "name": SKILL,
        "versions": versions,
    }]}), encoding="utf-8")
    assert cli.main([
        "--repo-root", str(root), "check-reviews", "--index", str(index),
    ]) == 1
    printed = capsys.readouterr().err
    assert "1.0.0" in printed and "2.0.0" in printed
