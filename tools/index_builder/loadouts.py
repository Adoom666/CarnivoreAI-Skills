"""Read a ``loadout.json`` and prove its members against the index being built.

A loadout is a REFERENCE, not content: it lists other catalog items by id,
exact version and exact digest. Its own bytes (the list) are covered by its
own release signature, and each member's bytes by that member's release, so
the only thing this job adds is the cross check the app repeats at install
time: every member must already be in THIS index, at the pinned version,
with the digest the index carries for it.

Refused, each with the loadout and member named: a manifest that is not the
``carnivore.catalog.loadout/1`` shape the app parses, more than
``MAX_MEMBERS`` members, a duplicate member, an id that is not in the index
(an unknown or unsigned member never reaches the index, so this is the
"unsigned" refusal too), a version the item does not carry, a digest that
differs from the indexed one, and a member that is itself a loadout.

The parser mirrors the app's ``src/core/skills/loadout_manifest.py`` on
purpose: what this job accepts must be what the app accepts, and the shared
constants below carry the same values.
"""

from __future__ import annotations

import json
from typing import Dict, List, Mapping, Tuple

from .releases import KIND_LOADOUT, ReleaseRefused
from .statements import DIGEST_RE, PUBLISHER_RE, SKILL_NAME_RE, VERSION_RE

#: The schema string a ``loadout.json`` must carry (the app pins the same).
LOADOUT_SCHEMA = "carnivore.catalog.loadout/1"

#: The most members one loadout may list (the app's own bound).
MAX_MEMBERS = 64

#: The manifest file a loadout folder must hold.
MANIFEST = "loadout.json"


def parse_loadout(text: str, *, item_id: str) -> Tuple[str, str, List[Dict[str, str]]]:
    """Parse a loadout.json body into (name, description, members).

    :param text: the manifest body, verbatim.
    :param item_id: this loadout's own id, so a list naming itself is refused.
    :returns: the name, a non-empty description (the card needs one), and the
        members as dicts with ``id``, ``version`` and ``digest``, in order.
    :raises ReleaseRefused: on anything the app's parser would refuse.

    Example: parse_loadout(text, item_id="a/pack")[2][0]["id"] -> "a/sme"
    """
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ReleaseRefused(f"{item_id}: loadout.json is not JSON: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != LOADOUT_SCHEMA:
        raise ReleaseRefused(
            f"{item_id}: loadout.json must be an object with schema {LOADOUT_SCHEMA!r}"
        )
    name = raw.get("name")
    description = raw.get("description")
    for field, value in (("name", name), ("description", description)):
        if not isinstance(value, str) or not value.strip():
            raise ReleaseRefused(f"{item_id}: loadout.json {field} is missing or not a string")
    members = raw.get("members")
    if not isinstance(members, list) or not members:
        raise ReleaseRefused(f"{item_id}: loadout.json members must be a non-empty list")
    if len(members) > MAX_MEMBERS:
        raise ReleaseRefused(
            f"{item_id}: {len(members)} members is over the cap of {MAX_MEMBERS}"
        )
    out: List[Dict[str, str]] = []
    seen = set()
    for index, entry in enumerate(members):
        where = f"{item_id}: members[{index}]"
        if not isinstance(entry, dict):
            raise ReleaseRefused(f"{where} is not an object")
        member_id, version, digest = (entry.get(k) for k in ("id", "version", "digest"))
        if not (isinstance(member_id, str) and isinstance(version, str)
                and isinstance(digest, str)):
            raise ReleaseRefused(f"{where} needs string id, version and digest")
        publisher, _, member_name = member_id.partition("/")
        if not (PUBLISHER_RE.fullmatch(publisher) and SKILL_NAME_RE.fullmatch(member_name)):
            raise ReleaseRefused(f"{where}.id {member_id!r} is not '<publisher>/<name>'")
        if not VERSION_RE.fullmatch(version):
            raise ReleaseRefused(f"{where}.version {version!r} is not a version")
        if not DIGEST_RE.fullmatch(digest):
            raise ReleaseRefused(f"{where}.digest is not 64 lowercase hex characters")
        if member_id == item_id:
            raise ReleaseRefused(f"{where} lists the loadout itself")
        if member_id in seen:
            raise ReleaseRefused(f"{where}: {member_id} is listed twice")
        seen.add(member_id)
        out.append({"id": member_id, "version": version, "digest": digest})
    return name.strip(), description.strip(), out


def check_members(
    item_id: str,
    version: str,
    members: List[Dict[str, str]],
    indexed: Mapping[str, Tuple[str, Mapping[str, str]]],
) -> None:
    """Prove every member against what the index being built carries.

    :param item_id: the loadout's id, for messages.
    :param version: the loadout version being checked, for messages.
    :param indexed: item id -> (kind, {version: digest}) for every item that
        survived verification. An unknown or unsigned member is absent.
    :raises ReleaseRefused: on the first member that is absent, is itself a
        loadout, pins a version the item lacks, or pins a wrong digest.

    Example: check_members("a/p", "1.0.0", members, {"a/sme": ("skill", {"1.0.0": d})})
    """
    for member in members:
        where = f"{item_id}@{version}: member {member['id']}@{member['version']}"
        known = indexed.get(member["id"])
        if known is None:
            raise ReleaseRefused(f"{where} is not in the index (unknown or unsigned)")
        kind, digests = known
        if kind == KIND_LOADOUT:
            raise ReleaseRefused(f"{where} is a loadout; loadouts do not nest")
        if member["version"] not in digests:
            raise ReleaseRefused(f"{where}: the index has no such version")
        if digests[member["version"]] != member["digest"]:
            raise ReleaseRefused(
                f"{where}: digest {member['digest']} is not the indexed "
                f"{digests[member['version']]}"
            )
