"""The card brief, and the characters it is not allowed to carry through.

A BRIEF IS COPIED VERBATIM INTO A GENERATED FILE AND RENDERED IN A LIST.
``brief_of`` flattens a publisher's description into one line, and that
line lands in ``.claude-plugin/marketplace.json`` and in the index, both
of which are printed to a terminal by tools this repository does not
control.

``" ".join(text.split())`` LOOKS LIKE IT SANITISES AND DOES NOT. Python
splits on the whitespace set, which is space, tab, CR, LF, vertical tab
and form feed. ESC, BEL and backspace are not in it. A published
description carrying ``\\x1b[31m`` therefore reached the marketplace file
intact; the consumer stripped it at render time, which is luck rather
than a guarantee, and the next consumer is under no obligation to.

A CONTROL CHARACTER IS NOT THE SAME CASE AS PUNCTUATION. An em dash is a
character the publisher meant a reader to see, so it travels. A C0
control is not text at all: it is an instruction to whatever renders it.
Removing one does not change a word the publisher wrote, which is why
this is a strip and not a rewrite.
"""

from __future__ import annotations

import pytest

from index_builder.frontmatter import brief_of


@pytest.mark.parametrize(
    "control,name",
    [
        ("\x1b", "ESC, the first byte of every ANSI sequence"),
        ("\x07", "BEL, which rings a terminal"),
        ("\x08", "backspace, which overprints what was already shown"),
        ("\x00", "NUL, which truncates a C string consumer"),
        ("\x1a", "SUB"),
        ("\x7f", "DEL"),
    ],
)
def test_a_c0_control_never_survives_a_brief(control: str, name: str) -> None:
    """The fix. The negative control is the split/join behaviour itself."""
    assert control in " ".join(f"red{control}text".split()), (
        f"negative control failed: split/join already removed {name}, so "
        f"this case never demonstrated the defect it claims to"
    )
    brief = brief_of(f"red{control}text is a thing.")
    assert control not in brief
    assert "\x1b" not in brief


def test_a_whole_ansi_sequence_loses_its_escape() -> None:
    """The measured case: a colour sequence in a published description."""
    brief = brief_of("\x1b[31mdanger\x1b[0m does one thing.")
    assert "\x1b" not in brief
    assert "danger" in brief


def test_no_c0_control_at_all_survives() -> None:
    """Swept rather than enumerated, so a byte nobody thought of is caught."""
    payload = "".join(chr(code) for code in range(0x20)) + "\x7f"
    brief = brief_of(f"a{payload}b does one thing.")
    for code in list(range(0x20)) + [0x7F]:
        assert chr(code) not in brief, f"U+{code:04X} survived"


def test_a_line_break_still_becomes_a_space_rather_than_vanishing() -> None:
    """The existing behaviour, which the fix must not have taken away.

    Deleting a newline would weld the last word of one line onto the
    first word of the next, which is a different sentence.
    """
    assert brief_of("first line\nsecond line here.") == "first line second line here."
    assert brief_of("first\tsecond here.") == "first second here."


def test_publisher_punctuation_is_left_exactly_as_written() -> None:
    """An em dash, an arrow and an emoji are words, not instructions.

    Four of the six skills published from this repository carry one of
    these in their own description. A brief that normalised them would be
    rewriting text whose folder digest a publisher has signed.
    """
    brief = brief_of("does a thing — then another → done ✅ here.")
    assert "—" in brief
    assert "→" in brief
    assert "✅" in brief
