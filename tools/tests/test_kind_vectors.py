"""Every shared kind vector through this repository's kind rules.

``tests/fixtures/kind_vectors.json`` is the one vectors file the product
repository's hosted validators and this index builder both run. Its sha256
is pinned here and in the product repository's
``tests/hosted_catalog/test_validate_kinds.py``, so changing either copy
goes red until both agree. The builder answers each vector with the same
status and code the hosted validator does.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Dict

import pytest

from index_builder.kind_errors import KindRefused
from index_builder.kind_rules import validate_folder

VECTORS_PATH = Path(__file__).resolve().parent / "fixtures" / "kind_vectors.json"
#: The same value the product repository pins for its copy.
VECTORS_SHA256 = "a3afcec293b6d281fee09ad5fce1926b308d07fd2d8a47f55a919389b47200e3"
VECTORS = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]


def members_of(vector: dict) -> Dict[str, bytes]:
    """Decode a vector's files into path to bytes, in vector order.

    :param vector: one entry of the vectors file.
    :returns: the members; ``pad_to`` pads with NULs like the hosted test.

    Example: members_of(v)["theme.json"]
    """
    members: Dict[str, bytes] = {}
    for path, spec in vector["files"].items():
        raw = spec["text"].encode() if "text" in spec else base64.b64decode(spec["b64"])
        members[path] = raw.ljust(spec.get("pad_to") or 0, b"\0")
    return members


def test_vectors_file_is_pinned() -> None:
    """The vectors file digest equals the value the product repository pins."""
    assert hashlib.sha256(VECTORS_PATH.read_bytes()).hexdigest() == VECTORS_SHA256


def test_vectors_file_carries_every_kind_and_refusal() -> None:
    """A vectors file that lost its content cannot pass by testing nothing."""
    kinds = {v["expect"].get("kind") for v in VECTORS} - {None}
    codes = {v["expect"].get("code") for v in VECTORS} - {None}
    assert kinds == {"skill", "theme", "plugin"}
    assert {"plugin_not_safe", "theme_value_unsafe", "kind_not_supported"} <= codes
    assert len(VECTORS) >= 50


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"] for v in VECTORS])
def test_vector(vector: dict) -> None:
    """Each vector is accepted as its kind or refused with its status and code."""
    expect = vector["expect"]
    members = members_of(vector)
    declared = vector.get("declared_kind")
    if expect["status"] == 200:
        assert validate_folder(vector["name"], members, declared)[0] == expect["kind"]
        return
    with pytest.raises(KindRefused) as caught:
        validate_folder(vector["name"], members, declared)
    assert (caught.value.status, caught.value.code) == (expect["status"], expect["code"])


def test_plugin_refusal_lists_every_offender_up_to_ten() -> None:
    """One round names every offending path, capped at ten."""
    vector = next(v for v in VECTORS if v["id"] == "plugin-ok")
    members = members_of(vector)
    for n in range(12):
        members[f"bin/x{n}"] = b"\0"
    with pytest.raises(KindRefused) as caught:
        validate_folder(vector["name"], members)
    assert caught.value.detail.count("bin/x") == 10 and "and 2 more" in caught.value.detail
