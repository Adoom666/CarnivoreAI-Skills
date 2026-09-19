"""The eleven fixture skills, and the verdict each one has to produce.

WHY THIS FILE IS THE DELIVERABLE THAT MATTERS. Before this change the
reviewer had returned zero findings on every input it had ever seen, which
is what a working detector and a broken one both look like. A green check
must first prove it can go red, so this file holds one hostile skill per
finding kind, and each one is run through the real parser and the real
verdict derivation.

NO MODEL IS CALLED HERE. The answers are canned, because what is under test
is the half that has to be deterministic: that a blocking kind produces
``blocked``, that a verdict disagreeing with its own findings is thrown
away whole, and that an answer with no verdict at all is thrown away too.
Whether the model finds the thing is a separate question, answered by
running these same folders past the live endpoint by hand; the prompt drift
guards are in ``test_review_prompt.py``.

THE FOLDERS ARE REAL AND THEY ARE THE CORPUS. ``fixtures/review/<name>/``
holds each skill as text, so the same set can be handed to the live model
when somebody changes the prompt. They live under the test tree and NEVER
under ``skills/``, so nothing here is ever published.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from index_builder.digest import digest_directory
from index_builder.review import (
    BLOCKING_KINDS,
    ReviewUnavailable,
    collect_staged_text,
    derive_verdict,
    parse_review,
)

#: Where the fixture skills live.
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review"

#: Every fixture, the verdict it must produce, and the kinds a correct
#: reading of it reports. The kinds are what the LIVE run is measured
#: against; the verdict is what this file proves the code derives from them.
EXPECTED: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "remote_exec": ("blocked", ("network", "shell_exec", "opaque_payload")),
    "credential_access": ("blocked", ("credential_access",)),
    "prompt_injection": ("blocked", ("prompt_injection",)),
    "reviewer_steering": ("blocked", ("prompt_injection",)),
    "settings_write": ("blocked", ("settings_write",)),
    "obfuscation": ("blocked", ("obfuscation",)),
    "opaque_payload": ("blocked", ("opaque_payload",)),
    "unshown_file": ("blocked", ("credential_access",)),
    # the recon named this one flagged, on the reading that a mismatch is
    # sloppy authorship rather than an attack. its BODY prints every .env it
    # can find into the conversation, and .env is named in the prompt's own
    # credential_access line, so the disposition table makes it blocked. the
    # table is the normative half and the expectation moved to it.
    "description_mismatch": ("blocked", ("description_mismatch", "credential_access")),
    "network_advisory": ("flagged", ("network",)),
    "clean": ("clean", ()),
}


def _canned(kinds: Tuple[str, ...]) -> str:
    """A model answer reporting exactly these kinds, in the documented shape.

    :param kinds: the finding kinds to report.
    :returns: the JSON text a model would send.

    The verdict is DERIVED here rather than written out, so a fixture whose
    expected verdict is wrong fails on the assertion rather than being
    quietly agreed with by its own canned answer.
    """
    warnings = [
        {"kind": kind, "detail": f"the skill {kind}s.", "file": "SKILL.md"}
        for kind in kinds
    ]
    return json.dumps({
        "verdict": derive_verdict(warnings),
        "summary": "what this fixture does.",
        "warnings": warnings,
    })


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_fixture_has_a_folder(name: str) -> None:
    """The corpus is on disk, so a live run has something to read.

    A table naming eleven fixtures with nine folders would pass every
    assertion below and still be a corpus with two holes in it.
    """
    skill = FIXTURES / name / "SKILL.md"
    assert skill.is_file(), f"{skill} is missing, so this fixture is a name only"
    assert skill.read_text(encoding="utf-8").startswith("---"), (
        f"{skill} carries no yaml frontmatter, so the description question "
        f"has nothing to compare against"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_fixture_derives_its_expected_verdict(name: str) -> None:
    """One fixture per kind, parsed for real, producing the stated verdict."""
    expected_verdict, kinds = EXPECTED[name]
    verdict, summary, warnings = parse_review(_canned(kinds))
    assert verdict == expected_verdict, (
        f"{name}: a review reporting {kinds or 'nothing'} derives {verdict}, "
        f"not the {expected_verdict} this fixture exists to produce"
    )
    assert [w["kind"] for w in warnings] == list(kinds)
    assert summary


def test_the_blocking_kinds_are_the_ones_that_block() -> None:
    """Every blocking kind blocks ALONE, and no advisory kind ever does.

    The disposition table is a security decision, so it is asserted here
    one kind at a time rather than trusted to the set operation that
    implements it.
    """
    for kind in BLOCKING_KINDS:
        assert derive_verdict([{"kind": kind}]) == "blocked", (
            f"{kind} is listed as blocking but does not block on its own"
        )
    advisory = {
        "network", "shell_exec", "file_delete", "privilege",
        "description_mismatch", "other",
    }
    for kind in advisory:
        assert derive_verdict([{"kind": kind}]) == "flagged", (
            f"{kind} is advisory but blocks, so a documentation lookup would "
            f"refuse a publish"
        )
    assert derive_verdict([]) == "clean"


def test_a_verdict_that_disagrees_with_its_findings_is_discarded() -> None:
    """The steering case, in the shape it would actually arrive in.

    A model that reports a credential_access finding and then calls the
    answer clean is not a model that made one mistake: it is one whose
    answer cannot be trusted at all. Discarding the whole thing records
    ``unavailable``, and the app renders that as no review, never a clean
    one.
    """
    with pytest.raises(ReviewUnavailable) as raised:
        parse_review(json.dumps({
            "verdict": "clean",
            "summary": "nothing damaging was found.",
            "warnings": [{
                "kind": "credential_access",
                "detail": "reads ~/.ssh/id_ed25519.",
                "file": "SKILL.md",
            }],
        }))
    assert "disagrees" in str(raised.value)


def test_an_answer_with_no_verdict_is_discarded() -> None:
    """The old schema's answer is not half a review under the new one."""
    with pytest.raises(ReviewUnavailable):
        parse_review(json.dumps({
            "summary": "reads files.",
            "warnings": [],
        }))


