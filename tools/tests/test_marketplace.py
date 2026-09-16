"""The Claude plugin marketplace file, held to the schema the CLI reads.

THE SCHEMA IS NOT GUESSED HERE. Every required field asserted below is the
one documented at https://code.claude.com/docs/en/plugin-marketplaces, read
on 2026-09-15 against Claude Code 2.1.266: the file lives at
``.claude-plugin/marketplace.json`` in the root of the repository that was
added, the document requires ``name``, ``owner`` and ``plugins``, and each
plugin entry requires ``name`` and ``source``, where a same repository
``source`` is a path that MUST begin with ``./`` and resolves against the
marketplace root rather than against the ``.claude-plugin`` directory.

The single skill shape this generator emits is documented at
https://code.claude.com/docs/en/plugins-reference under Skill Discovery: a
plugin directory holding a ``SKILL.md`` at its root, no ``skills/``
subdirectory and no manifest loads as one skill. It was also proven against
the real CLI before this generator was written; ``claude plugin details``
reported ``Skills (1)`` for a plugin whose source was a bare skill folder.

THE REFUSALS ARE THE POINT, again. A generator that can only say yes would
happily publish a marketplace listing a skill nobody released.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from index_builder.assemble import assemble
from index_builder.marketplace import (
    MARKETPLACE_NAME,
    MARKETPLACE_PATH,
    MarketplaceRefused,
    build_marketplace,
    owner_login,
    render,
    staleness,
    write_marketplace,
)
from index_builder.publishers import PublisherRecord, load_publishers
from index_builder.releases import find_release_files, verify_release

from tests.conftest import requires_minisign
from tests.test_builder import SLUG, catalog  # noqa: F401

HANDLE = "adoom666"


def _publisher(handle: str = HANDLE, login: str = "Adoom666") -> PublisherRecord:
    """A publisher record with no keys, which this module never looks at.

    :param handle: the folder name.
    :param login: the GitHub login the entries quote.
    :returns: the record.
    """
    return PublisherRecord(
        handle=handle, github_login=login, keys=(), active_keys={},
    )


def _item(name: str, *, handle: str = HANDLE, latest: str = "1.0.0") -> dict:
    """One assembled index item, in the shape assemble() writes.

    :param name: the skill folder name.
    :param handle: the publishing handle.
    :param latest: the version the entry should carry.
    :returns: the item.
    """
    return {
        "id": f"{handle}/{name}",
        "kind": "skill",
        "name": name,
        "publisher": handle,
        "latest": latest,
        "card": {"title": name, "brief": f"{name} does one thing."},
        "fm": {"description": f"{name} does one thing. Then it stops."},
        "versions": [],
    }


def test_the_document_carries_the_three_required_top_level_fields() -> None:
    """name, owner and plugins, per the marketplace schema documentation."""
    document = build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    assert set(document) == {"name", "owner", "plugins"}
    assert document["name"] == MARKETPLACE_NAME
    assert isinstance(document["owner"], dict)
    assert document["owner"]["name"] == "Adoom666"
    assert isinstance(document["plugins"], list)


def test_every_plugin_entry_carries_the_two_required_fields() -> None:
    """A plugin entry requires name and source; the rest is optional."""
    document = build_marketplace(
        [_item("sme"), _item("progress")],
        repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    for entry in document["plugins"]:
        assert isinstance(entry["name"], str) and entry["name"]
        assert isinstance(entry["source"], str) and entry["source"]


def test_a_same_repository_source_is_a_relative_path_beginning_with_dot_slash() -> None:
    """The documented form for a plugin living in the marketplace's own repo."""
    document = build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    source = document["plugins"][0]["source"]
    assert source == "./skills/adoom666/sme"
    assert source.startswith("./")
    assert ".." not in source


