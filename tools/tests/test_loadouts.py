"""A ``kind: loadout`` item is indexed when its members check out, and refused when not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from index_builder.assemble import assemble
from index_builder.digest import digest_directory
from index_builder.publishers import load_publishers
from index_builder.releases import ReleaseRefused, find_release_files, verify_release
from index_builder.statements import release_statement

from tests.conftest import requires_minisign, sign_bytes
from tests.test_builder import HANDLE, SKILL, SLUG, _commit
from tests.test_builder import catalog  # noqa: F401  (fixture)

PACK = "starter-pack"


def _publish_loadout(catalog: dict, tmp_path: Path, members: list) -> None:
    """Commit a loadout folder and a real signed release for it."""
    root = catalog["root"]
    folder = root / "loadouts" / HANDLE / PACK
    folder.mkdir(parents=True)
    (folder / "loadout.json").write_text(json.dumps({
        "schema": "carnivore.catalog.loadout/1",
        "name": "starter pack",
        "description": "the one skill this catalog has, as a pack",
        "members": members,
    }), encoding="utf-8")
    commit = _commit(root, "publish pack")
    digest, _entries = digest_directory(folder)
    statement = release_statement(
        kind="loadout", publisher=HANDLE, name=PACK, version="1.0.0", repo=SLUG,
        path=f"loadouts/{HANDLE}/{PACK}", commit=commit, digest=digest,
    )
    block = sign_bytes(statement, catalog["keypair"]["secret"], tmp_path)
    out = root / "releases" / HANDLE / PACK
    out.mkdir(parents=True)
    (out / "1.0.0.json").write_text(json.dumps({
        "statement": statement.decode("utf-8"),
        "sig": {k: block[k] for k in ("key_id", "sig", "tc", "gsig")},
        "commit": commit, "digest": digest,
    }), encoding="utf-8")
    _commit(root, "release pack")


def _build(root: Path):
    publishers = load_publishers(root)
    releases = [
        verify_release(root, p, publishers=publishers, repo_slug=SLUG)
        for p in find_release_files(root)
    ]
    return assemble(root, publishers=publishers, releases=releases,
                    repo_slug=SLUG, serial=1, generated_at="2026-09-28T00:00:00Z")


@requires_minisign
def test_a_valid_loadout_is_indexed(catalog: dict, tmp_path: Path) -> None:  # noqa: F811
    """Members pinned to the indexed version and digest give a loadout item."""
    _publish_loadout(catalog, tmp_path, [
        {"id": f"{HANDLE}/{SKILL}", "version": "1.0.0", "digest": catalog["digest"]},
    ])
    built = _build(catalog["root"])
    assert built.item_count == 2
    item = next(i for i in built.document["items"] if i["kind"] == "loadout")
    assert item["id"] == f"{HANDLE}/{PACK}"
    assert item["card"]["title"] == "starter pack"
    assert item["versions"][0]["src"]["path"] == f"loadouts/{HANDLE}/{PACK}"
    assert item["versions"][0]["scripts"] == 0
    assert "grade" not in item["versions"][0]


@requires_minisign
def test_a_loadout_pinning_a_wrong_digest_is_refused(
    catalog: dict, tmp_path: Path,  # noqa: F811
) -> None:
    """A member digest that is not the indexed one fails the whole build."""
    _publish_loadout(catalog, tmp_path, [
        {"id": f"{HANDLE}/{SKILL}", "version": "1.0.0", "digest": "0" * 64},
    ])
    with pytest.raises(ReleaseRefused, match="is not the indexed"):
        _build(catalog["root"])
