"""A skill, a theme and a plugin assemble into one index, and hostile ones are refused.

Real minisign signatures from a throwaway key (see ``conftest``), real git
history, and folders taken from the shared vectors, so the folder a release
signs is one the hosted validator has an opinion on too.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pytest

from index_builder.assemble import assemble
from index_builder.digest import digest_directory
from index_builder.gate import gate_report
from index_builder.marketplace import build_marketplace
from index_builder.publishers import load_publishers
from index_builder.releases import ReleaseRefused, find_release_files, verify_release
from index_builder.statements import release_statement

from tests.conftest import requires_minisign, sign_bytes
from tests.test_builder import HANDLE, SKILL, SLUG, _commit
from tests.test_builder import catalog  # noqa: F401  (fixture)
from tests.test_kind_vectors import VECTORS, members_of

FOLDERS = {"theme": "themes", "plugin": "plugins"}


def _vector(vector_id: str) -> tuple[str, Dict[str, bytes]]:
    """Take a vector's name and files by id.

    :param vector_id: an id in the shared vectors file.
    :returns: (item name, members).
    """
    vector = next(v for v in VECTORS if v["id"] == vector_id)
    return vector["name"], members_of(vector)


def _publish(
    catalog: dict, tmp_path: Path, kind: str, name: str, members: Dict[str, bytes],
) -> None:
    """Commit a folder of one kind and a real signed release for it."""
    root = catalog["root"]
    folder = root / FOLDERS[kind] / HANDLE / name
    for path, data in members.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(data)
    commit = _commit(root, f"publish {name}")
    digest, _entries = digest_directory(folder)
    statement = release_statement(
        kind=kind, publisher=HANDLE, name=name, version="1.0.0", repo=SLUG,
        path=f"{FOLDERS[kind]}/{HANDLE}/{name}", commit=commit, digest=digest,
    )
    block = sign_bytes(statement, catalog["keypair"]["secret"], tmp_path)
    out = root / "releases" / HANDLE / name
    out.mkdir(parents=True)
    (out / "1.0.0.json").write_text(json.dumps({
        "statement": statement.decode("utf-8"),
        "sig": {k: block[k] for k in ("key_id", "sig", "tc", "gsig")},
        "commit": commit, "digest": digest,
    }), encoding="utf-8")
    _commit(root, f"release {name}")


def _build(root: Path):
    """Verify every release in the repository and assemble the index."""
    publishers = load_publishers(root)
    releases = [
        verify_release(root, p, publishers=publishers, repo_slug=SLUG)
        for p in find_release_files(root)
    ]
    return assemble(root, publishers=publishers, releases=releases,
                    repo_slug=SLUG, serial=1, generated_at="2026-09-30T00:00:00Z")


@requires_minisign
def test_a_skill_a_theme_and_a_plugin_assemble_into_one_index(
    catalog: dict, tmp_path: Path,  # noqa: F811
) -> None:
    """Three kinds, three folders, correct kinds, cards and no grade off a skill."""
    for kind, vector_id in (("theme", "theme-ok"), ("plugin", "plugin-ok")):
        name, members = _vector(vector_id)
        _publish(catalog, tmp_path, kind, name, members)
    built = _build(catalog["root"])
    items = {i["id"]: i for i in built.document["items"]}
    assert built.item_count == 3 and built.version_count == 3
    assert {i["kind"] for i in items.values()} == {"skill", "theme", "plugin"}

    theme = items[f"{HANDLE}/neon-test"]
    assert theme["versions"][0]["src"]["path"] == f"themes/{HANDLE}/neon-test"
    assert theme["card"] == {"title": "Neon Test", "brief": "A test theme."}
    assert theme["versions"][0]["scripts"] == 0 and "grade" not in theme["versions"][0]

    plugin = items[f"{HANDLE}/tool-pack"]
    assert plugin["versions"][0]["src"]["path"] == f"plugins/{HANDLE}/tool-pack"
    assert plugin["card"]["title"] == "tool-pack" and plugin["card"]["brief"]
    assert "grade" not in plugin["versions"][0]
    assert "grade" in items[f"{HANDLE}/{SKILL}"]["versions"][0]


@requires_minisign
@pytest.mark.parametrize("kind,vector_id", [
    ("plugin", "plugin-hooks-dir"), ("plugin", "plugin-hooks-key"),
    ("plugin", "plugin-mcp-json"), ("theme", "theme-effects-key"),
    ("theme", "theme-url-value"), ("theme", "theme-svg-file"),
])
def test_a_hostile_folder_signed_by_a_valid_key_is_refused(
    catalog: dict, tmp_path: Path, kind: str, vector_id: str,  # noqa: F811
) -> None:
    """A good signature does not launder a folder the kind rules refuse."""
    name, members = _vector(vector_id)
    _publish(catalog, tmp_path, kind, name, members)
    with pytest.raises(ReleaseRefused, match=f"{kind} rules"):
        _build(catalog["root"])


@requires_minisign
def test_an_executable_file_in_a_theme_is_refused(
    catalog: dict, tmp_path: Path,  # noqa: F811
) -> None:
    """The exec bit is a script by another name and a theme carries none."""
    name, members = _vector("theme-ok")
    root = catalog["root"]
    folder = root / "themes" / HANDLE / name
    folder.mkdir(parents=True)
    for path, data in members.items():
        (folder / path).write_bytes(data)
    (folder / "preview.png").chmod(0o755)
    commit = _commit(root, "publish exec theme")
    digest, _ = digest_directory(folder)
    statement = release_statement(
        kind="theme", publisher=HANDLE, name=name, version="1.0.0", repo=SLUG,
        path=f"themes/{HANDLE}/{name}", commit=commit, digest=digest,
    )
    block = sign_bytes(statement, catalog["keypair"]["secret"], tmp_path)
    out = root / "releases" / HANDLE / name
    out.mkdir(parents=True)
    (out / "1.0.0.json").write_text(json.dumps({
        "statement": statement.decode("utf-8"),
        "sig": {k: block[k] for k in ("key_id", "sig", "tc", "gsig")},
        "commit": commit, "digest": digest,
    }), encoding="utf-8")
    _commit(root, "release exec theme")
    with pytest.raises(ReleaseRefused, match="executable"):
        _build(root)


@requires_minisign
def test_one_name_under_two_kind_folders_is_refused(
    catalog: dict, tmp_path: Path,  # noqa: F811
) -> None:
    """An item id is exactly one kind, across all four folders."""
    name, members = _vector("theme-ok")
    _publish(catalog, tmp_path, "theme", name, members)
    clash = catalog["root"] / "plugins" / HANDLE / name
    clash.mkdir(parents=True)
    (clash / "x.md").write_text("x", encoding="utf-8")
    with pytest.raises(ReleaseRefused, match="exactly one kind"):
        _build(catalog["root"])


@requires_minisign
def test_theme_and_plugin_never_reach_the_marketplace_file(
    catalog: dict, tmp_path: Path,  # noqa: F811
) -> None:
    """Only the app's verified installer installs them, so the file skips both."""
    for kind, vector_id in (("theme", "theme-ok"), ("plugin", "plugin-ok")):
        name, members = _vector(vector_id)
        _publish(catalog, tmp_path, kind, name, members)
    built = _build(catalog["root"])
    document = build_marketplace(
        built.document["items"], repo_slug=SLUG,
        publishers=load_publishers(catalog["root"]),
    )
    assert [p["name"] for p in document["plugins"]] == [SKILL]


