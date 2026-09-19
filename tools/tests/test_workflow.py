"""The workflow file itself, checked the way a reviewer would check it.

A build job that signs things is part of the product. These assertions are
the ones a supply chain review asks for, written down so nobody has to
remember them during a hurried change:

- every ``uses:`` is a 40 hex commit sha, with the version in a comment. a
  tag is a mutable pointer and trusting one trusts whoever can move it.
- ``pull_request_target`` appears nowhere. it runs the base branch's workflow
  with a real token against a fork's code, which is the standard way a public
  repository hands its secrets to a stranger.
- the top level permissions are the two this needs and no more.
- there is a concurrency group, because two runs racing would read the same
  live serial and both publish it.
- no job that can run from a pull request touches a cloud role.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

from tests.conftest import REPO_ROOT

WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-index.yml"

#: A pinned action: owner/repo@<40 hex>.
PINNED = re.compile(r"^[\w.-]+/[\w.-]+(?:/[\w.-]+)*@[0-9a-f]{40}$")


def _document() -> dict:
    """Parse the workflow, failing loudly when it is missing."""
    assert WORKFLOW.is_file(), f"{WORKFLOW} is missing"
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(document: dict) -> dict:
    """The ``on:`` block, whichever way yaml decided to spell the key.

    PyYAML reads a bare ``on`` as the boolean True, which is the single most
    common reason a workflow assertion silently examines nothing.
    """
    return document.get("on", document.get(True))


def test_the_workflow_parses() -> None:
    """It is valid YAML and carries the jobs the pipeline needs."""
    document = _document()
    assert set(document["jobs"]) == {"inputs", "verify", "review", "sign", "deploy"}


def test_every_action_is_pinned_to_a_sha() -> None:
    """No tag, no branch, no floating major. A sha and a version comment."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    uses = [line for line in lines if re.search(r"^\s*uses:\s", line)]
    assert uses, "the workflow uses no actions at all, so this test proved nothing"
    for line in uses:
        body = line.split("uses:", 1)[1].strip()
        reference, _, comment = body.partition("#")
        assert PINNED.match(reference.strip()), (
            f"not pinned to a 40 hex sha: {line.strip()}"
        )
        assert comment.strip(), (
            f"pinned with no version comment, so nobody can tell what it is: "
            f"{line.strip()}"
        )


def test_pull_request_target_is_never_used() -> None:
    """The trigger that hands a fork the repository's secrets is absent.

    Checked two ways. The parsed triggers are the fact; the line scan
    catches a spelling yaml folded into something else. Comments are
    excluded on purpose: the workflow explains in prose why this trigger is
    never used, and a test that failed on its own warning would be deleted.
    """
    triggers = _triggers(_document())
    assert "pull_request_target" not in triggers

    offending = [
        line for line in WORKFLOW.read_text(encoding="utf-8").splitlines()
        if "pull_request_target" in line and not line.lstrip().startswith("#")
    ]
    assert not offending, f"pull_request_target appears in: {offending}"


def test_the_top_level_permissions_are_the_two_it_needs() -> None:
    """Read the code, mint an oidc token. Nothing writes to the repository."""
    document = _document()
    assert document["permissions"] == {"contents": "read", "id-token": "write"}


def test_there_is_a_concurrency_group() -> None:
    """Two runs must never race on the serial, and a queued one is not cancelled."""
    document = _document()
    assert document["concurrency"]["group"]
    assert document["concurrency"]["cancel-in-progress"] is False


def test_the_cloud_jobs_never_run_from_a_pull_request() -> None:
    """A fork's pull request reaches the verify job and nothing else."""
    document = _document()
    for name in ("review", "sign", "deploy"):
        condition = document["jobs"][name]["if"]
        assert "github.event_name != 'pull_request'" in condition, (
            f"the {name} job does not exclude pull requests"
        )
        assert "vars.AWS_ROLE_ARN != ''" in condition, (
            f"the {name} job does not stand down when there is no role to assume"
        )


