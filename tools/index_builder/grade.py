"""The quality grade: what the published specification actually requires.

WHAT THIS IS, AND WHAT IT REFUSES TO BE. Every version in the index carries a
grade of its own text and structure, written at publish time beside the AI
security review. The two answer different questions. The review asks whether a
skill does anything damaging. The grade asks whether a skill is BUILT the way
the Agent Skills specification says to build one, so an agent can find it, load
it, and follow it. Neither is a gate. A low grade never blocks a publish: what
a publisher ships is the publisher's business, and the grade is advisory in
exactly the sense the review is.

EVERY RULE CITES A PUBLISHED SOURCE OR IT DOES NOT EXIST. :data:`RULE_SOURCES`
maps every ``rule_id`` this module can emit to the URL it came from and the one
line that URL states. There is no rule in this file that is not in that table,
and :mod:`tests.test_grade` fails the build if one appears. That is the whole
discipline here: a grader that invents a rule is a grader that marks a
specification-conformant skill down for the author's taste, and the author of
this file does not get a vote.

"NOT GRADED" IS A FIRST CLASS ANSWER, exactly as the review's ``unavailable``
is. A rule that only applies when an optional field is present is reported as
not graded when that field is absent, never as a pass. A folder with no
readable ``SKILL.md`` grades as ``ungraded`` rather than as an ``F``: an F is a
measurement and this is the absence of one. A blank grade must never read as a
clean one.

IT READS THE FOLDER IT WAS HANDED AND NOTHING ELSE. Every read goes through
:func:`_read_text` and every path is resolved through :func:`_within`, which
refuses anything that leaves the folder. A body that links ``../../etc/passwd``
is reported as a reference that does not resolve, and the file is never opened.
The grade runs over a publisher's own text, so the text gets no reach.

NO MODEL IS CALLED. The grade is a pure function of bytes on disk, so it is
reproducible, it costs nothing, and two builds of the same commit produce the
same grade. Where the specification asks for a judgement a machine cannot make,
this module either uses a stated, documented proxy and says it is one, or it
declines to grade at all.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

import yaml

#: The two levels a rule can sit at. ``required`` is something a published
#: specification states with a MUST or lists as a required field; anything
#: weaker is ``recommended``. There is deliberately no third, softer level: a
#: level nothing can emit is dead wire shape, and a level that means "the
#: author of the grader would prefer it" is the taste this module refuses.
Level = Literal["required", "recommended"]

#: What a folder grades as when there is nothing to measure. It is not a
#: failing letter, because no rule ran.
GRADE_UNGRADED = "ungraded"

#: The specification's own numbers, each one carried here rather than inline
#: so the rule and the figure it enforces are read together.
NAME_MAX_CHARS = 64
DESCRIPTION_MAX_CHARS = 1024
COMPATIBILITY_MAX_CHARS = 500
BODY_MAX_LINES = 500

#: The most characters one note carries into the index. A grader that writes
#: an essay bloats the document everybody downloads.
MAX_DETAIL_CHARS = 240

#: THE ONE TABLE. ``rule_id`` to (source url, the one line that source states).
#: A rule that cannot be traced to a published requirement or recommendation
#: does not belong here, and a rule that is not here cannot be emitted.
RULE_SOURCES: Dict[str, Tuple[str, str]] = {
    "frontmatter.present": (
        "https://agentskills.io/specification#skill-md-format",
        "The SKILL.md file must contain YAML frontmatter followed by Markdown "
        "content.",
    ),
    "name.present": (
        "https://agentskills.io/specification#frontmatter",
        "name is a required frontmatter field.",
    ),
    "name.shape": (
        "https://agentskills.io/specification#name-field",
        "Must be 1-64 characters, may only contain lowercase alphanumeric "
        "characters and hyphens, must not start or end with a hyphen, and must "
        "not contain consecutive hyphens.",
    ),
    "name.matches-folder": (
        "https://agentskills.io/specification#name-field",
        "Must match the parent directory name.",
    ),
    "description.present": (
        "https://agentskills.io/specification#frontmatter",
        "description is a required frontmatter field and must be non-empty.",
    ),
    "description.length": (
        "https://agentskills.io/specification#description-field",
        "Must be 1-1024 characters.",
    ),
    "description.trigger": (
        "https://agentskills.io/specification#description-field",
        "Should describe both what the skill does and when to use it.",
    ),
    "body.present": (
        "https://agentskills.io/specification#body-content",
        "The Markdown body after the frontmatter contains the skill "
        "instructions.",
    ),
    "body.lines": (
        "https://agentskills.io/specification#progressive-disclosure",
        "Keep your main SKILL.md under 500 lines.",
    ),
    "compatibility.length": (
        "https://agentskills.io/specification#compatibility-field",
        "Must be 1-500 characters if provided.",
    ),
    "metadata.shape": (
        "https://agentskills.io/specification#metadata-field",
        "A map from string keys to string values.",
    ),
    "references.resolve": (
        "https://agentskills.io/specification#file-references",
        "When referencing other files in your skill, use relative paths from "
        "the skill root.",
    ),
    "bundled.referenced": (
        "https://agentskills.io/skill-creation/best-practices"
        "#structure-large-skills-with-progressive-disclosure",
        "The key is telling the agent when to load each file.",
    ),
    "paths.portable": (
        "https://code.claude.com/docs/en/skills",
        "Avoid absolute or machine-specific paths by using these substitution "
        "variables instead.",
    ),
}

#: What level each rule is graded at. Separate from the source table so the
#: drift test can prove the two cover exactly the same rules.
RULE_LEVELS: Dict[str, Level] = {
    "frontmatter.present": "required",
    "name.present": "required",
    "name.shape": "required",
    "name.matches-folder": "required",
    "description.present": "required",
    "description.length": "required",
    "body.present": "required",
    "compatibility.length": "required",
    "metadata.shape": "required",
    "description.trigger": "recommended",
    "body.lines": "recommended",
    "references.resolve": "recommended",
    "bundled.referenced": "recommended",
    "paths.portable": "recommended",
}

#: The shape the specification states for ``name``, written as one expression
#: so the four separate sentences it is made of cannot drift apart: lowercase
#: alphanumerics in runs, separated by SINGLE hyphens, which forbids a leading
#: hyphen, a trailing one and a consecutive pair in one pass.
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: THE DOCUMENTED PROXY FOR "SAYS WHEN TO USE IT", and it is a proxy, not a
#: judgement. The specification says a description should say when to use the
#: skill, and the agentskills.io verification checklist spells that out as
#: "Description uses imperative phrasing ('Use when...') and lists specific
#: contexts". No model is called to decide whether a sentence means that, so
#: this is a closed list of the literal phrasings that state a trigger
#: condition, matched case-insensitively against the description. A
#: description that states its trigger some other way passes no rule here and
#: is marked down: that is a known and accepted false negative, which is why
#: the rule is a recommendation and never a required one.
TRIGGER_MARKERS: Tuple[str, ...] = (
    "use when",
    "use this when",
    "use it when",
    "used when",
    "use whenever",
    "used whenever",
    "use for",
    "use this for",
    "use this skill when",
    "trigger when",
    "triggers when",
    "triggered when",
    "trigger on",
    "triggers on",
    "invoke when",
    "invoked when",
    "invoke for",
    "apply when",
    "applies when",
    "activate when",
    "reach for",
    "when the user",
    "when you",
    "whenever the user",
    "whenever you",
)

#: An absolute, machine-specific path: one rooted at a particular machine's
#: user or volume layout, which cannot resolve on anybody else's computer.
#: ``~/`` IS DELIBERATELY NOT HERE. It resolves for every user, so it is
#: neither absolute nor machine-specific, and marking it down would be a rule
#: no published source states.
MACHINE_PATH_RE = re.compile(
    r"(?:/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|/Volumes/[A-Za-z0-9._ -]+/"
    r"|[A-Za-z]:\\Users\\)"
)

#: A fenced code block, which the portability rule steps over: a fenced block
#: is an example being shown, not a path the skill asks an agent to follow.
FENCE_RE = re.compile(r"^(?P<fence>```|~~~).*?^(?P=fence)", re.M | re.S)

#: A markdown link target, and a backticked path under one of the three
#: directories the specification names. Those are the two ways a SKILL.md
#: points at a file it ships with.
LINK_RE = re.compile(r"\]\(\s*([^)\s]+?)\s*\)")
CODE_PATH_RE = re.compile(r"`((?:scripts|references|assets)/[^`\s]+)`")

#: Reference targets that are not a bundled file and are not this rule's
#: business: a URL, an absolute path, a bare anchor, a mail link, or a path
#: built from a substitution variable the agent expands at run time.
_NOT_A_BUNDLED_FILE = ("http://", "https://", "mailto:", "#", "/", "$", "{")

#: The file every skill has, which is never itself a bundled reference.
SKILL_FILE = "SKILL.md"

#: The fence a front matter block opens and closes with.
FENCE = "---"


@dataclass(frozen=True)
class GradeNote:
    """One rule, run against one folder, and what it found.

    - ``rule_id``: the key into :data:`RULE_SOURCES`.
    - ``level``: ``required`` or ``recommended``.
    - ``passed``: whether the folder satisfied it. A rule that did not apply
      is NOT a note; it is carried in :attr:`Grade.not_graded`, because a
      rule that never ran and a rule that passed are different facts.
    - ``detail``: one line naming what was measured, never a scolding.
    """

    rule_id: str
    level: Level
    passed: bool
    detail: str


@dataclass(frozen=True)
class Grade:
    """One folder's whole grade, as a frozen value.

    - ``grade``: ``A`` to ``F``, or :data:`GRADE_UNGRADED` when nothing could
      be measured.
    - ``notes``: every rule that RAN, in table order, passed or failed.
    - ``not_graded``: (rule_id, why) for every rule that did not apply, so a
      reader can tell an absent optional field from a check that was skipped
      by accident.
    """

    grade: str
    notes: Tuple[GradeNote, ...]
    not_graded: Tuple[Tuple[str, str], ...]

    @property
    def required_failed(self) -> int:
        """How many required rules the folder failed.

        :returns: the count.

        Example: Grade("A", (), ()).required_failed -> 0
        """
        return sum(
            1 for note in self.notes
            if note.level == "required" and not note.passed
        )

    @property
    def recommended_failed(self) -> int:
        """How many recommended rules the folder failed.

        :returns: the count.

        Example: Grade("A", (), ()).recommended_failed -> 0
        """
        return sum(
            1 for note in self.notes
            if note.level == "recommended" and not note.passed
        )

    def to_index(self) -> Dict[str, object]:
        """Render the grade for the index document, carrying only failures.

        Description: a passing note carries no information the letter does
          not already carry, and the index is a file every reader downloads,
          so only the FAILURES travel, with the counts that produced the
          letter and the ids of the rules that did not run. The published
          rule table in this module is what turns an id back into a sentence.
        Inputs: none.
        Output: the ``grade`` block for one version entry.
        Example: grade_skill(folder, manifest).to_index()["grade"] -> "A"
        """
        return {
            "grade": self.grade,
            "checked": len(self.notes),
            "failed": [
                {
                    "rule": note.rule_id,
                    "level": note.level,
                    "detail": note.detail[:MAX_DETAIL_CHARS],
                }
                for note in self.notes if not note.passed
            ],
            "not_graded": [rule_id for rule_id, _why in self.not_graded],
        }


def letter_for(required_failed: int, recommended_failed: int) -> str:
    """Turn the two failure counts into the published letter.

    Description: the letter is a function of COUNTS and of nothing else, so
      no rule is secretly worth more than another and nobody has to defend a
      weighting. A required failure is a departure from something the
      specification states, so one of those outranks any number of
      recommendations: the worst a skill that meets every requirement can
      score is a C, and the best a skill that misses one can score is a D.
    Inputs: required_failed (int), recommended_failed (int) - the counts.
    Output: str - one of A, B, C, D, F.
    Example: letter_for(0, 1) -> "B"
    """
    if required_failed >= 2:
        return "F"
    if required_failed == 1:
        return "D"
    if recommended_failed == 0:
        return "A"
    if recommended_failed == 1:
        return "B"
    return "C"


def _read_text(path: Path) -> Optional[str]:
    """Read one file as UTF-8, or return None when it cannot be read.

    :param path: the file.
    :returns: the text, or None when absent, unreadable or not UTF-8.

    THE ONE READING BOUNDARY IN THIS MODULE. Every read goes through here so
    a test can watch every path this grader opens and prove none of them
    left the folder it was handed.
    """
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _within(folder: Path, relpath: str) -> Optional[Path]:
    """Resolve a relative path inside the folder, or refuse it.

    Description: joins the path to the folder and normalises it WITHOUT
      touching the filesystem, then refuses anything whose normal form
      climbs out. An absolute path is refused outright. Nothing is opened
      here, so a reference that points outside is reported as a reference
      that does not resolve and is never followed.
    Inputs: folder (Path) - the skill folder. relpath (str) - the reference.
    Output: the path inside the folder, or None when it escapes.
    Example: _within(Path("/s"), "../etc/passwd") is None -> True
    """
    if os.path.isabs(relpath) or relpath.startswith("\\"):
        return None
    normal = os.path.normpath(relpath.replace("\\", "/"))
    if normal == ".." or normal.startswith("../") or normal.startswith("/"):
        return None
    return folder / normal


def split_skill_md(text: str) -> Optional[Tuple[str, str]]:
    """Split a SKILL.md into its front matter block and its body.

    Description: requires the file to OPEN with a ``---`` fence and to close
      it, which is what the specification states the format is. Returns None
      when either fence is missing, so the caller can fail the front matter
      rule rather than guessing where the body starts.
    Inputs: text (str) - the whole file.
    Output: (front matter text, body text), or None when unfenced.
    Example: split_skill_md("---\\nname: a\\n---\\nbody\\n")[1] -> "body\\n"
    """
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != FENCE:
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FENCE:
            return "".join(lines[1:index]), "".join(lines[index + 1:])
    return None


def read_manifest(folder: Path) -> Dict[str, object]:
    """Read a skill's front matter TOLERANTLY, for grading.

    Description: deliberately softer than
      :func:`index_builder.frontmatter.parse_front_matter`, which refuses a
      SKILL.md with no description because the index may not carry an empty
      card. A GRADER has to be able to read a skill that is wrong in order
      to say so, so every failure here is an empty mapping and the rules
      report what is missing.
    Inputs: folder (Path) - the skill folder.
    Output: the parsed front matter mapping, empty when there is none.
    Example: read_manifest(Path("skills/adoom666/sme"))["name"] -> "sme"
    """
    text = _read_text(folder / SKILL_FILE)
    if text is None:
        return {}
    split = split_skill_md(text)
    if split is None:
        return {}
    try:
        block = yaml.safe_load(split[0])
    except yaml.YAMLError:
        return {}
    return block if isinstance(block, dict) else {}


def _optional_text(manifest: Dict[str, object], key: str) -> Optional[str]:
    """Read one front matter value as a non empty string, or None.

    :param manifest: the parsed front matter.
    :param key: the field name.
    :returns: the stripped value, or None when absent or not a string.
    """
    value = manifest.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _bundled_files(folder: Path) -> List[str]:
    """List the folder's members, relative and POSIX spelled, SKILL.md aside.

    :param folder: the skill folder.
    :returns: the relative paths, sorted, symlinks and directories skipped.

    ``followlinks=False`` so a symlinked directory is never descended into,
    which is the same posture :mod:`index_builder.digest` takes and for the
    same reason: the digest does not cover one either.
    """
    found: List[str] = []
    root = str(folder)
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            full = Path(dirpath) / filename
            if full.is_symlink() or not full.is_file():
                continue
            relpath = os.path.relpath(str(full), root).replace(os.sep, "/")
            if relpath != SKILL_FILE:
                found.append(relpath)
    return sorted(found)


def _referenced_paths(body: str) -> List[str]:
    """Pull every bundled file reference out of a body, in order.

    :param body: the markdown body.
    :returns: the reference targets, de-duplicated, order preserved.

    A URL, an absolute path, a bare anchor and a path built from a
    substitution variable are all dropped: none of them name a file this
    folder ships, so holding them to a folder member would be inventing a
    rule.
    """
    seen: List[str] = []
    for match in list(LINK_RE.finditer(body)) + list(CODE_PATH_RE.finditer(body)):
        target = match.group(1).split("#", 1)[0].strip()
        if not target or target.startswith(_NOT_A_BUNDLED_FILE):
            continue
        if "://" in target or "$" in target:
            continue
        if target not in seen:
            seen.append(target)
    return seen


def _strip_fences(body: str) -> str:
    """Remove fenced code blocks from a body.

    :param body: the markdown body.
    :returns: the body with every ``` or ~~~ block replaced by a blank line.

    A path inside a fence is an example being SHOWN. The portability rule is
    about paths a skill asks an agent to follow, so the fenced ones are out
    of its scope and are removed before it looks.
    """
    return FENCE_RE.sub("\n", body)


def _name_rules(
    manifest: Dict[str, object], folder_name: str,
) -> Tuple[List[GradeNote], List[Tuple[str, str]]]:
    """Grade the three rules the specification states about ``name``.

    :param manifest: the parsed front matter.
    :param folder_name: the skill folder's own directory name.
    :returns: (notes, not graded), because the shape and folder rules cannot
        run at all when there is no name to hold to them.
    """
    name = _optional_text(manifest, "name")
    if name is None:
        return (
            [GradeNote(
                "name.present", "required", False,
                "the front matter declares no name",
            )],
            [
                ("name.shape", "there is no name to check the shape of"),
                ("name.matches-folder", "there is no name to compare with the folder"),
            ],
        )

    notes = [GradeNote("name.present", "required", True, f"name is {name!r}")]
    shaped = bool(NAME_RE.match(name)) and len(name) <= NAME_MAX_CHARS
    notes.append(GradeNote(
        "name.shape", "required", shaped,
        f"name is {len(name)} characters"
        + ("" if shaped else
           ", and must be 1 to 64 lowercase letters, digits and single hyphens, "
           "with no leading, trailing or consecutive hyphen"),
    ))
    matches = name == folder_name
    notes.append(GradeNote(
        "name.matches-folder", "required", matches,
        f"name {name!r} matches the folder" if matches
        else f"name is {name!r} but the folder is {folder_name!r}",
    ))
    return notes, []


def _description_rules(
    manifest: Dict[str, object],
) -> Tuple[List[GradeNote], List[Tuple[str, str]]]:
    """Grade the three rules that hold the description.

    :param manifest: the parsed front matter.
    :returns: (notes, not graded). Length and trigger cannot run with no
        description, so they are reported as not graded rather than failed:
        one missing field must not read as three separate defects.
    """
    description = _optional_text(manifest, "description")
    if description is None:
        return (
            [GradeNote(
                "description.present", "required", False,
                "the front matter declares no description, which is the one "
                "field an agent matches a request against",
            )],
            [
                ("description.length", "there is no description to measure"),
                ("description.trigger", "there is no description to read"),
            ],
        )

    notes = [GradeNote(
        "description.present", "required", True,
        f"description is {len(description)} characters",
    )]
    within = len(description) <= DESCRIPTION_MAX_CHARS
    notes.append(GradeNote(
        "description.length", "required", within,
        f"description is {len(description)} characters"
        + ("" if within else f", over the {DESCRIPTION_MAX_CHARS} the "
                             f"specification allows"),
    ))
    lowered = description.lower()
    marker = next((m for m in TRIGGER_MARKERS if m in lowered), None)
    notes.append(GradeNote(
        "description.trigger", "recommended", marker is not None,
        f"the description states a trigger condition ({marker!r})"
        if marker is not None else
        "no stated trigger condition was found. this is a proxy: the grader "
        "looks for a closed list of phrasings such as 'use when' or 'triggers "
        "when', and a description that says when to use the skill some other "
        "way is marked down here in error",
    ))
    return notes, []


def _optional_field_rules(
    manifest: Dict[str, object],
) -> Tuple[List[GradeNote], List[Tuple[str, str]]]:
    """Grade the two optional fields that carry a stated constraint.

    :param manifest: the parsed front matter.
    :returns: (notes, not graded). Each rule runs only when its field is
        declared; an absent optional field is NOT a failure and is never
        reported as a pass either.
    """
    notes: List[GradeNote] = []
    skipped: List[Tuple[str, str]] = []

    if "compatibility" in manifest:
        value = manifest.get("compatibility")
        text = value if isinstance(value, str) else ""
        ok = 1 <= len(text.strip()) <= COMPATIBILITY_MAX_CHARS
        notes.append(GradeNote(
            "compatibility.length", "required", ok,
            f"compatibility is {len(text.strip())} characters"
            + ("" if ok else f", outside the 1 to {COMPATIBILITY_MAX_CHARS} "
                             f"the specification allows"),
        ))
    else:
        skipped.append((
            "compatibility.length", "the front matter declares no compatibility",
        ))

    if "metadata" in manifest:
        value = manifest.get("metadata")
        ok = isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        )
        notes.append(GradeNote(
            "metadata.shape", "required", ok,
            "metadata is a map of string keys to string values" if ok else
            "metadata must be a map from string keys to string values",
        ))
    else:
        skipped.append(("metadata.shape", "the front matter declares no metadata"))

    return notes, skipped


def _body_rules(folder: Path, body: str) -> List[GradeNote]:
    """Grade the four rules that hold the markdown body and what it ships.

    :param folder: the skill folder, for resolving references.
    :param body: the markdown body, front matter already removed.
    :returns: the notes, in table order.
    """
    notes: List[GradeNote] = []

    stripped = body.strip()
    notes.append(GradeNote(
        "body.present", "required", bool(stripped),
        f"the body is {len(body.splitlines())} lines" if stripped else
        "the body is empty, so an activated skill loads no instructions",
    ))

    line_count = len(body.splitlines())
    under = line_count < BODY_MAX_LINES
    notes.append(GradeNote(
        "body.lines", "recommended", under,
        f"the body is {line_count} lines"
        + ("" if under else f", over the {BODY_MAX_LINES} the specification "
                            f"recommends; move reference material into "
                            f"references/"),
    ))

    referenced = _referenced_paths(body)
    unresolved: List[str] = []
    for target in referenced:
        resolved = _within(folder, target)
        if resolved is None or not resolved.is_file():
            unresolved.append(target)
    notes.append(GradeNote(
        "references.resolve", "recommended", not unresolved,
        f"all {len(referenced)} bundled file references resolve"
        if referenced and not unresolved else
        "the body references no bundled files" if not referenced else
        f"{len(unresolved)} reference(s) name no file in this folder: "
        + ", ".join(unresolved[:5]),
    ))

    bundled = _bundled_files(folder)
    unmentioned = [relpath for relpath in bundled if relpath not in body]
    notes.append(GradeNote(
        "bundled.referenced", "recommended", not unmentioned,
        f"all {len(bundled)} bundled files are named in the body"
        if bundled and not unmentioned else
        "the folder bundles no files besides SKILL.md" if not bundled else
        f"{len(unmentioned)} bundled file(s) the body never names, so nothing "
        f"tells an agent when to load them: " + ", ".join(unmentioned[:5]),
    ))

    prose = _strip_fences(body)
    machine = sorted({match.group(0) for match in MACHINE_PATH_RE.finditer(prose)})
    notes.append(GradeNote(
        "paths.portable", "recommended", not machine,
        "the body names no absolute machine-specific path" if not machine else
        f"{len(machine)} absolute machine-specific path prefix(es) outside a "
        f"code fence, which cannot resolve for another user: "
        + ", ".join(machine[:5]),
    ))
    return notes


def grade_skill(folder: Path, manifest: Dict[str, object]) -> Grade:
    """Grade one skill folder against the published specification.

    Description: runs every rule in :data:`RULE_SOURCES` that APPLIES, and
      reports the rest as not graded. It never raises and never reads
      outside ``folder``. A folder with no readable SKILL.md returns
      :data:`GRADE_UNGRADED` with every rule not graded, because an F is a
      measurement and this is the absence of one.
    Inputs: folder (Path) - the skill folder, as it would be installed.
      manifest (dict) - its front matter, from :func:`read_manifest`.
    Output: Grade.
    Example: grade_skill(p, read_manifest(p)).grade -> "A"
    """
    text = _read_text(folder / SKILL_FILE)
    if text is None:
        return Grade(
            grade=GRADE_UNGRADED,
            notes=(),
            not_graded=tuple(
                (rule_id, f"{folder.name} has no readable {SKILL_FILE}")
                for rule_id in RULE_SOURCES
            ),
        )

    split = split_skill_md(text)
    notes: List[GradeNote] = []
    skipped: List[Tuple[str, str]] = []

    notes.append(GradeNote(
        "frontmatter.present", "required", split is not None,
        "the file opens and closes a front matter fence" if split is not None
        else f"the file does not open and close a {FENCE} front matter fence",
    ))
    body = split[1] if split is not None else text

    for produced, not_run in (
        _name_rules(manifest, folder.name),
        _description_rules(manifest),
        _optional_field_rules(manifest),
    ):
        notes.extend(produced)
        skipped.extend(not_run)
    notes.extend(_body_rules(folder, body))

    order = list(RULE_SOURCES)
    notes.sort(key=lambda note: order.index(note.rule_id))
    grade = Grade(grade="", notes=tuple(notes), not_graded=tuple(skipped))
    return Grade(
        grade=letter_for(grade.required_failed, grade.recommended_failed),
        notes=grade.notes,
        not_graded=grade.not_graded,
    )


def grade_folder(folder: Path) -> Dict[str, object]:
    """Grade a folder and render the block the index carries.

    Description: the one call the build job makes. It reads the front matter
      itself so no caller can hand the grader a manifest from a different
      folder than the one it is grading.
    Inputs: folder (Path) - the skill folder.
    Output: the ``grade`` block for one version entry.
    Example: grade_folder(Path("skills/adoom666/sme"))["grade"] -> "A"
    """
    return grade_skill(folder, read_manifest(folder)).to_index()


def summary_table(document: Dict[str, object]) -> str:
    """Render the per-skill grade table the verify job prints.

    Description: one row per version, naming the letter and every rule it
      failed. A version carrying no grade block is printed as such rather
      than skipped, because a table that quietly omits a row reads as a
      table where everything passed.
    Inputs: document (dict) - the assembled index.
    Output: str - github flavoured markdown, ending in one newline.
    Example: summary_table({"items": []}).splitlines()[0] -> "## quality grades"
    """
    lines = [
        "## quality grades",
        "",
        "Advisory. A grade never blocks a publish. Every rule cites the "
        "published requirement it came from in `tools/index_builder/grade.py`.",
        "",
        "| skill | version | grade | failed |",
        "|---|---|---|---|",
    ]
    items = document.get("items")
    rows = 0
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        versions = item.get("versions")
        for version in versions if isinstance(versions, list) else []:
            if not isinstance(version, dict):
                continue
            rows += 1
            block = version.get("grade")
            if not isinstance(block, dict):
                lines.append(
                    f"| {item.get('id', '?')} | {version.get('v', '?')} | "
                    f"not graded | this build wrote no grade |"
                )
                continue
            failed = block.get("failed")
            names = ", ".join(
                str(entry.get("rule"))
                for entry in (failed if isinstance(failed, list) else [])
                if isinstance(entry, dict)
            )
            lines.append(
                f"| {item.get('id', '?')} | {version.get('v', '?')} | "
                f"{block.get('grade', '?')} | {names or 'nothing'} |"
            )
    if not rows:
        lines.append("| none | | | this build published no versions |")
    return "\n".join(lines) + "\n"