def test_a_changed_theme_or_plugin_folder_needs_its_release() -> None:
    """The pull request gate covers all four item folders."""
    for folder in ("themes", "plugins", "skills", "loadouts"):
        ok, lines = gate_report([f"{folder}/a/b/file"])
        assert not ok, folder
        assert any(f"{folder}" in line for line in lines)
    assert gate_report(["themes/a/b/theme.json", "releases/a/b/1.0.0.json"])[0]


def test_the_identity_marker_is_optional_single_line_and_carried(
    tmp_path: Path,
) -> None:
    """A non GitHub handle carries an identity marker into the publishers block."""
    from index_builder.assemble import _publishers_block

    (tmp_path / "publishers").mkdir()
    for handle, extra in (("plain", {}), ("mail", {"identity": "email"})):
        (tmp_path / "publishers" / f"{handle}.json").write_text(json.dumps({
            "handle": handle, "github_login": "Adoom666", "keys": [], **extra,
        }), encoding="utf-8")
    block = _publishers_block(load_publishers(tmp_path))
    assert block["mail"]["identity"] == "email" and "identity" not in block["plain"]
    (tmp_path / "publishers" / "bad.json").write_text(json.dumps({
        "handle": "bad", "github_login": "x", "keys": [], "identity": "a\nb",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        load_publishers(tmp_path)


def test_identity_is_email_or_absent_and_email_needs_no_github_login(
    tmp_path: Path,
) -> None:
    """Email publishers omit github_login; anything else still needs one."""
    (tmp_path / "publishers").mkdir()

    def write(handle: str, **body: object) -> None:
        (tmp_path / "publishers" / f"{handle}.json").write_text(
            json.dumps({"handle": handle, "keys": [], **body}), encoding="utf-8")

    write("mail", identity="email")
    write("plain", github_login="Adoom666")
    records = load_publishers(tmp_path)
    assert records["mail"].github_login == "" and records["mail"].identity == "email"
    for handle, body in (("nologin", {}), ("odd", {"identity": "<b>x</b>", "github_login": "x"}),
                         ("other", {"identity": "github", "github_login": "x"})):
        write(handle, **body)
        with pytest.raises(ValueError):
            load_publishers(tmp_path)
        (tmp_path / "publishers" / f"{handle}.json").unlink()
