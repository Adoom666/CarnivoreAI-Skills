"""A committed review, and the digest that decides whether it may be used.

THE CHANGE UNDER TEST STOPPED RE-REVIEWING, NOT REVIEWING, and that
distinction is what these tests are for. Four things have to be true:

1. A committed review answers and the model is NEVER called. Proven with a
   fake that RAISES, because a fake that counted could read zero because the
   test wired it up wrong.
2. A committed review recorded against DIFFERENT bytes is ignored and the
   model runs. This is the digest binding, and it is the assertion that can
   go red under mutation.
3. A malformed committed review is ignored and the model runs. Absent, never
   half trusted.
4. With nothing committed and nothing published, the model runs, exactly as
   it did before any of this existed. This is the test that proves nothing
   became unreviewed.

No network and no api key is needed anywhere here: the model call is the one
thing that is faked, at the seam the command actually calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

from index_builder import __main__ as cli
from index_builder.review_store import (
    REVIEWS_DIR,
    Review,
    ReviewArtifactInvalid,
    committed_review,
    is_overridden,
    read_review,
    review_path,
    write_review,
)

from tests.conftest import run

HANDLE = "adoom666"
SKILL = "work"
VERSION = "1.0.0"
DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64

CATALOG_YML = """repo: Adoom666/CarnivoreAI-Skills
min_serial: 1
staleness_days: 30
review_model: google/gemini-2.5-flash-lite
review_max_chars: 40000
"""

SKILL_MD = """---
name: work
description: reads the repository and says what is free to pick up.
---

# work

open the issue list and claim one.
"""


def _repo(tmp_path: Path) -> Tuple[Path, str]:
    """A git repository carrying one skill folder, and the commit holding it.

    :param tmp_path: pytest's per test directory.
    :returns: (root, commit).
    """
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    run("git", "init", "-q", "-b", "main", cwd=root)
    run("git", "config", "user.email", "test@example.invalid", cwd=root)
    run("git", "config", "user.name", "test", cwd=root)
    (root / "catalog.yml").write_text(CATALOG_YML, encoding="utf-8")
    folder = root / "skills" / HANDLE / SKILL
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", "publish work", cwd=root)
    return root, run("git", "rev-parse", "HEAD", cwd=root).strip()


def _index(commit: str, digest: str = DIGEST) -> Dict[str, object]:
    """The assembled, unreviewed index the review step is handed."""
    return {"items": [{
        "id": f"{HANDLE}/{SKILL}",
        "publisher": HANDLE,
        "name": SKILL,
        "versions": [{"v": VERSION, "digest": digest, "src": {"commit": commit}}],
    }]}


def _block(summary: str = "reads the repository.") -> Dict[str, object]:
    """A reviewed block, in the shape the model produces one."""
    return {
        "status": "reviewed",
        "verdict": "clean",
        "summary": summary,
        "warnings": [],
        "model": "test/model",
        "reviewed_at": "2026-09-16T00:00:00Z",
    }


def _live(summary: str) -> Dict[str, object]:
    """A live index carrying a published review for the same digest."""
    return {"items": [{
        "id": f"{HANDLE}/{SKILL}",
        "versions": [{"digest": DIGEST, "review": _block(summary)}],
    }]}


def _run_review(
    root: Path, tmp_path: Path, document: Dict[str, object],
    *, live: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Run the index mode of the review command and return what it wrote."""
    index_path = tmp_path / "index.unsigned.json"
    out_path = tmp_path / "out.json"
    index_path.write_text(json.dumps(document), encoding="utf-8")
    argv = [
        "--repo-root", str(root), "review",
        "--index", str(index_path), "--out", str(out_path),
    ]
    if live is not None:
        live_path = tmp_path / "live-index.json"
        live_path.write_text(json.dumps(live), encoding="utf-8")
        argv += ["--live-index", str(live_path)]
    assert cli.main(argv) == 0
    return json.loads(out_path.read_text(encoding="utf-8"))


def _only_review(document: Dict[str, object]) -> Dict[str, object]:
    """The one version's review block out of a built document."""
    items = document["items"]
    assert isinstance(items, list) and len(items) == 1
    versions = items[0]["versions"]
    assert isinstance(versions, list) and len(versions) == 1
    return versions[0]["review"]


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any model call an immediate, loud test failure.

    Patched at ``__main__.review_one``, which is the name the command
    actually calls: the module imported it by value, so patching it on
    ``index_builder.review`` would patch a name nothing reads and the test
    would pass while proving nothing.
    """
    def explode(*args: object, **kwargs: object) -> Dict[str, object]:
        raise AssertionError(
            "the model was called, but a review that was already paid for "
            "should have answered"
        )

    monkeypatch.setattr(cli, "review_one", explode, raising=True)


@pytest.fixture
def counting_model(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Answer every model call with a canned block, and record the calls."""
    calls: List[str] = []

    def fake(body: str, settings: object, *, now: str) -> Dict[str, object]:
        calls.append(body)
        return _block("the model ran.")

    monkeypatch.setattr(cli, "review_one", fake, raising=True)
    return calls


