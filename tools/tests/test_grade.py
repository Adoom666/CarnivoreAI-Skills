"""The quality grade, one case per rule, each proven able to go red.

THE GREEN CASES ARE WORTH NOTHING ON THEIR OWN. A grader that returns "A" for
everything passes every happy path test ever written, so every rule below is
exercised twice: once against a fixture that violates it, and once against one
that does not. That is the failure shape this repository has been bitten by
most often, and it is the reason the file is laid out in pairs.

THREE CLAIMS BEYOND THE RULES THEMSELVES:

1. A folder with no SKILL.md grades as UNGRADED, never as an F. An F is a
   measurement; a missing file is the absence of one, and collapsing the two
   would publish a verdict nobody took.
2. THE SOURCE TABLE COVERS EVERY RULE THE GRADER CAN EMIT, and the grader can
   emit every rule in the table. That is the drift test: a rule added without
   its citation, or a citation left behind by a deleted rule, fails the build.
3. THE GRADER READS THE FOLDER IT WAS HANDED AND NOTHING ELSE. A body that
   links out of the folder is reported as a reference that does not resolve,
   and the file it names is never opened. Proven by watching every read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from index_builder import grade as grade_module
from index_builder.grade import (
    GRADE_UNGRADED,
    RULE_LEVELS,
    RULE_SOURCES,
    Grade,
    GradeNote,
    _within,
    grade_folder,
    grade_skill,
    letter_for,
    read_manifest,
    summary_table,
)

#: A description that satisfies every description rule, so a test changing one
#: other thing is not quietly failing this one too.
GOOD_DESCRIPTION = (
    "Renders a chart from a csv file and writes it as a png. "
    "Use when the user asks for a chart, a plot or a graph from tabular data."
)

#: A body that satisfies every body rule.
GOOD_BODY = "# demo\n\nRead the csv, plot it, write the png.\n"


def _write_skill(
    root: Path,
    *,
    folder: str = "demo",
    front: Optional[Dict[str, object]] = None,
    body: str = GOOD_BODY,
    files: Optional[Dict[str, str]] = None,
    raw: Optional[str] = None,
) -> Path:
    """Build one skill folder on disk and hand back its path.

    Description: writes a SKILL.md from ``front`` and ``body`` unless ``raw``
      is given, in which case the file is written verbatim so a test can
      produce a shape the front matter renderer could not.
    Inputs: root (Path) - a tmp_path. folder (str) - the directory name.
      front (dict or None) - the front matter fields; None means the good
      default. body (str) - the markdown body. files (dict or None) -
      relative path to content, for bundled files. raw (str or None) - the
      whole SKILL.md, bypassing front and body.
    Output: Path - the skill folder.
    Example: _write_skill(tmp_path, front={"name": "demo"})
    """
    import yaml

    skill = root / folder
    skill.mkdir(parents=True, exist_ok=True)
    if raw is None:
        fields = {"name": folder, "description": GOOD_DESCRIPTION}
        if front is not None:
            fields = front
        block = yaml.safe_dump(fields, sort_keys=False, allow_unicode=True)
        raw = f"---\n{block}---\n\n{body}"
    (skill / "SKILL.md").write_text(raw, encoding="utf-8")
    for relpath, content in (files or {}).items():
        target = skill / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return skill


def _grade(folder: Path) -> Grade:
    """Grade a folder the way the build job does.

    :param folder: the skill folder.
    :returns: the Grade.
    """
    return grade_skill(folder, read_manifest(folder))


def _note(graded: Grade, rule_id: str) -> GradeNote:
    """Find the one note for a rule, failing the test when it did not run.

    :param graded: the grade.
    :param rule_id: the rule to look for.
    :returns: the note.
    :raises AssertionError: when the rule did not run, which is a different
        answer from failing and must never be read as one.
    """
    for note in graded.notes:
        if note.rule_id == rule_id:
            return note
    raise AssertionError(
        f"{rule_id} did not run at all. it is "
        f"{'declared not graded' if rule_id in dict(graded.not_graded) else 'missing'}"
    )


def _skipped(graded: Grade) -> Dict[str, str]:
    """The rules that did not apply, as a mapping of id to reason."""
    return dict(graded.not_graded)


# --------------------------------------------------------------------------
# frontmatter.present
# --------------------------------------------------------------------------

def test_a_file_with_no_front_matter_fence_fails(tmp_path: Path) -> None:
    """A SKILL.md that is only markdown declares nothing an agent can match."""
    skill = _write_skill(tmp_path, raw="# demo\n\nno front matter here.\n")
    assert _note(_grade(skill), "frontmatter.present").passed is False


def test_a_fenced_file_passes(tmp_path: Path) -> None:
    """And the same check goes green on a properly fenced one."""
    assert _note(_grade(_write_skill(tmp_path)), "frontmatter.present").passed


def test_an_unclosed_fence_fails(tmp_path: Path) -> None:
    """An opening fence with no closing one is not a front matter block."""
    skill = _write_skill(tmp_path, raw="---\nname: demo\n\n# demo\n")
    assert _note(_grade(skill), "frontmatter.present").passed is False


# --------------------------------------------------------------------------
# name.present, name.shape, name.matches-folder
# --------------------------------------------------------------------------

def test_a_missing_name_fails_and_skips_the_two_rules_that_need_one(
    tmp_path: Path,
) -> None:
    """One missing field must not be reported as three separate defects."""
    skill = _write_skill(tmp_path, front={"description": GOOD_DESCRIPTION})
    graded = _grade(skill)
    assert _note(graded, "name.present").passed is False
    skipped = _skipped(graded)
    assert "name.shape" in skipped and "name.matches-folder" in skipped


def test_a_declared_name_passes(tmp_path: Path) -> None:
    """The same rule green."""
    assert _note(_grade(_write_skill(tmp_path)), "name.present").passed


@pytest.mark.parametrize(
    "name",
    ["Demo", "de mo", "demo_skill", "-demo", "demo-", "de--mo", "démo", "d" * 65],
)
def test_a_name_outside_the_stated_shape_fails(tmp_path: Path, name: str) -> None:
    """Uppercase, spaces, underscores, hyphen edges, doubles and over 64."""
    skill = _write_skill(
        tmp_path, folder=name if "/" not in name else "demo",
        front={"name": name, "description": GOOD_DESCRIPTION},
    )
    assert _note(_grade(skill), "name.shape").passed is False


@pytest.mark.parametrize("name", ["demo", "pdf-processing", "a", "a1-b2-c3", "d" * 64])
def test_a_name_inside_the_stated_shape_passes(tmp_path: Path, name: str) -> None:
    """The shapes the specification's own examples use."""
    skill = _write_skill(
        tmp_path, folder=name, front={"name": name, "description": GOOD_DESCRIPTION},
    )
    assert _note(_grade(skill), "name.shape").passed


