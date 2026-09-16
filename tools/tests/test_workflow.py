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