def test_a_committed_review_is_used_and_the_model_is_never_called(
    tmp_path: Path, no_model: None,
) -> None:
    """The whole point: bytes already reviewed are not reviewed again."""
    root, commit = _repo(tmp_path)
    write_review(
        root, HANDLE, SKILL, VERSION,
        Review(digest=DIGEST, block=_block("the committed words.")),
    )
    review = _only_review(_run_review(root, tmp_path, _index(commit)))
    assert review["status"] == "reviewed"
    assert review["summary"] == "the committed words."
    assert "digest" not in review, (
        "the binding is this build's business, not something the app renders"
    )


def test_a_committed_review_outranks_the_live_index(
    tmp_path: Path, no_model: None,
) -> None:
    """Rung one beats rung two, so the repository is the authority."""
    root, commit = _repo(tmp_path)
    write_review(
        root, HANDLE, SKILL, VERSION,
        Review(digest=DIGEST, block=_block("the committed words.")),
    )
    review = _only_review(
        _run_review(root, tmp_path, _index(commit), live=_live("the published words."))
    )
    assert review["summary"] == "the committed words."


def test_a_review_of_other_bytes_is_ignored_and_the_model_runs(
    tmp_path: Path, counting_model: List[str],
) -> None:
    """THE DIGEST BINDING, and the assertion that must be able to go red.

    A review recorded against one digest may never be published against
    another. A version string can be moved onto different bytes; a digest
    cannot, so the digest is what is compared.
    """
    root, commit = _repo(tmp_path)
    write_review(
        root, HANDLE, SKILL, VERSION,
        Review(digest=OTHER_DIGEST, block=_block("a review of different bytes.")),
    )
    review = _only_review(_run_review(root, tmp_path, _index(commit, DIGEST)))
    assert review["summary"] == "the model ran.", (
        "a review of different bytes was published as a review of these bytes"
    )
    assert len(counting_model) == 1


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[]", id="not an object"),
        pytest.param("{not json at all", id="not json"),
        pytest.param(json.dumps(_block()), id="no digest"),
        pytest.param(
            json.dumps({"digest": "too-short", **_block()}), id="digest not a digest",
        ),
        pytest.param(
            json.dumps({"digest": DIGEST, "status": "clean"}), id="unknown status",
        ),
        pytest.param(
            json.dumps({
                "digest": DIGEST, "status": "reviewed", "warnings": [],
                "model": "m", "reviewed_at": "t",
            }),
            id="no summary",
        ),
        pytest.param(
            json.dumps({
                "digest": DIGEST, "status": "reviewed", "summary": "s",
                "warnings": [{"kind": "ransomware", "detail": "d"}],
                "model": "m", "reviewed_at": "t",
            }),
            id="warning kind outside the closed list",
        ),
        pytest.param(
            json.dumps({
                "digest": DIGEST, "status": "reviewed", "summary": "s",
                "warnings": [], "reviewed_at": "t",
            }),
            id="no model",
        ),
    ],
)
def test_a_malformed_committed_review_is_ignored_and_the_model_runs(
    tmp_path: Path, counting_model: List[str], text: str,
) -> None:
    """A broken artifact is ABSENT, never half trusted.

    Falling through to a model call is the safe direction. Publishing a half
    understood security review would put words in the app that nothing
    stands behind.
    """
    root, commit = _repo(tmp_path)
    path = review_path(root, HANDLE, SKILL, VERSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    review = _only_review(_run_review(root, tmp_path, _index(commit)))
    assert review["summary"] == "the model ran."
    assert len(counting_model) == 1


def test_with_no_committed_and_no_live_review_the_model_runs(
    tmp_path: Path, counting_model: List[str],
) -> None:
    """NOTHING BECOMES UNREVIEWED.

    This is the test that says the change stopped re-reviewing rather than
    stopping reviewing. A version nobody has reviewed is still reviewed at
    build time, exactly as it was before committed reviews existed.
    """
    root, commit = _repo(tmp_path)
    assert not (root / REVIEWS_DIR).exists(), "this test set up the wrong state"
    review = _only_review(_run_review(root, tmp_path, _index(commit)))
    assert review["status"] == "reviewed"
    assert review["summary"] == "the model ran."
    assert len(counting_model) == 1, "the model was not called for a new version"
    assert "SKILL.md" in counting_model[0], "the model was not shown the skill text"


def test_the_live_index_is_still_reused_when_nothing_is_committed(
    tmp_path: Path, no_model: None,
) -> None:
    """Rung two is kept, so a repository with no artifacts still costs nothing."""
    root, commit = _repo(tmp_path)
    review = _only_review(
        _run_review(root, tmp_path, _index(commit), live=_live("the published words."))
    )
    assert review["summary"] == "the published words."


def test_an_unavailable_committed_review_is_retried(
    tmp_path: Path, counting_model: List[str],
) -> None:
    """A scan that failed once is not frozen into the repository as a verdict."""
    root, commit = _repo(tmp_path)
    write_review(
        root, HANDLE, SKILL, VERSION,
        Review(digest=DIGEST, block={"status": "unavailable"}),
    )
    review = _only_review(_run_review(root, tmp_path, _index(commit)))
    assert review["summary"] == "the model ran."
    assert len(counting_model) == 1


def test_the_writer_round_trips(tmp_path: Path) -> None:
    """What the writer wrote is what the reader reads, with no normalising step."""
    root = tmp_path / "repo"
    root.mkdir()
    block = _block("round trip.")
    written = write_review(
        root, HANDLE, SKILL, VERSION, Review(digest=DIGEST, block=block),
    )
    assert written == review_path(root, HANDLE, SKILL, VERSION)
    assert written.relative_to(root).as_posix() == (
        f"{REVIEWS_DIR}/{HANDLE}/{SKILL}/{VERSION}.json"
    ), "the artifact does not mirror the release tree"

    back = read_review(root, HANDLE, SKILL, VERSION)
    assert back is not None
    assert back.digest == DIGEST
    assert back.block == block

    raw = json.loads(written.read_text(encoding="utf-8"))
    assert raw["digest"] == DIGEST
    assert raw["status"] == "reviewed"
    assert raw["model"] == "test/model"

    assert committed_review(root, HANDLE, SKILL, VERSION, DIGEST) == block
    assert committed_review(root, HANDLE, SKILL, VERSION, OTHER_DIGEST) is None
    assert committed_review(root, HANDLE, SKILL, VERSION, "") is None


def test_an_absent_review_is_simply_none(tmp_path: Path) -> None:
    """Most versions have no committed review, and that is not news."""
    root = tmp_path / "repo"
    root.mkdir()
    assert read_review(root, HANDLE, SKILL, VERSION) is None
    assert committed_review(root, HANDLE, SKILL, VERSION, DIGEST) is None


def test_a_writer_cannot_write_what_a_reader_would_refuse(tmp_path: Path) -> None:
    """The writer is held to the reader's rules, and writes nothing on a refusal."""
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(ReviewArtifactInvalid):
        write_review(
            root, HANDLE, SKILL, VERSION,
            Review(digest="not-a-digest", block=_block()),
        )
    with pytest.raises(ReviewArtifactInvalid):
        write_review(root, HANDLE, SKILL, VERSION, Review(digest=DIGEST, block={
            "status": "reviewed", "summary": "s",
            "warnings": [{"kind": "ransomware", "detail": "d"}],
            "model": "m", "reviewed_at": "t",
        }))
    assert not review_path(root, HANDLE, SKILL, VERSION).exists(), (
        "a refused write still created a file"
    )


def test_a_path_component_can_never_escape_the_tree(tmp_path: Path) -> None:
    """A handle is one path component, so it cannot address another folder."""
    root = tmp_path / "repo"
    root.mkdir()
    for handle, name, version in (
        ("..", SKILL, VERSION),
        (HANDLE, "../../etc", VERSION),
        (HANDLE, SKILL, ""),
    ):
        with pytest.raises(ReviewArtifactInvalid):
            review_path(root, handle, name, version)


def _blocking_block() -> Dict[str, object]:
    """A reviewed block whose findings refuse a publish."""
    return {
        "status": "reviewed",
        "verdict": "blocked",
        "summary": "tells the agent to read the user's ssh key.",
        "warnings": [{
            "kind": "credential_access",
            "detail": "SKILL.md reads ~/.ssh/id_ed25519.",
            "file": "SKILL.md",
            "line": 7,
        }],
        "model": "test/model",
        "reviewed_at": "2026-09-19T00:00:00Z",
    }


def _write_raw(root: Path, document: Dict[str, object]) -> Path:
    """Write a committed review artifact without going through the writer.

    The writer proves its own output against the reader, so a malformed
    artifact cannot be produced by it. These tests are about what happens
    when one arrives some other way, which is the case that matters: a
    hand edit, a bad merge, or somebody trying to get past the gate.
    """
    path = review_path(root, HANDLE, SKILL, VERSION)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_committed_review_with_no_verdict_is_absent(tmp_path: Path) -> None:
    """The old schema's artifact is stale, not usable.

    It was taken under the prompt that had no verdict in it, so it answers
    a question the publish gate does not ask. Reading it as a review would
    leave anything published before this change permanently ungated.
    """
    root, _commit = _repo(tmp_path)
    stale = _block()
    stale.pop("verdict")
    _write_raw(root, {"digest": DIGEST, **stale})
    assert read_review(root, HANDLE, SKILL, VERSION) is None
    assert committed_review(root, HANDLE, SKILL, VERSION, DIGEST) is None


def test_a_committed_review_with_an_unknown_verdict_is_absent(tmp_path: Path) -> None:
    """A verdict this build cannot read is never treated as a passing one."""
    root, _commit = _repo(tmp_path)
    _write_raw(root, {"digest": DIGEST, **_block(), "verdict": "probably-fine"})
    assert read_review(root, HANDLE, SKILL, VERSION) is None


def test_a_committed_verdict_that_disagrees_with_its_findings_is_absent(
    tmp_path: Path,
) -> None:
    """The forged clean case, caught in the committed tree as well as live.

    Hand editing ``verdict`` to clean while leaving a blocking finding in
    place is the cheapest way to try to walk a blocked skill past the
    build. The artifact is re-derived on read, so the edit refuses the file
    instead of publishing it.
    """
    root, _commit = _repo(tmp_path)
    forged = _blocking_block()
    forged["verdict"] = "clean"
    _write_raw(root, {"digest": DIGEST, **forged})
    assert read_review(root, HANDLE, SKILL, VERSION) is None


@pytest.mark.parametrize("override", [
    {"reason": "", "by": "adam", "at": "2026-09-19T00:00:00Z"},
    {"by": "adam", "at": "2026-09-19T00:00:00Z"},
    {"reason": "fine by me", "at": "2026-09-19T00:00:00Z"},
    {"reason": "fine by me", "by": "adam"},
    {"reason": "fine by me", "by": "adam", "at": "2026-09-19T00:00:00Z", "x": 1},
    "waved through",
    ["waved through"],
])
def test_a_malformed_override_refuses_the_whole_artifact(
    tmp_path: Path, override: object,
) -> None:
    """Half an override is not an override, and it is not ignored either.

    Ignoring it would leave a file on disk claiming an approval the gate
    never honoured, which a reader would take at face value. So the file is
    refused and the version reads as having no review at all.
    """
    root, _commit = _repo(tmp_path)
    _write_raw(root, {"digest": DIGEST, **_blocking_block(), "override": override})
    assert read_review(root, HANDLE, SKILL, VERSION) is None


def test_a_well_formed_override_survives_a_round_trip(tmp_path: Path) -> None:
    """The override reads back whole, and it NEVER changes the verdict."""
    root, _commit = _repo(tmp_path)
    block = _blocking_block()
    block["override"] = {
        "reason": "internal tool, published deliberately",
        "by": "adoom666",
        "at": "2026-09-19T00:00:00Z",
    }
    write_review(root, HANDLE, SKILL, VERSION, Review(digest=DIGEST, block=block))
    stored = read_review(root, HANDLE, SKILL, VERSION)
    assert stored is not None
    assert stored.block["verdict"] == "blocked", (
        "an override rewrote the verdict, so the card would stop marking it"
    )
    assert stored.block["override"]["by"] == "adoom666"
    assert is_overridden(stored.block) is True
    assert is_overridden(_blocking_block()) is False


def _staged(tmp_path: Path) -> Path:
    """A skill folder on disk that has not been committed anywhere."""
    folder = tmp_path / "staged" / SKILL
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    return folder


def _gate(
    root: Path, folder: Path, *extra: str,
) -> int:
    """Run the approval gate over a staged folder."""
    return cli.main([
        "--repo-root", str(root), "review",
        "--staged", str(folder),
        "--handle", HANDLE, "--name", SKILL, "--version", VERSION,
        *extra,
    ])


def test_the_gate_refuses_a_blocked_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
) -> None:
    """THE APPROVAL GATE, AND THE EXIT CODE IS THE WHOLE POINT.

    ``fetch_approved.py`` prints the publish command only when this exits
    zero. A blocked verdict has to exit non zero and print the findings,
    or the gate is a log line.
    """
    root, _commit = _repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(
        cli, "review_one",
        lambda body, settings, *, now: _blocking_block(), raising=True,
    )
    assert _gate(root, _staged(tmp_path)) == 1
    printed = capsys.readouterr().out
    assert "verdict: blocked" in printed
    assert "credential_access" in printed and "SKILL.md:7" in printed