def test_a_name_that_is_not_the_folder_fails(tmp_path: Path) -> None:
    """The spec requires the two to match, and an agent resolves the folder."""
    skill = _write_skill(
        tmp_path, folder="demo",
        front={"name": "something-else", "description": GOOD_DESCRIPTION},
    )
    note = _note(_grade(skill), "name.matches-folder")
    assert note.passed is False
    assert "something-else" in note.detail and "demo" in note.detail


def test_a_name_that_is_the_folder_passes(tmp_path: Path) -> None:
    """The same rule green."""
    assert _note(_grade(_write_skill(tmp_path)), "name.matches-folder").passed


# --------------------------------------------------------------------------
# description.present, description.length, description.trigger
# --------------------------------------------------------------------------

def test_a_missing_description_fails_and_skips_length_and_trigger(
    tmp_path: Path,
) -> None:
    """There is nothing to measure or read, so neither rule is reported."""
    skill = _write_skill(tmp_path, front={"name": "demo"})
    graded = _grade(skill)
    assert _note(graded, "description.present").passed is False
    skipped = _skipped(graded)
    assert "description.length" in skipped and "description.trigger" in skipped


def test_an_empty_description_fails(tmp_path: Path) -> None:
    """Whitespace is not a description an agent can match a request against."""
    skill = _write_skill(tmp_path, front={"name": "demo", "description": "   "})
    assert _note(_grade(skill), "description.present").passed is False


