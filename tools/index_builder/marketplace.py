"""The Claude plugin marketplace file, built from the same proven items.

WHAT THIS IS FOR. `claude plugin marketplace add Adoom666/CarnivoreAI-Skills`
reads one file, `.claude-plugin/marketplace.json`, at the ROOT of whatever
repository was added. That file lists plugins and where each one's bytes are.
This module writes it, so the catalog is installable by the stock CLI without
anybody hand maintaining a second list of what is published.

IT IS BUILT FROM THE VERIFIED ITEMS AND FROM NOTHING ELSE. The caller hands
this module the items :mod:`index_builder.assemble` produced, which only
contain releases that survived :mod:`index_builder.releases`. A skill whose
release statement did not verify, or whose publisher has no active key, never
reaches an item and therefore can never reach this file. There is no second
walk of the `skills/` tree here, on purpose: a second walk would be a second
answer to "what is published", and the two would eventually disagree.

THE SIGNED TREE IS NOT TOUCHED. A plugin entry points straight at the skill
folder, `./skills/<handle>/<name>`, and the CLI loads a directory holding a
SKILL.md and no `skills/` subdirectory as a single skill plugin. So no
`plugin.json` is written into a skill folder and no copy of one is made
elsewhere. Either would change bytes a publisher already signed a digest
over, or duplicate them into a second tree that drifts. Proven against
Claude Code 2.1.266, which reported `Skills (1)` for exactly this shape.

THE DOCUMENT CARRIES NO TIMESTAMP AND NO SERIAL. It is a pure function of the
verified items, so two builds of the same commit write the same bytes, which
is what lets the build job tell a stale committed file from a fresh one. A
`generated_at` here would make every rebuild look like a change.

WHAT INSTALLING THROUGH THIS FILE DOES AND DOES NOT GET YOU. `claude
plugin install` copies the skill folder as it stands on `main` at the
moment it runs; it does not read a release statement and it cannot be made
to. The minisign chain in this repository covers `v1/index.json`, which is
the CATALOG INDEX, and it does not cover the copy the CLI made: no
signature artifact is written into the plugin cache and nothing there is
checked. A user who wants the bytes a publisher actually signed installs
through the app's catalog screen, which verifies the index against a
pinned key and checks the folder digest before it stages anything. Both
paths are real and neither is oversold here.

A NAME COLLISION IS REFUSED, NEVER RENAMED. A marketplace namespace is flat:
`sme@carnivore` names one plugin. Two publishers shipping a skill of the same
name cannot both have it. Renaming the older one to settle the clash would
break every install that already used its name, and dropping one would make a
published skill silently absent, so the build stops and says which two clash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from .publishers import PublisherRecord
from .releases import SKILLS_DIR
from .statements import PUBLISHER_RE, SKILL_NAME_RE, match_or_raise

#: Where the CLI looks, relative to the root of the repository it was given.
MARKETPLACE_PATH = ".claude-plugin/marketplace.json"

#: The marketplace's name. This is public: it is the half after the `@` in
#: `sme@carnivore`, so it is part of every install command anybody writes
#: down, and changing it orphans those commands.
MARKETPLACE_NAME = "carnivore"

#: The command that rewrites the file, quoted in the staleness message so a
#: contributor never has to go and find it. Run from the `tools` directory,
#: the way every other command in this package is run.
REGENERATE_COMMAND = (
    "cd tools && python3 -m index_builder --repo-root .. marketplace --write"
)


class MarketplaceRefused(Exception):
    """Raised when the marketplace file cannot be built honestly."""


def _github_url(login: str) -> str:
    """The profile URL for a GitHub login.

    :param login: the login exactly as the publisher declared it.
    :returns: the URL.
    """
    return f"https://github.com/{login}"


def owner_login(repo_slug: str) -> str:
    """The GitHub account that owns the repository, and so the marketplace.

    Description: reads the owner out of the `owner/repo` slug that
      catalog.yml declares. The slug is the authority rather than a
      publisher record because the marketplace IS the repository: it is
      what a user types into `claude plugin marketplace add`, it is
      already part of every signed release statement, and it stays right
      as publishers come and go. On this repository it is the same string
      as `publishers/adoom666.json`'s `github_login`, which is the other
      place the name honestly appears.
    Inputs: repo_slug (str) - `owner/repo`, from catalog.yml.
    Output: str - the owner segment.
    Raises: MarketplaceRefused when the slug does not read `owner/repo`.
    Example: owner_login("Adoom666/CarnivoreAI-Skills") -> "Adoom666"
    """
    owner, _, name = repo_slug.partition("/")
    if not owner or not name or "/" in name:
        raise MarketplaceRefused(
            f"the repo slug {repo_slug!r} does not read owner/repo, so the "
            f"marketplace owner cannot be read out of it"
        )
    return owner


def plugin_entry(
    item: Dict[str, object], *, publishers: Dict[str, PublisherRecord],
) -> Dict[str, object]:
    """Render one verified catalog item as one marketplace plugin entry.

    Description: the entry carries only what the CLI reads and what a
      reader needs to judge it. `source` is the skill folder itself,
      relative to the marketplace root and spelled with the leading `./`
      the CLI requires; the folder holds a SKILL.md and no `skills/`
      subdirectory, which is the shape the CLI loads as a single skill.
      `description` is the item's CARD BRIEF rather than the full front
      matter description, because this is a list row and the brief is the
      one line the catalog already derived for exactly that job. Nothing
      is invented: every value is copied from the item or from the
      publisher's own declaration.
    Inputs: item (dict) - one entry of the assembled index's `items`.
      publishers (dict) - every declared publisher, by handle.
    Output: dict - one plugin entry.
    Raises: MarketplaceRefused when the item is missing a field it cannot
      be rendered without, when its publisher or name fails the shape that
      makes it safe to compose into a path, or when it names a publisher
      that is not declared.
    Example: plugin_entry(item, publishers=records)["source"]
      -> "./skills/adoom666/sme"
    """
    handle = item.get("publisher")
    name = item.get("name")
    latest = item.get("latest")
    card = item.get("card")
    if not isinstance(handle, str) or not handle:
        raise MarketplaceRefused(f"an item carries no publisher: {item.get('id')!r}")
    if not isinstance(name, str) or not name:
        raise MarketplaceRefused(f"item {item.get('id')!r} carries no name")
    if not isinstance(latest, str) or not latest:
        raise MarketplaceRefused(f"item {item.get('id')!r} carries no latest version")
    if not isinstance(card, dict):
        raise MarketplaceRefused(f"item {item.get('id')!r} carries no card")
    brief = card.get("brief")
    if not isinstance(brief, str) or not brief:
        raise MarketplaceRefused(f"item {item.get('id')!r} carries no card brief")

    # `source` is composed into a path under the marketplace root two
    # lines below, so BOTH HALVES ARE HELD TO THEIR OWN SHAPE HERE rather
    # than trusted to have been checked upstream. They are checked
    # upstream today, in a different module reached by a different call
    # path, which is one refactor away from not being reached at all. A
    # boundary that composes a path re-asserts its own grammar or it is
    # not a boundary. The line break check comes first because the `$`
    # anchor in both patterns matches BEFORE a trailing newline, so
    # "sme\n" would otherwise pass a shape it does not have.
    for field_name, value in (("publisher", handle), ("name", name)):
        if "\n" in value or "\r" in value:
            raise MarketplaceRefused(
                f"item {item.get('id')!r} carries a line break in its "
                f"{field_name}, which cannot be part of a path or a plugin name"
            )
    try:
        match_or_raise(handle, PUBLISHER_RE, "publisher")
        match_or_raise(name, SKILL_NAME_RE, "name")
    except ValueError as exc:
        raise MarketplaceRefused(
            f"item {item.get('id')!r} cannot be rendered as a plugin entry "
            f"because {exc}. the entry composes a path from the publisher "
            f"and the name, so it refuses rather than emits"
        ) from exc

    record = publishers.get(handle)
    if record is None:
        raise MarketplaceRefused(
            f"item {item.get('id')!r} names the publisher {handle!r}, for which "
            f"there is no publishers/{handle}.json"
        )

    return {
        "name": name,
        "source": f"./{SKILLS_DIR}/{handle}/{name}",
        "description": brief,
        "version": latest,
        "author": {
            "name": record.github_login,
            "url": _github_url(record.github_login),
        },
    }


def build_marketplace(
    items: Sequence[Dict[str, object]],
    *,
    repo_slug: str,
    publishers: Dict[str, PublisherRecord],
) -> Dict[str, object]:
    """Build the whole marketplace document from the verified items.

    Description: one plugin entry per item, in the order the index already
      sorted them, which is total and stable, so the bytes do not wander
      between builds of the same content. Two items whose folder names
      collide are REFUSED rather than renamed or dropped, because a
      marketplace namespace is flat and neither of the quiet answers is
      one a publisher would want made on their behalf.
    Inputs: items (sequence of dict) - the assembled index's `items`.
      repo_slug (str) - `owner/repo`, from catalog.yml. publishers (dict).
    Output: dict - the whole `.claude-plugin/marketplace.json` document.
    Raises: MarketplaceRefused on a name collision or an unrenderable item.
    Example: build_marketplace([], repo_slug="a/b", publishers={})["plugins"]
      -> []
    """
    login = owner_login(repo_slug)
    entries: List[Dict[str, object]] = []
    claimed: Dict[str, str] = {}
    for item in items:
        entry = plugin_entry(item, publishers=publishers)
        name = str(entry["name"])
        item_id = str(item.get("id", name))
        first = claimed.get(name)
        if first is not None:
            raise MarketplaceRefused(
                f"{first} and {item_id} would both be the plugin {name!r}, and a "
                f"marketplace holds one plugin per name. Rename one of the two "
                f"skill folders and release it under the new name; renaming it "
                f"here would break every install that already used {name!r}"
            )
        claimed[name] = item_id
        entries.append(entry)

    return {
        "name": MARKETPLACE_NAME,
        "owner": {"name": login, "url": _github_url(login)},
        "plugins": entries,
    }


def render(document: Dict[str, object]) -> bytes:
    """Serialise the marketplace document in its one spelling.

    Description: the same spelling :func:`index_builder.assemble.write_index`
      uses, for the same reason: the staleness check compares BYTES, so
      the formatting has to be decided in exactly one place or a build
      would report a file stale because it was indented differently.
    Inputs: document (dict).
    Output: bytes - two space indent, declared key order, non ASCII left
      as itself, exactly one trailing newline.
    Example: render({"name": "carnivore"}).endswith(b"\\n") -> True
    """
    return json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8") + b"\n"


def write_marketplace(document: Dict[str, object], path: Path) -> bytes:
    """Write the marketplace document to disk.

    Description: creates the `.claude-plugin` directory when it is absent,
      because the very first run of this command is the run that makes it.
    Inputs: document (dict). path (Path) - where the file goes.
    Output: bytes - what was written.
    Example: write_marketplace(doc, root / MARKETPLACE_PATH)
    """
    payload = render(document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return payload


def staleness(repo_root: Path, document: Dict[str, object]) -> Optional[str]:
    """Say why the committed marketplace file does not match the build.

    Description: compares the bytes the build just produced with the bytes
      committed at `.claude-plugin/marketplace.json`. A missing file, a
      file that differs by so much as a space, and a file that is not
      readable are all the same verdict for the caller and each gets its
      own sentence, because "regenerate it" is useless advice to somebody
      who does not know which of the three happened. Returns None when
      the committed file is exactly what this build would write.
    Inputs: repo_root (Path) - the repository. document (dict) - what the
      build produced.
    Output: str - one line naming the difference, or None when fresh.
    Example: staleness(root, document) is None -> True on a clean tree
    """
    path = repo_root / MARKETPLACE_PATH
    expected = render(document)
    if not path.is_file():
        return (
            f"{MARKETPLACE_PATH} is not committed, and the catalog now publishes "
            f"{len(document.get('plugins', []))} plugins that a Claude Code user "
            f"cannot install without it"
        )
    try:
        found = path.read_bytes()
    except OSError as exc:
        return f"{MARKETPLACE_PATH} could not be read: {exc}"
    if found == expected:
        return None
    return (
        f"{MARKETPLACE_PATH} is {len(found)} bytes and this build would write "
        f"{len(expected)}, so the committed file no longer lists what the catalog "
        f"publishes"
    )
