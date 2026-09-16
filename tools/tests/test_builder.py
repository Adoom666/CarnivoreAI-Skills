"""The build job, proven against a real repository with real signatures.

Every test here builds a git repository in ``tmp_path``, generates a minisign
keypair with the real binary, signs a real release statement, and runs the
builder over it. Nothing is stubbed, because the thing under test is whether
this job will publish something it should not.

THE REFUSAL TESTS ARE THE POINT. A happy path test proves the job can say
yes. Only the refusals prove it can say no, and a build job that cannot say
no is a signing oracle.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from index_builder.assemble import assemble, write_index
from index_builder.config import load_config
from index_builder.gate import gate_report
from index_builder.publishers import load_index_key, load_publishers
from index_builder.releases import (
    ReleaseRefused,
    find_release_files,
    verify_release,
)
from index_builder.review import ReviewSettings, existing_review, review_one
from index_builder.serial import SerialRefused, decide_serial
from index_builder.statements import release_statement

from tests.conftest import requires_minisign, run, sign_bytes

HANDLE = "adoom666"
SKILL = "work"
SLUG = "Adoom666/CarnivoreAI-Skills"

SKILL_MD = """---
name: work
description: reads the repository and says what is free to pick up.
license: MIT
---

# work

open the issue list, read the approach sections, claim one with a draft pull
request.
"""

CATALOG_YML = """repo: Adoom666/CarnivoreAI-Skills
min_serial: 1
staleness_days: 30
review_model: google/gemini-2.5-flash-lite
review_max_chars: 40000
"""


def _git_repo(root: Path) -> None:
    """Make an empty git repository that can commit with no global config."""
    root.mkdir(parents=True, exist_ok=True)
    run("git", "init", "-q", "-b", "main", cwd=root)
    run("git", "config", "user.email", "test@example.invalid", cwd=root)
    run("git", "config", "user.name", "test", cwd=root)


def _commit(root: Path, message: str) -> str:
    """Stage everything and commit, returning the new commit sha."""
    run("git", "add", "-A", cwd=root)
    run("git", "commit", "-q", "-m", message, cwd=root)
    return run("git", "rev-parse", "HEAD", cwd=root).strip()


def _publishers_file(root: Path, pub_line: str) -> None:
    """Write the publisher declaration carrying one active key."""
    from index_builder.minisign_verify import parse_public_key

    key = parse_public_key(pub_line)
    (root / "publishers").mkdir(parents=True, exist_ok=True)
    (root / "publishers" / f"{HANDLE}.json").write_text(json.dumps({
        "handle": HANDLE,
        "github_login": "Adoom666",
        "keys": [{
            "key_id": key.key_id, "alg": "Ed25519", "pub": pub_line,
            "added": "2026-09-15", "status": "active",
        }],
    }, indent=2) + "\n", encoding="utf-8")


def _write_release(
    root: Path, *, version: str, commit: str, digest: str,
    secret: Path, tmp_path: Path,
) -> None:
    """Sign a release statement and write the release file."""
    statement = release_statement(
        kind="skill", publisher=HANDLE, name=SKILL, version=version,
        repo=SLUG, path=f"skills/{HANDLE}/{SKILL}", commit=commit, digest=digest,
    )
    block = sign_bytes(statement, secret, tmp_path)
    folder = root / "releases" / HANDLE / SKILL
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{version}.json").write_text(json.dumps({
        "statement": statement.decode("utf-8"),
        "sig": {k: block[k] for k in ("key_id", "sig", "tc", "gsig")},
        "commit": commit,
        "digest": digest,
    }, indent=2) + "\n", encoding="utf-8")


@pytest.fixture
def catalog(tmp_path: Path, keypair: dict) -> dict:
    """A repository with one published skill, signed by a real key.

    :returns: a dict with the repository root, the commit, the digest and
        the keypair, so a test can tamper with any of them.
    """
    from index_builder.digest import digest_directory

    root = tmp_path / "repo"
    _git_repo(root)
    (root / "catalog.yml").write_text(CATALOG_YML, encoding="utf-8")
    _publishers_file(root, keypair["pub"])
    skill_dir = root / "skills" / HANDLE / SKILL
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    commit = _commit(root, "publish work")
    digest, _entries = digest_directory(skill_dir)
    _write_release(
        root, version="1.0.0", commit=commit, digest=digest,
        secret=keypair["secret"], tmp_path=tmp_path,
    )
    _commit(root, "release work 1.0.0")
    return {"root": root, "commit": commit, "digest": digest, "keypair": keypair}


@requires_minisign
def test_a_signed_release_is_listed(catalog: dict) -> None:
    """The happy path: a proven release becomes one index item."""
    root = catalog["root"]
    publishers = load_publishers(root)
    releases = [
        verify_release(root, path, publishers=publishers, repo_slug=SLUG)
        for path in find_release_files(root)
    ]
    built = assemble(
        root, publishers=publishers, releases=releases, repo_slug=SLUG,
        serial=1, generated_at="2026-09-15T00:00:00Z",
    )
    assert built.item_count == 1
    assert built.version_count == 1
    item = built.document["items"][0]
    assert item["id"] == f"{HANDLE}/{SKILL}"
    assert item["latest"] == "1.0.0"
    assert item["card"]["title"] == "work"
    assert item["fm"]["license"] == "MIT"
    version = item["versions"][0]
    assert version["digest"] == catalog["digest"]
    assert version["src"]["commit"] == catalog["commit"]
    assert version["files"] == 1
    assert version["scripts"] == 0
    assert set(version["sig"]) == {"key_id", "sig", "tc", "gsig"}
    assert "review" not in version, "assemble must not invent a review"


@requires_minisign
def test_a_statement_whose_digest_is_not_the_tree_is_refused(
    catalog: dict, tmp_path: Path,
) -> None:
    """A correctly signed statement naming the wrong bytes is still refused.

    This is the check that makes the signature mean something. Without it a
    publisher could sign any digest they liked and the catalog would serve a
    commit whose contents nobody vouched for.
    """
    root = catalog["root"]
    _write_release(
        root, version="2.0.0", commit=catalog["commit"], digest="b" * 64,
        secret=catalog["keypair"]["secret"], tmp_path=tmp_path,
    )
    publishers = load_publishers(root)
    path = root / "releases" / HANDLE / SKILL / "2.0.0.json"
    with pytest.raises(ReleaseRefused) as refusal:
        verify_release(root, path, publishers=publishers, repo_slug=SLUG)
    assert "digests to" in str(refusal.value)


@requires_minisign
def test_a_release_signed_by_an_unknown_key_is_refused(
    catalog: dict, tmp_path: Path,
) -> None:
    """A real signature under a key this handle does not declare is refused."""
    other_secret = tmp_path / "other.key"
    other_public = tmp_path / "other.pub"
    run("minisign", "-G", "-W", "-s", str(other_secret), "-p", str(other_public))
    root = catalog["root"]
    _write_release(
        root, version="3.0.0", commit=catalog["commit"], digest=catalog["digest"],
        secret=other_secret, tmp_path=tmp_path,
    )
    publishers = load_publishers(root)
    path = root / "releases" / HANDLE / SKILL / "3.0.0.json"
    with pytest.raises(ReleaseRefused) as refusal:
        verify_release(root, path, publishers=publishers, repo_slug=SLUG)
    assert "not an active key" in str(refusal.value)


@requires_minisign
def test_a_statement_lifted_from_another_release_is_refused(catalog: dict) -> None:
    """A genuine statement pasted into a file naming something else is refused.

    Caught by the text comparison, BEFORE any cryptography, so the message
    sends the reader to the right place.
    """
    root = catalog["root"]
    source = root / "releases" / HANDLE / SKILL / "1.0.0.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    target = root / "releases" / HANDLE / SKILL / "9.9.9.json"
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    publishers = load_publishers(root)
    with pytest.raises(ReleaseRefused) as refusal:
        verify_release(root, target, publishers=publishers, repo_slug=SLUG)
    assert "is not the one these fields name" in str(refusal.value)


@requires_minisign
def test_a_handle_with_no_declaration_is_refused(catalog: dict) -> None:
    """A release under a handle with no publishers file cannot be verified."""
    root = catalog["root"]
    source = root / "releases" / HANDLE / SKILL / "1.0.0.json"
    stranger = root / "releases" / "stranger" / SKILL
    stranger.mkdir(parents=True)
    (stranger / "1.0.0.json").write_text(source.read_text(), encoding="utf-8")
    publishers = load_publishers(root)
    with pytest.raises(ReleaseRefused) as refusal:
        verify_release(
            root, stranger / "1.0.0.json", publishers=publishers, repo_slug=SLUG,
        )
    assert "publishers/stranger.json" in str(refusal.value)


@requires_minisign
def test_an_unreviewed_version_is_recorded_unavailable(catalog: dict) -> None:
    """With no api key, the review is an explicit unavailable, never blank."""
    settings = ReviewSettings(api_key=None, model="m", max_chars=1000)
    block = review_one("anything", settings, now="2026-09-15T00:00:00Z")
    assert block == {"status": "unavailable"}
    assert "summary" not in block, "an unavailable review carries no words"


def test_a_live_review_is_reused_for_the_same_digest() -> None:
    """The same bytes keep the same review, so a reinstall reads the same words."""
    live = {"items": [{
        "id": "adoom666/work",
        "versions": [{"digest": "a" * 64, "review": {
            "status": "reviewed", "summary": "reads files", "warnings": [],
            "model": "m", "reviewed_at": "2026-09-01T00:00:00Z",
        }}],
    }]}
    reused = existing_review(live, "adoom666/work", "a" * 64)
    assert reused is not None and reused["summary"] == "reads files"
    assert existing_review(live, "adoom666/work", "b" * 64) is None, (
        "different bytes must be reviewed again"
    )
    assert existing_review(None, "adoom666/work", "a" * 64) is None, (
        "with no verified live index there is nothing to reuse"
    )


def test_an_unavailable_live_review_is_not_reused() -> None:
    """A previous failure is retried, never carried forward as a verdict."""
    live = {"items": [{
        "id": "adoom666/work",
        "versions": [{"digest": "a" * 64, "review": {"status": "unavailable"}}],
    }]}
    assert existing_review(live, "adoom666/work", "a" * 64) is None


def test_the_first_deploy_takes_the_floor_from_catalog_yml(tmp_path: Path) -> None:
    """With nothing published, the serial is the configured floor."""
    decision = decide_serial(catalog_url="", index_key=None, min_serial=1)
    assert decision.serial == 1
    assert decision.outcome == "first-deploy"
    assert decision.live_document is None


def test_an_absent_live_index_is_a_first_deploy(tmp_path, static_server) -> None:
    """A 404 on both files is the first deploy, not a failure."""
    server = static_server(tmp_path / "site")
    decision = decide_serial(
        catalog_url=f"{server.base_url}/v1/index.json",
        index_key=None, min_serial=4,
    )
    assert decision.serial == 4
    assert decision.outcome == "first-deploy"


@requires_minisign
def test_a_verified_live_index_gives_the_next_serial(
    tmp_path: Path, keypair: dict, static_server,
) -> None:
    """A live index that verifies is counted from, and its serial goes up by one."""
    from index_builder.minisign_verify import parse_public_key

    site = tmp_path / "site" / "v1"
    site.mkdir(parents=True)
    payload = write_index({"schema": "carnivore.catalog.index/1", "serial": 11,
                           "generated_at": "2026-09-01T00:00:00Z", "items": []},
                          site / "index.json")
    run("minisign", "-S", "-W", "-s", str(keypair["secret"]),
        "-m", str(site / "index.json"), "-t", "carnivore index serial 11")
    assert payload
    server = static_server(tmp_path / "site")
    decision = decide_serial(
        catalog_url=f"{server.base_url}/v1/index.json",
        index_key=parse_public_key(keypair["pub"]), min_serial=1,
    )
    assert decision.serial == 12
    assert decision.outcome == "live-verified"
    assert decision.live_document is not None
    assert decision.live_document["serial"] == 11


@requires_minisign
def test_an_unverifiable_live_index_fails_the_build(
    tmp_path: Path, keypair: dict, static_server,
) -> None:
    """A live index under the wrong key stops the build rather than resetting it.

    Treating this as "no live index" and starting again at the floor is the
    move an attacker wants: a lower serial republished under the real key
    resets every client's rollback floor.
    """
    from index_builder.minisign_verify import parse_public_key

    site = tmp_path / "site" / "v1"
    site.mkdir(parents=True)
    write_index({"schema": "carnivore.catalog.index/1", "serial": 11,
                 "generated_at": "2026-09-01T00:00:00Z", "items": []},
                site / "index.json")
    run("minisign", "-S", "-W", "-s", str(keypair["secret"]),
        "-m", str(site / "index.json"))
    other_secret = tmp_path / "other.key"
    other_public = tmp_path / "other.pub"
    run("minisign", "-G", "-W", "-s", str(other_secret), "-p", str(other_public))
    stranger = [ln for ln in other_public.read_text().splitlines() if ln.strip()][-1]

    server = static_server(tmp_path / "site")
    with pytest.raises(SerialRefused) as refusal:
        decide_serial(
            catalog_url=f"{server.base_url}/v1/index.json",
            index_key=parse_public_key(stranger), min_serial=1,
        )
    assert "does not verify" in str(refusal.value)


@requires_minisign
def test_a_live_index_with_no_pinned_key_fails_the_build(
    tmp_path: Path, keypair: dict, static_server,
) -> None:
    """Reachable and uncheckable is refused for the same reason as unverifiable."""
    site = tmp_path / "site" / "v1"
    site.mkdir(parents=True)
    write_index({"schema": "carnivore.catalog.index/1", "serial": 3,
                 "generated_at": "2026-09-01T00:00:00Z", "items": []},
                site / "index.json")
    run("minisign", "-S", "-W", "-s", str(keypair["secret"]),
        "-m", str(site / "index.json"))
    server = static_server(tmp_path / "site")
    with pytest.raises(SerialRefused) as refusal:
        decide_serial(
            catalog_url=f"{server.base_url}/v1/index.json",
            index_key=None, min_serial=1,
        )
    assert "pins no index key" in str(refusal.value)


def test_half_a_published_index_is_refused(tmp_path: Path, static_server) -> None:
    """An index served with its signature removed is not a first deploy."""
    site = tmp_path / "site" / "v1"
    site.mkdir(parents=True)
    write_index({"schema": "carnivore.catalog.index/1", "serial": 3,
                 "generated_at": "2026-09-01T00:00:00Z", "items": []},
                site / "index.json")
    server = static_server(tmp_path / "site")
    with pytest.raises(SerialRefused) as refusal:
        decide_serial(
            catalog_url=f"{server.base_url}/v1/index.json",
            index_key=None, min_serial=1,
        )
    assert "is absent while the other is served" in str(refusal.value)


def test_the_gate_refuses_a_skill_change_with_no_release() -> None:
    """Editing a skill without releasing it fails the pull request check."""
    ok, lines = gate_report(["skills/adoom666/work/SKILL.md"])
    assert not ok
    assert any("REFUSED" in line for line in lines)


def test_the_gate_passes_a_paired_change() -> None:
    """A skill change with its release beside it merges."""
    ok, lines = gate_report([
        "skills/adoom666/work/SKILL.md",
        "releases/adoom666/work/1.1.0.json",
    ])
    assert ok
    assert any("also carries a release change" in line for line in lines)


def test_the_gate_pairs_per_skill_not_per_publisher() -> None:
    """Releasing one skill does not license an unreleased change to another."""
    ok, _lines = gate_report([
        "skills/adoom666/work/SKILL.md",
        "skills/adoom666/other/SKILL.md",
        "releases/adoom666/work/1.1.0.json",
    ])
    assert not ok


def test_the_gate_ignores_changes_that_are_not_skills() -> None:
    """Editing the tooling or a publisher file needs no release."""
    ok, _lines = gate_report(["tools/index_builder/sign.py", "publishers/x.json"])
    assert ok


@requires_minisign
def test_the_config_and_the_index_key_load(catalog: dict) -> None:
    """catalog.yml parses, and an unpinned index key reads as None, not an error."""
    root = catalog["root"]
    config = load_config(root)
    assert config.repo == SLUG
    assert config.min_serial == 1
    assert load_index_key(root) is None


@requires_minisign
def test_the_review_subcommand_commits_a_review_bound_to_the_verified_digest(
    catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single version mode, which is the call the approval flow will make.

    THE DIGEST MUST COME FROM THE RELEASE VERIFICATION, not from anything the
    caller passed in, because that is what makes the artifact safe to reuse
    later: a review committed for bytes nobody signed would be a review the
    build would happily publish against bytes somebody did.
    """
    from index_builder import __main__ as cli
    from index_builder.review_store import committed_review, read_review

    root = catalog["root"]
    seen: dict = {}

    def fake_review_one(body: str, settings: object, *, now: str) -> dict:
        """Stand in for the model, and remember what it was shown."""
        seen["body"] = body
        return {
            "status": "reviewed",
            "summary": "reads the repository and says what is free.",
            "warnings": [{"kind": "other", "detail": "reads the issue list."}],
            "model": "test/model",
            "reviewed_at": now,
        }

    monkeypatch.setattr(cli, "review_one", fake_review_one, raising=True)
    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")

    assert cli.main([
        "--repo-root", str(root), "review",
        "--handle", HANDLE, "--name", SKILL, "--version", "1.0.0",
    ]) == 0

    written = root / "reviews" / HANDLE / SKILL / "1.0.0.json"
    assert written.is_file(), "the review was not committed where the build looks"

    stored = read_review(root, HANDLE, SKILL, "1.0.0")
    assert stored is not None
    assert stored.digest == catalog["digest"], (
        "the review is not bound to the digest the release verification produced"
    )
    assert committed_review(root, HANDLE, SKILL, "1.0.0", catalog["digest"]) is not None
    assert committed_review(root, HANDLE, SKILL, "1.0.0", "b" * 64) is None
    assert "SKILL.md" in seen["body"], "the model was not shown the skill text"