def test_a_description_over_the_cap_fails(tmp_path: Path) -> None:
    """1024 characters is the specification's hard limit, not a guideline."""
    long_one = "Use when the user asks. " + ("x" * 1024)
    skill = _write_skill(
        tmp_path, front={"name": "demo", "description": long_one},
    )
    note = _note(_grade(skill), "description.length")
    assert note.passed is False
    assert "1024" in note.detail


def test_a_description_at_the_cap_passes(tmp_path: Path) -> None:
    """Exactly 1024 is inside the stated range of 1 to 1024."""
    at_cap = ("Use when the user asks. " + "x" * 1024)[:1024]
    skill = _write_skill(tmp_path, front={"name": "demo", "description": at_cap})
    assert _note(_grade(skill), "description.length").passed


def test_a_description_with_no_trigger_condition_is_marked_down(
    tmp_path: Path,
) -> None:
    """It says what the skill does and never says when to reach for it."""
    skill = _write_skill(
        tmp_path,
        front={
            "name": "demo",
            "description": "Generates a comprehensive readme from codebase analysis.",
        },
    )
    note = _note(_grade(skill), "description.trigger")
    assert note.passed is False
    assert note.level == "recommended", "a documented proxy is never a requirement"
    assert "proxy" in note.detail, "the note must say the measurement is a proxy"


@pytest.mark.parametrize(
    "description",
    [
        "Plots charts. Use when the user asks for a chart.",
        "Plots charts. Triggers when the user mentions a graph.",
        "Plots charts. Invoke when data needs a picture.",
        "Front end design skills which should be used whenever you change a UI.",
        "Plots charts. Reach for this when the user has tabular data.",
    ],
)
def test_a_description_that_states_its_trigger_passes(
    tmp_path: Path, description: str,
) -> None:
    """Every phrasing in the documented closed list, and the rule is green."""
    skill = _write_skill(
        tmp_path, front={"name": "demo", "description": description},
    )
    assert _note(_grade(skill), "description.trigger").passed


# --------------------------------------------------------------------------
# body.present, body.lines
# --------------------------------------------------------------------------

def test_an_empty_body_fails(tmp_path: Path) -> None:
    """An activated skill with no body loads no instructions at all."""
    skill = _write_skill(tmp_path, body="   \n\n")
    assert _note(_grade(skill), "body.present").passed is False


def test_a_body_with_instructions_passes(tmp_path: Path) -> None:
    """The same rule green."""
    assert _note(_grade(_write_skill(tmp_path)), "body.present").passed


def test_a_body_over_five_hundred_lines_is_marked_down(tmp_path: Path) -> None:
    """The specification's recommended ceiling for the main file."""
    skill = _write_skill(tmp_path, body="\n".join(f"line {i}" for i in range(600)))
    note = _note(_grade(skill), "body.lines")
    assert note.passed is False
    assert "500" in note.detail and note.level == "recommended"


def test_a_body_under_five_hundred_lines_passes(tmp_path: Path) -> None:
    """The same rule green, and a low grade never comes from length alone."""
    skill = _write_skill(tmp_path, body="\n".join(f"line {i}" for i in range(400)))
    assert _note(_grade(skill), "body.lines").passed


# --------------------------------------------------------------------------
# compatibility.length, metadata.shape: graded only when declared
# --------------------------------------------------------------------------

