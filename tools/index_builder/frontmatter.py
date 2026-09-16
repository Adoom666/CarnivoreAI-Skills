"""The card and the front matter block, read out of a skill's SKILL.md.

A SKILL.md opens with a YAML block between two ``---`` lines. The app shows
the description before anything is installed, so it has to come out of the
skill's own text rather than out of a field somebody typed into the index:
an index that could say anything about a skill would be a place to lie
about one.

NOTHING IS INVENTED HERE. A skill with no description is REFUSED, because
"" in the index would render as a card with nothing on it and the reader
could not tell an empty description from a build that dropped the field.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

#: The fence a front matter block opens and closes with.
FENCE = "---"

#: How long a card's one line brief may be before it is cut. The card is a
#: list row; the full text is in the front matter block beside it.
BRIEF_MAX_CHARS = 200


@dataclass(frozen=True)
class SkillFrontMatter:
    """What a SKILL.md says about itself.

    - ``name``: the front matter name, or None when it declares none.
    - ``description``: the full description, always present.
    - ``license``, ``compatibility``: optional, carried through verbatim.
    - ``allowed_tools``: optional list, from ``allowed-tools`` or
      ``allowed_tools``; both spellings are in the wild.
    - ``tags``: optional list for the card.
    """

    name: Optional[str]
    description: str
    license: Optional[str]
    compatibility: Optional[str]
    allowed_tools: Optional[List[str]]
    tags: Optional[List[str]]


def _string_list(raw: object) -> Optional[List[str]]:
    """Coerce a front matter value to a list of strings, or None.

    :param raw: the parsed YAML value.
    :returns: the list, or None when the value is absent or not usable.

    A comma separated string is accepted because skills in the wild write
    ``allowed-tools: Read, Bash`` as often as they write a list.
    """
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        return items or None
    if isinstance(raw, str) and raw.strip():
        items = [part.strip() for part in raw.split(",") if part.strip()]
        return items or None
    return None


def parse_front_matter(skill_md: Path) -> SkillFrontMatter:
    """Read the YAML block at the top of a SKILL.md.

    Description: requires the file to OPEN with a ``---`` fence and to
      close it, parses the block with a safe loader, and requires a non
      empty ``description``. Every refusal names the file, because this
      runs over somebody else's contribution and the message is the only
      thing they will see.
    Inputs: skill_md (Path) - the SKILL.md itself.
    Output: SkillFrontMatter.
    Raises: ValueError when the fence is missing, the block is not a
      mapping, or the description is absent or empty.
    Example: parse_front_matter(Path("skills/adoom666/work/SKILL.md")).description
    """
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != FENCE:
        raise ValueError(f"{skill_md}: does not open with a {FENCE} front matter fence")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1)
                   if line.strip() == FENCE)
    except StopIteration as exc:
        raise ValueError(f"{skill_md}: the front matter fence is never closed") from exc

    block = yaml.safe_load("\n".join(lines[1:end])) or {}
    if not isinstance(block, dict):
        raise ValueError(f"{skill_md}: the front matter block is not a mapping")

    description = block.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{skill_md}: the front matter has no description")

    def optional(key: str) -> Optional[str]:
        """One front matter string, or None when it is absent or blank.

        :param key: the front matter key.
        :returns: the stripped value, or None. Blank and absent are the
            same answer on purpose: a key present but empty states
            nothing, and writing "" into the index would render as a
            field the publisher had filled in.
        """
        value = block.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    return SkillFrontMatter(
        name=optional("name"),
        description=description.strip(),
        license=optional("license"),
        compatibility=optional("compatibility"),
        allowed_tools=_string_list(
            block.get("allowed-tools", block.get("allowed_tools"))
        ),
        tags=_string_list(block.get("tags")),
    )


#: Every C0 control and DEL, minus the five ``str.split`` already folds
#: into a single space. ``" ".join(text.split())`` LOOKS LIKE IT
#: SANITISES AND DOES NOT: Python's whitespace set is space, tab, CR, LF,
#: vertical tab and form feed, so ESC, BEL, backspace and NUL passed
#: straight through and a published description carried an ANSI sequence
#: into the marketplace file. The consumer stripped it at render time,
#: which is luck rather than a guarantee.
#:
#: THEY ARE DELETED, NOT REPLACED WITH A SPACE, and punctuation is left
#: alone. A control character is not a word, it is an instruction to
#: whatever renders the text, so removing one changes nothing the
#: publisher said. An em dash or an emoji IS a character they meant a
#: reader to see, and rewriting it would be altering text whose folder
#: digest that publisher signed.
_CONTROL_STRIP = {
    code: None
    for code in list(range(0x20)) + [0x7F]
    if chr(code) not in " \t\n\r\v\f"
}


def brief_of(description: str) -> str:
    """Cut a description down to one card line.

    Description: takes the text up to the first sentence end when that is
      short enough, otherwise cuts on a word boundary and appends a single
      full stop so the row does not end mid word. Never returns empty,
      because the caller already refused an empty description. Every C0
      control and DEL is stripped first (see ``_CONTROL_STRIP``); the
      publisher's punctuation is left exactly as written.
    Inputs: description (str) - the full front matter description.
    Output: str, at most BRIEF_MAX_CHARS characters.
    Example: brief_of("Does one thing. Then another.") -> "Does one thing."
    """
    flat = " ".join(description.translate(_CONTROL_STRIP).split())
    head = flat.split(". ")[0].rstrip(".")
    candidate = f"{head}." if head else flat
    if len(candidate) <= BRIEF_MAX_CHARS:
        return candidate
    cut = flat[: BRIEF_MAX_CHARS - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return f"{cut}."


def card_and_fm(
    front: SkillFrontMatter, *, name: str,
) -> tuple[Dict[str, object], Dict[str, object]]:
    """Build the index's ``card`` and ``fm`` blocks from the front matter.

    Description: the card is what a list row shows, the fm block is what
      the install preview shows. Optional fields are OMITTED when absent
      rather than written as null, so the app never has to tell an absent
      field from one the build job failed to read.
    Inputs: front (SkillFrontMatter). name (str) - the folder name, used as
      the title when the front matter declares none.
    Output: (card, fm) - two plain dicts ready to serialise.
    Example: card_and_fm(front, name="work")[0]["title"] -> "work"
    """
    card: Dict[str, object] = {
        "title": front.name or name,
        "brief": brief_of(front.description),
    }
    if front.tags:
        card["tags"] = front.tags

    fm: Dict[str, object] = {"description": front.description}
    if front.license:
        fm["license"] = front.license
    if front.compatibility:
        fm["compatibility"] = front.compatibility
    if front.allowed_tools:
        fm["allowed_tools"] = front.allowed_tools
    return card, fm