def test_the_verify_job_takes_the_whole_history() -> None:
    """A shallow clone refuses every release for a reason that reads like a bug."""
    document = _document()
    checkout = next(
        step for step in document["jobs"]["verify"]["steps"]
        if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["fetch-depth"] == 0


def test_only_the_sign_job_names_the_signing_secret() -> None:
    """The index key is read in one job and nowhere else."""
    document = _document()
    for name, job in document["jobs"].items():
        mentions = "carnivore/catalog/index-signing-key" in yaml.safe_dump(job)
        assert mentions == (name == "sign"), (
            f"the {name} job should not mention the index signing secret"
        )


def test_the_deploy_job_waits_for_a_real_signature() -> None:
    """Nothing is published unless the sign job said it actually signed."""
    document = _document()
    assert "needs.sign.outputs.signed == 'true'" in document["jobs"]["deploy"]["if"]


def test_the_weekly_resign_is_scheduled() -> None:
    """The re-sign bounds an undetected key compromise to a week."""
    triggers = _triggers(_document())
    assert triggers["schedule"], "there is no weekly re-sign"


#: The ownership file, beside the workflow, checked for the same reason.
CODEOWNERS = REPO_ROOT / "CODEOWNERS"

#: The generated file `claude plugin marketplace add` reads. It decides,
#: for every plugin name, which folder's bytes a user installs.
GENERATED_MARKETPLACE = ".claude-plugin"


def _codeowner_paths() -> list[str]:
    """Every path pattern CODEOWNERS assigns an owner to.

    :returns: the left hand column, comments and blank lines dropped.

    Example: _codeowner_paths() contains "tools/**"
    """
    assert CODEOWNERS.is_file(), f"{CODEOWNERS} is missing"
    out = []
    for line in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append(stripped.split()[0])
    assert out, "CODEOWNERS assigns no owner to anything, so this proved nothing"
    return out


def test_the_generated_marketplace_file_is_in_the_push_paths_filter() -> None:
    """A change to it must run this workflow, or the staleness check is mute.

    The check itself works: it regenerates the file from the releases it
    just proved and compares byte for byte, and it goes red on exactly the
    edit that matters. It simply never fired for this path on a push,
    because the filter did not name it. A commit touching only
    `.claude-plugin/marketplace.json` therefore ran no workflow at all,
    which is the one file that decides, per plugin name, whose folder a
    `claude plugin install` copies.
    """
    triggers = _triggers(_document())
    paths = triggers["push"]["paths"]
    assert any(pattern.startswith(GENERATED_MARKETPLACE) for pattern in paths), (
        f"no push path filter covers {GENERATED_MARKETPLACE}/, so a commit "
        f"that repoints a plugin name at another publisher's folder runs "
        f"nothing at all. filter is: {paths}"
    )


def test_the_generated_marketplace_file_needs_an_owner_review() -> None:
    """CODEOWNERS covers it, for the same reason the workflow filter does.

    Its own header says everything that decides what gets signed needs the
    owner on the pull request. This file decides what gets INSTALLED,
    which is the same question one layer out.
    """
    patterns = _codeowner_paths()
    assert any(pattern.startswith(GENERATED_MARKETPLACE) for pattern in patterns), (
        f"CODEOWNERS does not cover {GENERATED_MARKETPLACE}/, so a change to "
        f"the file that maps a plugin name to a folder needs no owner "
        f"review. it covers: {patterns}"
    )


def test_every_codeowned_path_also_triggers_the_build() -> None:
    """The two lists answer one question and must not drift apart.

    A path worth an owner's review is a path worth running the checks on.
    This is the test that would have caught the original gap in either
    file rather than only in the one that was noticed.
    """
    triggers = _triggers(_document())
    paths = triggers["push"]["paths"]
    for pattern in _codeowner_paths():
        stem = pattern.split("*")[0].rstrip("/")
        assert any(candidate.startswith(stem) for candidate in paths), (
            f"CODEOWNERS guards {pattern} but no push path filter covers it, "
            f"so a change there is reviewed but never checked"
        )


#: The subcommand the publish backstop runs.
CHECK_REVIEWS = "check-reviews"


def _blocked_review(digest: str, *, override: bool) -> dict:
    """A committed review that refuses a publish, with or without the waiver."""
    document = {
        "digest": digest,
        "status": "reviewed",
        "verdict": "blocked",
        "summary": "reads the user's ssh key and posts it.",
        "warnings": [{
            "kind": "credential_access",
            "detail": "SKILL.md tells the agent to read ~/.ssh/id_ed25519.",
            "file": "SKILL.md",
            "line": 6,
        }],
        "model": "test/model",
        "reviewed_at": "2026-09-19T00:00:00Z",
    }
    if override:
        document["override"] = {
            "reason": "internal fixture, published deliberately",
            "by": "adoom666",
            "at": "2026-09-19T00:00:00Z",
        }
    return document


def _backstop_step() -> dict:
    """The verify job's step that refuses a blocked version.

    :returns: the step, so a test can run the command the workflow runs
        rather than a command a test wrote to look like it.
    """
    document = _document()
    steps = [
        step for step in document["jobs"]["verify"]["steps"]
        if CHECK_REVIEWS in str(step.get("run", ""))
    ]
    assert len(steps) == 1, (
        f"the verify job runs {CHECK_REVIEWS} {len(steps)} times; it needs "
        f"exactly one backstop, in the job that runs on a pull request"
    )
    return steps[0]


def test_the_verify_job_refuses_a_blocked_review() -> None:
    """The backstop is in the job a fork's pull request actually reaches.

    The review job holds the model key and is skipped on a pull request, so
    a gate living there would never see a submitted skill. This one holds
    no credential and reads committed files, so it runs for everybody.
    """
    step = _backstop_step()
    assert step["working-directory"] == "tools"
    assert "if" not in step, (
        "the backstop is conditional, so there is a way to merge past it"
    )


def test_the_backstop_command_goes_red_on_a_blocked_review(tmp_path) -> None:
    """A GREEN CHECK MUST FIRST PROVE IT CAN GO RED.

    This runs the command out of the workflow file itself, against a
    repository carrying one blocked committed review, and requires a non
    zero exit. Then it adds the written override and requires a zero one.
    Asserting the step's presence alone would pass against a step that
    printed the verdicts and exited 0 every time, which is the exact shape
    of check this project keeps removing.
    """
    import json
    import subprocess
    import sys

    digest = "a" * 64
    index = {"items": [{
        "id": "adoom666/probe",
        "publisher": "adoom666",
        "name": "probe",
        "versions": [{"v": "1.0.0", "digest": digest}],
    }]}
    index_path = tmp_path / "index.unsigned.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    review_path = tmp_path / "reviews" / "adoom666" / "probe" / "1.0.0.json"
    review_path.parent.mkdir(parents=True)

    command = _backstop_step()["run"].replace("python ", f"{sys.executable} ")

    def run_backstop() -> subprocess.CompletedProcess:
        """Run the workflow's own command line against the crafted tree."""
        return subprocess.run(
            ["bash", "-euo", "pipefail", "-c", command],
            cwd=str(REPO_ROOT / "tools"),
            env={
                "PATH": os.environ["PATH"],
                "GITHUB_WORKSPACE": str(tmp_path),
                "PYTHONPATH": str(REPO_ROOT / "tools"),
            },
            capture_output=True, text=True, check=False,
        )

    review_path.write_text(
        json.dumps(_blocked_review(digest, override=False)), encoding="utf-8",
    )
    refused = run_backstop()
    assert refused.returncode != 0, (
        f"a blocked review did not refuse the build. stdout: {refused.stdout} "
        f"stderr: {refused.stderr}"
    )
    assert "blocked" in (refused.stdout + refused.stderr)

    review_path.write_text(
        json.dumps(_blocked_review(digest, override=True)), encoding="utf-8",
    )
    allowed = run_backstop()
    assert allowed.returncode == 0, (
        f"a written override did not let the build through. stdout: "
        f"{allowed.stdout} stderr: {allowed.stderr}"
    )
    assert "blocked" in allowed.stdout, (
        "the override hid the verdict; it must never change what the review "
        "says, only whether the build stops"
    )


def test_a_malformed_override_does_not_let_a_blocked_review_through(tmp_path) -> None:
    """Half an override is not an override, and the version stays blocked.

    A file claiming a waiver that the gate does not honour is worse than no
    file: a reader sees an approval that never happened. So a malformed
    override refuses the whole artifact, and the refusal stands.
    """
    import json
    import subprocess
    import sys

    digest = "b" * 64
    index_path = tmp_path / "index.unsigned.json"
    index_path.write_text(json.dumps({"items": [{
        "id": "adoom666/probe",
        "publisher": "adoom666",
        "name": "probe",
        "versions": [{"v": "1.0.0", "digest": digest}],
    }]}), encoding="utf-8")
    review = _blocked_review(digest, override=True)
    review["override"].pop("reason")
    review_path = tmp_path / "reviews" / "adoom666" / "probe" / "1.0.0.json"
    review_path.parent.mkdir(parents=True)
    review_path.write_text(json.dumps(review), encoding="utf-8")

    command = _backstop_step()["run"].replace("python ", f"{sys.executable} ")
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", command],
        cwd=str(REPO_ROOT / "tools"),
        env={
            "PATH": os.environ["PATH"],
            "GITHUB_WORKSPACE": str(tmp_path),
            "PYTHONPATH": str(REPO_ROOT / "tools"),
        },
        capture_output=True, text=True, check=False,
    )
    # a committed review that exists and cannot be read refuses the build.
    # treating it as absent would make corrupting the artifact the way past
    # this check, which is a cheaper attack than forging an override.
    assert result.returncode != 0, (
        f"a broken override let the build through. stdout: {result.stdout} "
        f"stderr: {result.stderr}"
    )
    assert "unreadable" in result.stdout, result.stdout