def test_an_absent_compatibility_is_not_graded_rather_than_passed(
    tmp_path: Path,
) -> None:
    """Most skills need no compatibility field, and absence is not a pass."""
    graded = _grade(_write_skill(tmp_path))
    assert "compatibility.length" in _skipped(graded)
    with pytest.raises(AssertionError):
        _note(graded, "compatibility.length")


def test_a_compatibility_over_five_hundred_characters_fails(tmp_path: Path) -> None:
    """1 to 500 is stated, so 501 is outside it."""
    skill = _write_skill(
        tmp_path,
        front={
            "name": "demo", "description": GOOD_DESCRIPTION,
            "compatibility": "x" * 501,
        },
    )
    assert _note(_grade(skill), "compatibility.length").passed is False


def test_a_compatibility_inside_the_range_passes(tmp_path: Path) -> None:
    """The same rule green, on the specification's own example wording."""
    skill = _write_skill(
        tmp_path,
        front={
            "name": "demo", "description": GOOD_DESCRIPTION,
            "compatibility": "Requires git, docker, jq, and access to the internet",
        },
    )
    assert _note(_grade(skill), "compatibility.length").passed


def test_an_absent_metadata_is_not_graded_rather_than_passed(
    tmp_path: Path,
) -> None:
    """Same posture as compatibility: an optional field nobody declared."""
    assert "metadata.shape" in _skipped(_grade(_write_skill(tmp_path)))


def test_metadata_that_is_not_strings_to_strings_fails(tmp_path: Path) -> None:
    """The spec states a map from string keys to string values."""
    skill = _write_skill(
        tmp_path,
        front={
            "name": "demo", "description": GOOD_DESCRIPTION,
            "metadata": {"author": "example-org", "version": 1.0},
        },
    )
    assert _note(_grade(skill), "metadata.shape").passed is False


def test_metadata_of_strings_to_strings_passes(tmp_path: Path) -> None:
    """The specification's own example, quoted version included."""
    skill = _write_skill(
        tmp_path,
        front={
            "name": "demo", "description": GOOD_DESCRIPTION,
            "metadata": {"author": "example-org", "version": "1.0"},
        },
    )
    assert _note(_grade(skill), "metadata.shape").passed


# --------------------------------------------------------------------------
# references.resolve, bundled.referenced
# --------------------------------------------------------------------------

def test_a_reference_to_a_file_the_folder_does_not_have_fails(
    tmp_path: Path,
) -> None:
    """The link resolves to nothing once the folder is installed elsewhere."""
    skill = _write_skill(
        tmp_path,
        body="# demo\n\nSee [the guide](references/missing.md) for details.\n",
    )
    note = _note(_grade(skill), "references.resolve")
    assert note.passed is False
    assert "references/missing.md" in note.detail


def test_a_reference_to_a_bundled_file_passes(tmp_path: Path) -> None:
    """The same shape, with the file actually shipped beside SKILL.md."""
    skill = _write_skill(
        tmp_path,
        body="# demo\n\nSee [the guide](references/guide.md) for details.\n",
        files={"references/guide.md": "# guide\n"},
    )
    assert _note(_grade(skill), "references.resolve").passed


def test_a_url_and_an_anchor_are_not_treated_as_bundled_files(
    tmp_path: Path,
) -> None:
    """Neither names a file this folder ships, so neither is this rule's job."""
    skill = _write_skill(
        tmp_path,
        body=(
            "# demo\n\n[spec](https://agentskills.io/specification) and "
            "[below](#later) and `${CLAUDE_SKILL_DIR}/scripts/run.sh`.\n"
        ),
    )
    assert _note(_grade(skill), "references.resolve").passed


def test_a_bundled_file_the_body_never_names_is_marked_down(
    tmp_path: Path,
) -> None:
    """Nothing tells an agent when to load it, so it never loads."""
    skill = _write_skill(
        tmp_path, files={"references/orphan.md": "# orphan\n"},
    )
    note = _note(_grade(skill), "bundled.referenced")
    assert note.passed is False
    assert "references/orphan.md" in note.detail