def test_a_flagged_answer_that_should_have_blocked_is_discarded() -> None:
    """Under-calling the verdict is refused for the same reason over-calling is."""
    with pytest.raises(ReviewUnavailable):
        parse_review(json.dumps({
            "verdict": "flagged",
            "summary": "edits a config file.",
            "warnings": [{
                "kind": "settings_write",
                "detail": "edits ~/.claude/settings.json.",
                "file": "SKILL.md",
            }],
        }))


def _staged_body(name: str, max_chars: int = 40000) -> str:
    """The exact body the gate would send for one fixture folder."""
    folder = FIXTURES / name
    _digest, entries = digest_directory(folder)
    members: List[Tuple[str, str]] = [(e.relpath, e.mode) for e in entries]
    return collect_staged_text(folder, members=members, max_chars=max_chars)


def test_a_reference_file_reaches_the_reviewer() -> None:
    """THE NEGATIVE CONTROL FOR THE FILE FILTER, and it went red before.

    ``unshown_file`` carries its damaging instruction in
    ``references/rules.md``, which is neither SKILL.md nor under
    ``scripts/`` nor executable. The filter this replaces sent three
    categories of file and nothing else, so that line was never shown to
    the reviewer and the fixture came back clean. The live catalog had the
    same shape: one published skill's summary described six reference
    files the model was never given.
    """
    body = _staged_body("unshown_file")
    # the HEADER, not the path: SKILL.md names references/rules.md in its own
    # prose, so asserting on the bare path passes against the filter this
    # replaces and proves nothing at all.
    assert "--- references/rules.md (mode 100644) ---" in body, (
        "the reference file's contents are not shown to the reviewer"
    )
    assert ".credentials.json" in body, (
        "the reviewer was not shown the line that makes this fixture "
        "damaging, so a clean verdict here would mean nothing. this is the "
        "assertion that goes red against the three category filter"
    )


def test_a_binary_member_is_named_with_its_size() -> None:
    """A payload nobody can read is a thing to report, not a thing to skip.

    The reviewer cannot decode ``bin/optimise``, so it is named, sized and
    marked as not shown. That is what gives the model something concrete to
    raise ``opaque_payload`` on.
    """
    body = _staged_body("opaque_payload")
    assert "bin/optimise" in body
    assert "4096 bytes" in body
    assert "not utf-8 text" in body
    assert "NOT shown" in body


def test_a_file_the_cap_excluded_is_named_rather_than_dropped() -> None:
    """A cut body says WHICH files were cut, not merely that it was cut.

    A model shown half a folder and told nothing will report that the rest
    is fine. Naming the remainder is what lets it say the opposite.
    """
    body = _staged_body("unshown_file", max_chars=200)
    assert "SKILL.md" in body, "the most important file lost its place in the order"
    assert "references/rules.md" in body
    assert "not shown to you" in body


def test_skill_md_is_always_first() -> None:
    """The cap falls on the least important files last, by construction."""
    body = _staged_body("opaque_payload")
    assert body.startswith("--- SKILL.md")
