"""The field grammars a release statement holds its inputs to.

TWO FIELDS BECOME A PATH SEGMENT AND ALL EIGHT GET RENDERED INTO A SIGNED
LINE. ``name`` is a directory under the user's home and the flat plugin
namespace's only key; ``version`` is a file stem under ``releases/`` and
the half of a revocation subject after the ``@``. Both are read out of a
document or a filename somebody else wrote, so both are refused here or
not at all.

WHY A TRAILING DOT IS A SQUAT, NOT A TYPO. ``SKILL_NAME_RE`` used to end
``[a-z0-9._-]{0,63}$``, which accepts ``sme.`` as readily as ``sme``. A
marketplace namespace is flat and the duplicate check in
:mod:`index_builder.marketplace` compares names for equality, so ``sme``
and ``sme.`` are two different keys and the check never fires. A second
publisher could therefore ship ``sme.`` beside the real ``sme``, both
entries would be emitted, and the two rows render indistinguishably in a
list: the trailing dot reads as the end of the sentence before it. This
was not theoretical. A two publisher catalog built here emitted both, and
the live CLI installed the trailing dot source.

EVERY REFUSAL BELOW CARRIES A NEGATIVE CONTROL asserting the OLD pattern
accepted the value, so none of these tests can quietly become a test that
passes because it looked at nothing (CLAUDE.md, gotcha 11).
"""

from __future__ import annotations

import re

import pytest

from index_builder.statements import (
    SKILL_NAME_RE,
    VERSION_RE,
    match_or_raise,
    release_statement,
)

#: The name pattern exactly as it stood before this file was written. It
#: exists ONLY so each refusal below can prove the old code accepted the
#: value. Never import it anywhere else.
OLD_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

COMMIT = "a" * 40
DIGEST = "b" * 64


def _statement(**overrides) -> bytes:
    """Render a valid release statement with per test overrides.

    :param overrides: any field of the statement.
    :returns: the rendered bytes.

    Example: _statement(version="2.0.0").splitlines()[4] -> b"2.0.0"
    """
    fields = {
        "kind": "skill",
        "publisher": "adoom666",
        "name": "sme",
        "version": "1.0.0",
        "repo": "Adoom666/CarnivoreAI-Skills",
        "path": "skills/adoom666/sme",
        "commit": COMMIT,
        "digest": DIGEST,
    }
    fields.update(overrides)
    return release_statement(**fields)


@pytest.mark.parametrize(
    "name",
    ["sme", "a", "a" * 64, "skill.v2", "my_skill", "my-skill", "x1", "11-stars"],
)
def test_a_valid_skill_name_is_still_accepted(name: str) -> None:
    """The positive control. A pattern that matched nothing would pass
    every refusal below without refusing anything."""
    assert SKILL_NAME_RE.match(name)
    assert _statement(name=name)


@pytest.mark.parametrize(
    "name,why",
    [
        ("sme.", "the squat: a flat namespace reads this as a second key"),
        ("work.", "a trailing dot on any name, not just the one measured"),
        ("a-", "a trailing hyphen"),
        ("a_", "a trailing underscore"),
        ("a" + "." * 63, "sixty three trailing dots, still one name"),
    ],
)
def test_a_name_that_does_not_end_alphanumeric_is_refused(name: str, why: str) -> None:
    """The fix, with the negative control that proves it is a fix."""
    assert OLD_SKILL_NAME_RE.match(name), (
        f"negative control failed: the OLD pattern did not accept {name!r}, "
        f"so this case never demonstrated the defect it claims to ({why})"
    )
    assert not SKILL_NAME_RE.match(name), why
    with pytest.raises(ValueError):
        _statement(name=name)


def test_the_name_length_bound_did_not_move() -> None:
    """Tightening the last character must not have cost a character."""
    assert SKILL_NAME_RE.match("a" * 64)
    assert not SKILL_NAME_RE.match("a" * 65)


def test_the_leading_character_rule_did_not_move() -> None:
    """A leading dot is still what keeps a name out of a .system folder."""
    for name in (".hidden", "..", "-lead", "_lead"):
        assert not SKILL_NAME_RE.match(name)


@pytest.mark.parametrize(
    "version",
    ["1.0.0", "1", "1.2", "1.2.3.4", "0.0.1", "10.20.30", "1.0.0-rc.1",
     "1.0.0-beta2", "2.0.0-alpha-3"],
)
def test_a_reasonable_version_is_accepted(version: str) -> None:
    """The positive control for every version refusal below."""
    assert VERSION_RE.match(version)
    assert _statement(version=version)


@pytest.mark.parametrize(
    "version,why",
    [
        ("../../../etc", "traversal; the version is a file stem under releases/"),
        ("9" * 400, "four hundred digits rendered raw in the CLI"),
        ("$(id)", "a shell substitution"),
        ("   ", "whitespace only"),
        ("1.0.0@evil", "an @ breaks the revocation subject's own parse"),
        ("1.0.0 ", "a trailing space is not the same version and looks it"),
        ("v1.0.0", "a leading v; one spelling per version or two rows appear"),
        ("1.0.0/x", "a separator"),
        ("1.0.0-", "a trailing hyphen on the prerelease"),
        ("\x1b[31m1.0.0", "an ANSI escape"),
    ],
)
def test_an_unreasonable_version_is_refused(version: str, why: str) -> None:
    """The fix, each with the negative control proving the old code took it.

    The old code held ``version`` to nothing at all beyond being non empty
    and carrying no line break, so the control here is that
    ``release_statement`` used to render it.
    """
    assert version and "\n" not in version and "\r" not in version, (
        "negative control failed: this value was already refused by the "
        "empty and line break checks, so it never demonstrated the defect"
    )
    assert not VERSION_RE.match(version), why
    with pytest.raises(ValueError):
        _statement(version=version)


def test_the_version_separator_comment_is_now_true() -> None:
    """``VERSION_SUBJECT_SEPARATOR`` is documented as not legal in a
    version, so the subject ``<item_id>@<version>`` parses back
    unambiguously. Nothing enforced that until this grammar existed."""
    from index_builder.statements import VERSION_SUBJECT_SEPARATOR

    assert not VERSION_RE.match(f"1.0.0{VERSION_SUBJECT_SEPARATOR}2.0.0")


@pytest.mark.parametrize(
    "value,pattern",
    [("sme\n", SKILL_NAME_RE), ("1.0.0\n", VERSION_RE)],
)
def test_a_trailing_newline_is_refused_by_fullmatch_not_match(
    value: str, pattern: "re.Pattern[str]"
) -> None:
    """``match_or_raise`` must use ``fullmatch``, not ``match``.

    ``match`` anchors only the start of the string; ``$`` in the pattern
    matches either the end of the string OR just before one trailing
    newline, so ``re.match`` lets a name or version carrying a trailing
    newline slip through where ``re.fullmatch`` catches it. This is the
    same hole the product repo's own ``_match_or_raise`` closed by using
    ``fullmatch``, and the same hole a reviewer had to close by hand
    inside :func:`index_builder.marketplace.plugin_entry`. Nothing
    downstream exploits it today only because both statement renderers
    pre-filter line breaks before a value reaches this helper.

    The negative control is ``pattern.match(value)`` below: it proves the
    OLD method (``match``) would have accepted a smuggled newline, so the
    refusal from ``match_or_raise`` beside it is demonstrably because of
    the method, not because the shape was already illegal.
    """
    assert pattern.match(value), (
        f"negative control failed: re.match did not accept {value!r}"
    )
    assert not pattern.fullmatch(value)
    with pytest.raises(ValueError):
        match_or_raise(value, pattern, "value")