def test_bundled_files_the_body_names_pass(tmp_path: Path) -> None:
    """The shape design-engineer ships: one line per reference file."""
    skill = _write_skill(
        tmp_path,
        body=(
            "# demo\n\nSee [references/a.md](references/a.md) for a.\n"
            "See [references/b.md](references/b.md) for b.\n"
        ),
        files={"references/a.md": "a\n", "references/b.md": "b\n"},
    )
    assert _note(_grade(skill), "bundled.referenced").passed


def test_a_folder_with_only_a_skill_md_passes_the_bundling_rule(
    tmp_path: Path,
) -> None:
    """Shipping nothing is not the same as shipping something unmentioned."""
    assert _note(_grade(_write_skill(tmp_path)), "bundled.referenced").passed


# --------------------------------------------------------------------------
# paths.portable
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path",
    ["/Users/adam/notes.md", "/home/adam/notes.md", "/Volumes/Data/notes.md"],
)
def test_an_absolute_machine_specific_path_in_prose_is_marked_down(
    tmp_path: Path, path: str,
) -> None:
    """It cannot resolve on anybody else's computer once installed."""
    skill = _write_skill(tmp_path, body=f"# demo\n\nRead {path} first.\n")
    note = _note(_grade(skill), "paths.portable")
    assert note.passed is False


def test_the_same_path_inside_a_code_fence_is_not_marked_down(
    tmp_path: Path,
) -> None:
    """A fenced block is an example being shown, not a path to follow."""
    skill = _write_skill(
        tmp_path,
        body="# demo\n\n```bash\ncat /Users/adam/notes.md\n```\n",
    )
    assert _note(_grade(skill), "paths.portable").passed


def test_a_home_relative_path_is_not_marked_down(tmp_path: Path) -> None:
    """``~/`` resolves for every user, so it is not machine-specific.

    Marking it down would be a rule no published source states, which is
    exactly what this grader refuses to do.
    """
    skill = _write_skill(tmp_path, body="# demo\n\nRead ~/.claude/settings.json.\n")
    assert _note(_grade(skill), "paths.portable").passed


# --------------------------------------------------------------------------
# ungradeable, and the letter
# --------------------------------------------------------------------------

def test_a_folder_with_no_skill_md_is_ungraded_not_failed(tmp_path: Path) -> None:
    """An F is a measurement; this is the absence of one, and it says so."""
    empty = tmp_path / "empty"
    empty.mkdir()
    graded = grade_skill(empty, read_manifest(empty))
    assert graded.grade == GRADE_UNGRADED
    assert graded.notes == ()
    assert set(dict(graded.not_graded)) == set(RULE_SOURCES)


def test_a_folder_that_does_not_exist_is_ungraded_rather_than_crashing(
    tmp_path: Path,
) -> None:
    """The grader is total: it never raises on input it cannot read."""
    assert grade_skill(tmp_path / "nope", {}).grade == GRADE_UNGRADED


def test_an_unparseable_front_matter_block_reads_as_no_manifest(
    tmp_path: Path,
) -> None:
    """Broken yaml grades as a skill declaring nothing, and does not raise."""
    skill = _write_skill(tmp_path, raw="---\nname: [unclosed\n---\n\nbody\n")
    assert read_manifest(skill) == {}
    assert _grade(skill).grade in {"D", "F"}


@pytest.mark.parametrize(
    "required, recommended, expected",
    [
        (0, 0, "A"), (0, 1, "B"), (0, 2, "C"), (0, 5, "C"),
        (1, 0, "D"), (1, 4, "D"), (2, 0, "F"), (9, 9, "F"),
    ],
)
def test_the_letter_is_a_function_of_the_two_counts(
    required: int, recommended: int, expected: str,
) -> None:
    """No rule is secretly worth more than another, and the table says so."""
    assert letter_for(required, recommended) == expected