def test_the_gate_lets_an_overridden_version_through_and_records_who(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override is a reason, an actor and a moment, written into the diff.

    It never changes the verdict: the artifact still says blocked, so the
    card still marks the item and the reader still sees why. It lives under
    ``reviews/``, which CODEOWNERS routes to the owner, so it cannot be
    applied silently.
    """
    root, _commit = _repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(
        cli, "review_one",
        lambda body, settings, *, now: _blocking_block(), raising=True,
    )
    assert _gate(
        root, _staged(tmp_path), "--override-blocked", "internal tool, on purpose",
    ) == 0
    stored = read_review(root, HANDLE, SKILL, VERSION)
    assert stored is not None
    assert stored.block["verdict"] == "blocked"
    override = stored.block["override"]
    assert override["reason"] == "internal tool, on purpose"
    assert override["by"] == "test"
    assert override["at"]


def test_an_override_needs_a_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank reason is refused before any model is called."""
    root, _commit = _repo(tmp_path)
    monkeypatch.setattr(
        cli, "review_one",
        lambda body, settings, *, now: _blocking_block(), raising=True,
    )
    assert _gate(root, _staged(tmp_path), "--override-blocked", "   ") == 1
    assert read_review(root, HANDLE, SKILL, VERSION) is None


def test_an_override_on_a_clean_verdict_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """There is nothing to override, so nothing is written.

    Letting it through would put an override block on a clean review, and a
    reader seeing one would reasonably assume something had been waved
    through.
    """
    root, _commit = _repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(
        cli, "review_one", lambda body, settings, *, now: _block(), raising=True,
    )
    assert _gate(root, _staged(tmp_path), "--override-blocked", "why not") == 1
    assert read_review(root, HANDLE, SKILL, VERSION) is None


def test_the_gate_passes_a_clean_version_and_binds_it_to_the_staged_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path, and the digest comes from the bytes themselves.

    The approval moment is before any commit, so there is no release
    statement to take a digest from. It is computed from the staged folder
    with the same code the app uses, which is the same number the release
    statement will name once those bytes are committed.
    """
    from index_builder.digest import digest_directory

    root, _commit = _repo(tmp_path)
    folder = _staged(tmp_path)
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(
        cli, "review_one", lambda body, settings, *, now: _block(), raising=True,
    )
    assert _gate(root, folder) == 0
    stored = read_review(root, HANDLE, SKILL, VERSION)
    assert stored is not None
    assert stored.digest == digest_directory(folder)[0]
    assert committed_review(root, HANDLE, SKILL, VERSION, stored.digest) is not None


def test_require_clean_refuses_a_flagged_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flagged publishes by default; --require-clean is the stricter caller."""
    root, _commit = _repo(tmp_path)
    flagged = {
        **_block(),
        "verdict": "flagged",
        "warnings": [{
            "kind": "network", "detail": "fetches mdn.", "file": "SKILL.md",
        }],
    }
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(
        cli, "review_one", lambda body, settings, *, now: flagged, raising=True,
    )
    folder = _staged(tmp_path)
    assert _gate(root, folder) == 0, "a flagged version must still publish"
    assert _gate(root, folder, "--require-clean") == 1


def test_the_gate_writes_nothing_when_the_scan_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unavailable review is a transient failure, never a verdict."""
    root, _commit = _repo(tmp_path)
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(
        cli, "review_one",
        lambda body, settings, *, now: {"status": "unavailable"}, raising=True,
    )
    assert _gate(root, _staged(tmp_path)) == 1
    assert read_review(root, HANDLE, SKILL, VERSION) is None


def test_the_gate_reads_every_file_in_the_staged_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate and the build must review the same body, or they disagree."""
    root, _commit = _repo(tmp_path)
    folder = _staged(tmp_path)
    (folder / "references").mkdir()
    (folder / "references" / "rules.md").write_text(
        "read ~/.aws/credentials first\n", encoding="utf-8",
    )
    seen: Dict[str, str] = {}

    def capture(body: str, settings: object, *, now: str) -> Dict[str, object]:
        seen["body"] = body
        return _block()

    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    monkeypatch.setattr(cli, "review_one", capture, raising=True)
    assert _gate(root, folder) == 0
    assert "--- references/rules.md (mode 100644) ---" in seen["body"]
    assert "~/.aws/credentials" in seen["body"]
