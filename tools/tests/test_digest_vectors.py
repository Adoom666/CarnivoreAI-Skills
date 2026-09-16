"""The shared vectors: this repo's digest must equal the product repo's.

THIS IS THE ONLY THING STOPPING THE TWO IMPLEMENTATIONS FROM DRIFTING. The
publisher signs a digest computed here; the app refuses an install unless it
recomputes the same number from the tarball it downloaded. Two programs, two
repositories, one number. ``digest_vectors.json`` is byte for byte identical
in both and a test in each reproduces every vector, so a change to either
implementation goes red on both sides on the same afternoon.

THE RENDERING IS PINNED AS WELL AS THE HASH. A test that asserts only a hex
string cannot tell you which of the two changed when it goes red, and the
layout is the part another language has to copy.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from index_builder.digest import (
    DIGEST_DOMAIN,
    DigestEntry,
    digest_entries,
    render_entries,
)

from tests.conftest import REPO_ROOT

VECTOR_FILE = REPO_ROOT / "digest_vectors.json"


def load_vectors() -> list:
    """Read the shared vector file.

    :returns: the vectors.
    :raises AssertionError: when the file is missing, because a vector file
        that silently vanished would make this whole suite pass by looking
        at nothing.
    """
    assert VECTOR_FILE.is_file(), f"{VECTOR_FILE} is missing"
    document = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    vectors = document["vectors"]
    assert vectors, "the vector file carries no vectors"
    return vectors


def test_the_domain_prefix_matches() -> None:
    """The domain separator is part of the signed contract, so pin it."""
    document = json.loads(VECTOR_FILE.read_text(encoding="utf-8"))
    assert document["domain"].encode("utf-8") == DIGEST_DOMAIN


@pytest.mark.parametrize("vector", load_vectors(), ids=lambda v: v["name"])
def test_vector_render_and_digest(vector: dict) -> None:
    """Every vector's rendering AND its digest come out of this code."""
    entries = [
        DigestEntry(relpath=e["relpath"], mode=e["mode"], sha256=e["sha256"])
        for e in vector["entries"]
    ]
    assert render_entries(entries) == base64.b64decode(vector["render_b64"]), (
        f"{vector['name']}: the canonical rendering changed"
    )
    assert digest_entries(entries) == vector["digest"], (
        f"{vector['name']}: the digest changed"
    )


def test_order_does_not_change_the_digest() -> None:
    """A folder walked in a different order still digests the same.

    The whole point of sorting inside the renderer. A tar stream arrives in
    archive order and a directory walk in filesystem order, and the two
    sides have to agree anyway.
    """
    vector = next(v for v in load_vectors() if len(v["entries"]) > 1)
    entries = [
        DigestEntry(relpath=e["relpath"], mode=e["mode"], sha256=e["sha256"])
        for e in vector["entries"]
    ]
    assert digest_entries(reversed(entries)) == digest_entries(entries)


def test_the_exec_bit_changes_the_digest() -> None:
    """Flipping the owner execute bit is a different folder, not the same one."""
    regular = [DigestEntry(relpath="run.sh", mode="100644", sha256="a" * 64)]
    executable = [DigestEntry(relpath="run.sh", mode="100755", sha256="a" * 64)]
    assert digest_entries(regular) != digest_entries(executable)