def test_a_conformant_skill_grades_a(tmp_path: Path) -> None:
    """The whole thing end to end, with every rule that runs coming up green."""
    graded = _grade(_write_skill(tmp_path))
    assert graded.grade == "A"
    assert graded.required_failed == 0 and graded.recommended_failed == 0
    assert all(note.passed for note in graded.notes)


def test_one_recommendation_missed_is_a_b_and_never_a_failure(
    tmp_path: Path,
) -> None:
    """A recommendation is advice. It costs a letter, it does not fail a skill."""
    skill = _write_skill(
        tmp_path,
        front={"name": "demo", "description": "Generates a readme from a codebase."},
    )
    graded = _grade(skill)
    assert graded.grade == "B"
    assert graded.required_failed == 0


# --------------------------------------------------------------------------
# the drift test: the table and the grader cover the same rules
# --------------------------------------------------------------------------

def test_every_rule_has_a_source_and_a_level(tmp_path: Path) -> None:
    """A rule with no citation does not exist, and the build says so.

    This is the discipline the whole module rests on. A rule added without
    the URL it came from would be the grader's author marking a
    specification-conformant skill down for their own taste.
    """
    assert set(RULE_SOURCES) == set(RULE_LEVELS), (
        "the source table and the level table name different rules"
    )
    for rule_id, (url, statement) in RULE_SOURCES.items():
        assert url.startswith("https://"), f"{rule_id} cites no https source"
        assert statement.strip(), f"{rule_id} cites a source but states nothing"
        assert RULE_LEVELS[rule_id] in ("required", "recommended")


def test_every_rule_the_grader_emits_is_in_the_source_table(
    tmp_path: Path,
) -> None:
    """Run the grader over a battery of fixtures and check every id it emits."""
    fixtures = [
        _write_skill(tmp_path / "a"),
        _write_skill(tmp_path / "b", raw="no front matter\n"),
        _write_skill(tmp_path / "c", front={"name": "c"}),
        _write_skill(
            tmp_path / "d",
            front={
                "name": "d", "description": GOOD_DESCRIPTION,
                "compatibility": "needs git", "metadata": {"author": "x"},
            },
            files={"references/x.md": "x\n"},
        ),
    ]
    emitted = set()
    for folder in fixtures:
        graded = _grade(folder)
        emitted.update(note.rule_id for note in graded.notes)
        emitted.update(rule_id for rule_id, _ in graded.not_graded)
    unknown = emitted - set(RULE_SOURCES)
    assert not unknown, f"the grader emitted rules with no citation: {sorted(unknown)}"


def test_every_rule_either_runs_or_is_declared_not_graded(tmp_path: Path) -> None:
    """The two lists together are exactly the table: nothing is silently absent.

    A rule that neither ran nor was declared skipped is a check that
    examined nothing while the grade read as complete.
    """
    graded = _grade(_write_skill(tmp_path))
    covered = {note.rule_id for note in graded.notes}
    covered.update(rule_id for rule_id, _ in graded.not_graded)
    assert covered == set(RULE_SOURCES)


def test_every_skipped_rule_carries_a_reason(tmp_path: Path) -> None:
    """"Not graded" with no reason is indistinguishable from a bug."""
    for rule_id, why in _grade(_write_skill(tmp_path)).not_graded:
        assert why.strip(), f"{rule_id} was skipped with no reason given"


# --------------------------------------------------------------------------
# the grader reads the folder it was handed and nothing else
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "escape",
    [
        "../outside.md",
        "../../etc/passwd",
        "/etc/passwd",
        "references/../../outside.md",
        "..",
        "\\\\server\\share",
    ],
)
def test_a_path_that_leaves_the_folder_is_refused_without_being_opened(
    tmp_path: Path, escape: str,
) -> None:
    """Resolution is textual, so nothing outside is even stat-ed as a member."""
    assert _within(tmp_path / "demo", escape) is None