@requires_minisign
def test_the_review_subcommand_refuses_a_version_with_no_release(
    catalog: dict, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No signed release means no proven bytes, so there is nothing to review."""
    from index_builder import __main__ as cli

    monkeypatch.setenv("OPENROUTER_SECRET_VALUE", "sk-test")
    assert cli.main([
        "--repo-root", str(catalog["root"]), "review",
        "--handle", HANDLE, "--name", SKILL, "--version", "9.9.9",
    ]) == 1
    assert not (catalog["root"] / "reviews").exists(), (
        "a refused review still wrote something"
    )


def test_the_review_command_refuses_half_a_request(tmp_path: Path) -> None:
    """The two modes do different things to different files, so neither is guessed.

    A command that quietly picked a mode from an incomplete argument set
    would, on the wrong guess, write an index where a maintainer asked for
    one review.
    """
    from index_builder import __main__ as cli

    assert cli.main([
        "--repo-root", str(tmp_path), "review", "--handle", HANDLE,
    ]) == 1
    assert cli.main(["--repo-root", str(tmp_path), "review"]) == 1
    assert cli.main([
        "--repo-root", str(tmp_path), "review",
        "--handle", HANDLE, "--name", SKILL, "--version", "1.0.0",
        "--index", str(tmp_path / "i.json"), "--out", str(tmp_path / "o.json"),
    ]) == 1