def test_the_source_is_the_signed_skill_folder_itself() -> None:
    """Nothing is copied and no manifest is written beside the signed bytes.

    The whole reason the entry points at ``skills/<handle>/<name>`` is that a
    release statement names that folder's digest. A generator that wrote a
    ``plugin.json`` into it, or copied it into a second tree, would either
    invalidate the signature or create a copy free to drift from it.
    """
    item = _item("sme")
    document = build_marketplace(
        [item], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    entry = document["plugins"][0]
    assert entry["source"].removeprefix("./") == f"skills/{item['publisher']}/{item['name']}"


def test_the_description_is_the_card_brief_and_the_version_is_latest() -> None:
    """Both are copied from the item; neither is composed here."""
    item = _item("sme", latest="2.3.1")
    document = build_marketplace(
        [item], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    entry = document["plugins"][0]
    assert entry["description"] == item["card"]["brief"]
    assert entry["version"] == "2.3.1"


def test_the_author_is_the_publishers_declared_github_login() -> None:
    """Taken from publishers/<handle>.json, never from the handle itself."""
    document = build_marketplace(
        [_item("sme")],
        repo_slug=SLUG,
        publishers={HANDLE: _publisher(login="SomeoneElse")},
    )
    author = document["plugins"][0]["author"]
    assert author["name"] == "SomeoneElse"
    assert author["url"] == "https://github.com/SomeoneElse"


def test_an_item_whose_publisher_is_not_declared_is_refused() -> None:
    """An entry naming an author nobody declared would be a made up claim."""
    with pytest.raises(MarketplaceRefused) as caught:
        build_marketplace([_item("sme")], repo_slug=SLUG, publishers={})
    assert "publishers/adoom666.json" in str(caught.value)


def test_two_publishers_claiming_one_plugin_name_are_refused() -> None:
    """A marketplace namespace is flat, so the clash is surfaced, not settled.

    Renaming the older entry would break every install that already used the
    name; dropping one would make a published skill silently absent. Both are
    decisions only the publishers can make, so the build stops.
    """
    publishers = {
        HANDLE: _publisher(),
        "someone": _publisher(handle="someone", login="Someone"),
    }
    items = [_item("sme"), _item("sme", handle="someone")]
    with pytest.raises(MarketplaceRefused) as caught:
        build_marketplace(items, repo_slug=SLUG, publishers=publishers)
    message = str(caught.value)
    assert "adoom666/sme" in message and "someone/sme" in message


def test_the_owner_is_read_out_of_the_repo_slug() -> None:
    """And a slug that does not read owner/repo is refused rather than split."""
    assert owner_login("Adoom666/CarnivoreAI-Skills") == "Adoom666"
    with pytest.raises(MarketplaceRefused):
        owner_login("not-a-slug")


def test_the_document_carries_no_timestamp_and_no_serial() -> None:
    """Otherwise every rebuild would look like a change to the staleness check."""
    document = build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    text = json.dumps(document)
    assert "generated_at" not in text and "serial" not in text
    again = build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    assert render(document) == render(again)


def test_the_rendered_file_is_valid_json_ending_in_one_newline() -> None:
    """The spelling the staleness check compares byte for byte."""
    payload = render(build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    ))
    assert payload.endswith(b"\n") and not payload.endswith(b"\n\n")
    assert json.loads(payload.decode("utf-8"))["name"] == MARKETPLACE_NAME


def test_staleness_is_red_when_the_file_was_never_committed(tmp_path: Path) -> None:
    """A missing file is the loudest kind of stale, and it says so."""
    document = build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    reason = staleness(tmp_path, document)
    assert reason is not None
    assert MARKETPLACE_PATH in reason and "not committed" in reason


def test_staleness_is_red_when_the_committed_file_lists_something_else(
    tmp_path: Path,
) -> None:
    """The check must be able to go red, or its green means nothing."""
    publishers = {HANDLE: _publisher()}
    stale = build_marketplace([_item("sme")], repo_slug=SLUG, publishers=publishers)
    write_marketplace(stale, tmp_path / MARKETPLACE_PATH)

    fresh = build_marketplace(
        [_item("sme"), _item("progress")], repo_slug=SLUG, publishers=publishers,
    )
    assert staleness(tmp_path, fresh) is not None


def test_staleness_is_green_on_the_file_the_build_just_wrote(tmp_path: Path) -> None:
    """And green only then."""
    document = build_marketplace(
        [_item("sme")], repo_slug=SLUG, publishers={HANDLE: _publisher()},
    )
    write_marketplace(document, tmp_path / MARKETPLACE_PATH)
    assert staleness(tmp_path, document) is None


def test_the_file_is_written_at_the_documented_path(tmp_path: Path) -> None:
    """`.claude-plugin/marketplace.json`, and the directory is made for it."""
    document = build_marketplace([], repo_slug=SLUG, publishers={})
    write_marketplace(document, tmp_path / MARKETPLACE_PATH)
    assert (tmp_path / ".claude-plugin" / "marketplace.json").is_file()


@requires_minisign
def test_a_skill_with_no_verified_release_never_reaches_the_marketplace(
    catalog: dict, tmp_path: Path,  # noqa: F811
) -> None:
    """The exclusion runs through the real verification path, not around it.

    A folder is added under ``skills/`` with a perfectly good SKILL.md and no
    release statement at all. It is exactly what an unreleased or untrusted
    contribution looks like on disk, and the marketplace must not list it: a
    user who installed it would be installing bytes nobody signed for.
    """
    root: Path = catalog["root"]
    unreleased = root / "skills" / HANDLE / "unreleased"
    unreleased.mkdir(parents=True)
    (unreleased / "SKILL.md").write_text(
        "---\nname: unreleased\ndescription: nobody signed this one.\n---\n\nbody.\n",
        encoding="utf-8",
    )

    publishers = load_publishers(root)
    verified = [
        verify_release(root, path, publishers=publishers, repo_slug=SLUG)
        for path in find_release_files(root)
    ]
    built = assemble(
        root, publishers=publishers, releases=verified, repo_slug=SLUG, serial=0,
    )
    document = build_marketplace(
        built.document["items"], repo_slug=SLUG, publishers=publishers,
    )

    names = [entry["name"] for entry in document["plugins"]]
    assert "unreleased" not in names
    assert names == ["work"]
    assert document["plugins"][0]["source"] == "./skills/adoom666/work"