def test_the_grader_never_reads_outside_the_folder_it_was_handed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every read is watched, and every path it saw is inside the folder.

    The body links a file that really does exist one directory up. A grader
    that resolved references against the filesystem rather than against the
    folder would open it and report the reference as fine.
    """
    (tmp_path / "outside.md").write_text("secret\n", encoding="utf-8")
    skill = _write_skill(
        tmp_path,
        body="# demo\n\nSee [up there](../outside.md) for details.\n",
    )

    seen: List[Path] = []
    original = grade_module._read_text

    def spy(path: Path):
        seen.append(Path(path))
        return original(path)

    monkeypatch.setattr(grade_module, "_read_text", spy, raising=True)
    graded = _grade(skill)

    assert seen, "the grader read nothing at all, so this test proved nothing"
    for path in seen:
        resolved = path.resolve()
        assert resolved == skill.resolve() or skill.resolve() in resolved.parents, (
            f"the grader read {resolved}, which is outside {skill.resolve()}"
        )
    assert _note(graded, "references.resolve").passed is False


def test_a_sibling_folder_is_never_counted_as_a_bundled_file(
    tmp_path: Path,
) -> None:
    """The bundling rule walks the folder, not the tree it happens to sit in."""
    (tmp_path / "neighbour").mkdir()
    (tmp_path / "neighbour" / "notes.md").write_text("x\n", encoding="utf-8")
    assert _note(_grade(_write_skill(tmp_path)), "bundled.referenced").passed


# --------------------------------------------------------------------------
# the wire block and the job summary
# --------------------------------------------------------------------------

def test_the_index_block_carries_only_failures_and_is_json(tmp_path: Path) -> None:
    """A passing note repeats what the letter already says, so it never ships."""
    skill = _write_skill(
        tmp_path,
        front={"name": "demo", "description": "Generates a readme."},
        files={"references/orphan.md": "x\n"},
    )
    block = grade_folder(skill)
    assert json.loads(json.dumps(block)) == block
    assert block["grade"] == "C"
    assert block["checked"] == len(_grade(skill).notes)
    failed = {entry["rule"] for entry in block["failed"]}
    assert failed == {"description.trigger", "bundled.referenced"}
    assert set(block["not_graded"]) == {"compatibility.length", "metadata.shape"}


def test_the_index_block_caps_a_detail(tmp_path: Path) -> None:
    """A grader that writes an essay bloats a file everybody downloads."""
    files = {f"references/f{i}.md": "x\n" for i in range(40)}
    block = grade_folder(_write_skill(tmp_path, files=files))
    for entry in block["failed"]:
        assert len(entry["detail"]) <= grade_module.MAX_DETAIL_CHARS


def test_the_summary_table_names_every_version_and_its_failures() -> None:
    """One row per version, and the failures spelled out by rule id."""
    document = {
        "items": [{
            "id": "adoom666/demo",
            "versions": [
                {"v": "1.0.0", "grade": {
                    "grade": "B", "checked": 12,
                    "failed": [{"rule": "description.trigger",
                                "level": "recommended", "detail": "x"}],
                    "not_graded": [],
                }},
                {"v": "1.1.0", "grade": {
                    "grade": "A", "checked": 12, "failed": [], "not_graded": [],
                }},
            ],
        }],
    }
    table = summary_table(document)
    assert table.startswith("## quality grades")
    assert "adoom666/demo | 1.0.0 | B | description.trigger" in table
    assert "adoom666/demo | 1.1.0 | A | nothing" in table
    assert "Advisory" in table, "the table must say the grade blocks nothing"


def test_the_summary_table_says_so_when_a_version_carries_no_grade() -> None:
    """A table that quietly omits a row reads as one where everything passed."""
    document = {"items": [{"id": "a/b", "versions": [{"v": "1.0.0"}]}]}
    assert "not graded" in summary_table({**document})


def test_the_summary_table_says_so_when_nothing_was_published() -> None:
    """An empty table and a table nobody built must not look the same."""
    assert "published no versions" in summary_table({"items": []})
