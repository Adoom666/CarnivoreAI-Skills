"""The pull request check: you may not change a skill without releasing it.

THE HOLE THIS CLOSES. Every version in the index names a commit, and the
build re-digests that commit's tree, so nothing unsigned is ever published.
But a pull request could still edit ``skills/adoom666/work/SKILL.md`` and
change nothing else: the build would stay green, because the index would go
on pointing at the last RELEASED commit, and the repository and the catalog
would quietly disagree about what that skill says. Somebody reading the
folder on GitHub would be reading text nobody can install.

SO A DIFF THAT TOUCHES A SKILL FOLDER MUST ALSO TOUCH THAT SKILL'S RELEASES.
The pairing is per skill, not per publisher: changing one skill does not let
you smuggle a change into another one beside it. Whether the release itself
is any good is not decided here; every release in the repository is verified
by the assemble step in the same job, and this check runs after it, so a
paired release that does not verify has already failed the build.

DELETIONS PAIR THE SAME WAY. Removing a skill folder is a change to it, and
a catalog still offering a skill whose folder is gone would hand out install
failures. The message says so rather than leaving the contributor guessing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import List, Sequence, Set, Tuple

from .releases import RELEASES_DIR, SKILLS_DIR


def changed_paths(repo_root: Path, base: str, head: str) -> List[str]:
    """List the repository relative paths a range of commits touched.

    Description: uses the three dot form, which asks what the head added
      SINCE the branches diverged rather than what differs between two
      tips. The two answers differ whenever the base has moved on, and the
      two dot answer would blame a contributor for other people's commits.
    Inputs: repo_root (Path). base (str), head (str) - two commit-ish refs.
    Output: the paths, sorted.
    Raises: RuntimeError when git fails, carrying its stderr, so a range
      that cannot be computed is never read as an empty diff.
    Example: changed_paths(root, "origin/main", "HEAD")
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", f"{base}...{head}"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git diff {base}...{head} failed: "
            f"{result.stderr.strip() or 'no stderr'}"
        )
    return sorted(line for line in result.stdout.splitlines() if line.strip())


def _skill_of(path: str, folder: str) -> Tuple[str, str] | None:
    """Read the (handle, name) a path belongs to, or None.

    :param path: a repository relative path.
    :param folder: ``skills`` or ``releases``.
    :returns: the pair, or None when the path is not deep enough to name a
        skill.

    Example: _skill_of("skills/a/b/SKILL.md", "skills") -> ("a", "b")
    """
    parts = path.split("/")
    if len(parts) < 3 or parts[0] != folder:
        return None
    return parts[1], parts[2]


def unreleased_changes(changed: Sequence[str]) -> List[Tuple[str, str]]:
    """Find skills the diff changed without touching their releases.

    Description: builds the set of skills the diff touched under
      ``skills/`` and the set it touched under ``releases/``, and returns
      the difference, sorted. A change to a publisher declaration or to the
      build tooling touches neither set and is not this check's business.
    Inputs: changed (sequence of str) - repository relative paths.
    Output: the (handle, name) pairs that need a release and have none, in
      a stable order.
    Example: unreleased_changes(["skills/a/b/SKILL.md"]) -> [("a", "b")]
    """
    touched_skills: Set[Tuple[str, str]] = set()
    touched_releases: Set[Tuple[str, str]] = set()
    for path in changed:
        skill = _skill_of(path, SKILLS_DIR)
        if skill is not None:
            touched_skills.add(skill)
            continue
        release = _skill_of(path, RELEASES_DIR)
        if release is not None:
            touched_releases.add(release)
    return sorted(touched_skills - touched_releases)


def gate_report(changed: Sequence[str]) -> Tuple[bool, List[str]]:
    """Decide whether this diff may merge, and say why in full.

    Description: returns the verdict and the lines to print. A passing
      report still prints what it LOOKED AT, because a check that passes
      silently is indistinguishable from a check that examined nothing,
      and that is the failure shape this repository has been bitten by
      most often.
    Inputs: changed (sequence of str) - the diff's paths.
    Output: (ok, lines).
    Example: gate_report([])[0] -> True
    """
    offenders = unreleased_changes(changed)
    skills_touched = sorted({
        pair for pair in
        (_skill_of(path, SKILLS_DIR) for path in changed) if pair is not None
    })
    lines = [
        f"paths in this diff: {len(changed)}",
        f"skill folders it touches: {len(skills_touched)}"
        + (f" ({', '.join(f'{h}/{n}' for h, n in skills_touched)})"
           if skills_touched else ""),
    ]
    if not offenders:
        lines.append("every touched skill folder also carries a release change")
        return True, lines
    for handle, name in offenders:
        lines.append(
            f"REFUSED: this diff changes {SKILLS_DIR}/{handle}/{name} but no "
            f"file under {RELEASES_DIR}/{handle}/{name}. Sign a release for "
            f"the new content with scripts/catalog-bootstrap/sign_release.py "
            f"and commit it in this pull request, or the catalog will go on "
            f"serving the version you just edited away from."
        )
    return False, lines
