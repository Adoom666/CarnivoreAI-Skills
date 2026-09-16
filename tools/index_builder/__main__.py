"""The four commands the workflow runs, and what each one refuses.

Run as ``python -m index_builder <command>`` from the ``tools`` directory.

  assemble  read the repository, prove every release, decide the serial and
            write an UNSIGNED index. Refuses on anything it cannot prove.
  gate      refuse a diff that edits a skill without releasing it.
  review    fill in the review block for every version, reusing what the
            live index already published for the same bytes.
  sign      sign the index with the key from Secrets Manager, or SKIP.
  marketplace  write, or prove fresh, the .claude-plugin/marketplace.json the
            `claude plugin marketplace add` command reads.

SECRETS ARRIVE THROUGH THE ENVIRONMENT, NEVER THROUGH AN ARGUMENT. A command
line is visible in the process table and lands in a job log the moment
anything echoes it; an environment variable does neither. The two commands
that need one read it from a named variable and say, when it is missing,
which variable was empty.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .assemble import assemble, write_index
from .config import load_config
from .gate import changed_paths, gate_report
from .marketplace import (
    MARKETPLACE_PATH,
    REGENERATE_COMMAND,
    MarketplaceRefused,
    build_marketplace,
    staleness,
    write_marketplace,
)
from .publishers import load_index_key, load_publishers
from .releases import ReleaseRefused, find_release_files, verify_release
from .review import (
    ReviewSettings,
    api_key_from_secret,
    collect_text,
    existing_review,
    review_one,
)
from .serial import SerialRefused, decide_serial, decision_lines
from .sign import SigningFailed, SigningSkipped, sign_index

#: The environment variable carrying the OpenRouter secret's raw value.
REVIEW_SECRET_ENV = "OPENROUTER_SECRET_VALUE"

#: The environment variable carrying the index signing secret's raw value.
SIGNING_SECRET_ENV = "INDEX_SIGNING_SECRET_VALUE"


def _notice(message: str) -> None:
    """Print a GitHub Actions notice that survives a collapsed job log.

    :param message: one line, no newlines.
    :returns: None.
    """
    print(f"::notice::{message}")


def _now() -> str:
    """The current instant, as the index spells one.

    :returns: ``YYYY-MM-DDTHH:MM:SSZ`` in UTC.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _repo_slug(config_repo: str) -> str:
    """The ``owner/repo`` the release statements are signed against.

    :param config_repo: what catalog.yml declares.
    :returns: the slug.

    catalog.yml is the authority rather than ``GITHUB_REPOSITORY``, because
    the slug is part of every signed statement: reading it from the
    environment would mean a fork's build produced statements that verify
    for a repository nobody published.
    """
    return config_repo


def cmd_assemble(args: argparse.Namespace) -> int:
    """Prove the repository and write an unsigned index.

    :param args: the parsed command line.
    :returns: the process exit code, 0 on success.
    """
    root = Path(args.repo_root).resolve()
    config = load_config(root)
    publishers = load_publishers(root)
    index_key = load_index_key(root)
    slug = _repo_slug(config.repo)

    try:
        decision = decide_serial(
            catalog_url=args.catalog_url or "",
            index_key=index_key,
            min_serial=config.min_serial,
        )
    except SerialRefused as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    for line in decision_lines(decision):
        print(line)

    verified = []
    for path in find_release_files(root):
        try:
            verified.append(
                verify_release(root, path, publishers=publishers, repo_slug=slug)
            )
        except ReleaseRefused as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1

    try:
        built = assemble(
            root,
            publishers=publishers,
            releases=verified,
            repo_slug=slug,
            serial=decision.serial,
            generated_at=args.generated_at,
        )
    except ReleaseRefused as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    write_index(built.document, Path(args.out))
    print(
        f"assembled {built.item_count} items, {built.version_count} versions, "
        f"serial {decision.serial}, into {args.out}"
    )
    for handle in built.untrusted_handles:
        _notice(
            f"publisher {handle} has no active key, so none of its releases "
            f"could be verified and none are listed"
        )
    if decision.live_document is not None and args.live_out:
        Path(args.live_out).write_text(
            json.dumps(decision.live_document), encoding="utf-8",
        )
        print(f"wrote the verified live index to {args.live_out} for review reuse")
    return 0


def _verified_items(root: Path) -> List[Dict[str, object]]:
    """Prove the repository and return the items a build would publish.

    Description: runs the same verification path ``assemble`` runs, with
      the serial left out because the marketplace file does not carry
      one. Every item it returns therefore survived a release statement
      check; an untrusted or unverifiable release never reaches the list.
    Inputs: root (Path) - the repository root.
    Output: the ``items`` list of the index this repository would publish.
    Raises: ReleaseRefused when any release cannot be proven.
    Example: _verified_items(Path(".")) -> [{"id": "adoom666/sme", ...}]
    """
    config = load_config(root)
    publishers = load_publishers(root)
    slug = _repo_slug(config.repo)
    verified = [
        verify_release(root, path, publishers=publishers, repo_slug=slug)
        for path in find_release_files(root)
    ]
    built = assemble(
        root,
        publishers=publishers,
        releases=verified,
        repo_slug=slug,
        serial=0,
        generated_at="1970-01-01T00:00:00Z",
    )
    items = built.document["items"]
    assert isinstance(items, list)
    return items


def cmd_marketplace(args: argparse.Namespace) -> int:
    """Write the marketplace file, or prove the committed one is fresh.

    :param args: the parsed command line.
    :returns: 0 when written or already fresh, 1 when stale or refused.

    THE BUILD JOB CANNOT COMMIT THIS FILE ITSELF. It has read only access
    to the repository, and a job that could push to the default branch
    would be a way around the review every other published byte goes
    through. So the check mode is what runs in CI: it says the committed
    file no longer matches, and prints the one command that fixes it.
    """
    root = Path(args.repo_root).resolve()
    config = load_config(root)
    publishers = load_publishers(root)
    try:
        items = _verified_items(root)
        document = build_marketplace(
            items, repo_slug=_repo_slug(config.repo), publishers=publishers,
        )
    except (ReleaseRefused, MarketplaceRefused) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    plugins = document["plugins"]
    assert isinstance(plugins, list)
    if args.write:
        target = Path(args.out) if args.out else root / MARKETPLACE_PATH
        payload = write_marketplace(document, target)
        print(
            f"wrote {len(plugins)} plugins, {len(payload)} bytes, to "
            f"{target}"
        )
        return 0

    named = ", ".join(str(entry["name"]) for entry in plugins)
    print(f"the build publishes {len(plugins)} plugins: {named or 'none'}")
    reason = staleness(root, document)
    if reason is None:
        print(f"{MARKETPLACE_PATH} is exactly what this build would write")
        return 0
    print(f"::error::{reason}. Regenerate it with: {REGENERATE_COMMAND}",
          file=sys.stderr)
    return 1


def cmd_gate(args: argparse.Namespace) -> int:
    """Refuse a diff that edits a skill without releasing it.

    :param args: the parsed command line.
    :returns: 0 when the diff may merge, 1 when it may not.
    """
    root = Path(args.repo_root).resolve()
    try:
        changed = changed_paths(root, args.base, args.head)
    except RuntimeError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    ok, lines = gate_report(changed)
    for line in lines:
        print(line)
    if not ok:
        print("::error::a skill folder changed with no matching release", file=sys.stderr)
    return 0 if ok else 1


def cmd_review(args: argparse.Namespace) -> int:
    """Fill in every version's review block, honestly.

    :param args: the parsed command line.
    :returns: 0 always, because an unobtainable review is a recorded state
        and not a build failure.
    """
    root = Path(args.repo_root).resolve()
    config = load_config(root)
    document = json.loads(Path(args.index).read_text(encoding="utf-8"))

    raw_secret = os.environ.get(REVIEW_SECRET_ENV, "")
    api_key = api_key_from_secret(raw_secret) if raw_secret else None
    if api_key is None:
        _notice(
            f"no usable OpenRouter key in {REVIEW_SECRET_ENV}, so every "
            f"version is recorded with review status unavailable"
        )

    live: Optional[Dict[str, object]] = None
    if args.live_index and Path(args.live_index).is_file():
        live = json.loads(Path(args.live_index).read_text(encoding="utf-8"))

    settings = ReviewSettings(
        api_key=api_key, model=config.review_model, max_chars=config.review_max_chars,
    )
    now = _now()
    reused = written = unavailable = 0

    for item in document.get("items", []):
        item_id = item.get("id", "")
        skill_path = f"skills/{item.get('publisher')}/{item.get('name')}"
        for version in item.get("versions", []):
            digest = version.get("digest", "")
            carried = existing_review(live, item_id, digest)
            if carried is not None:
                version["review"] = carried
                reused += 1
                continue
            commit = version.get("src", {}).get("commit", "")
            members = _walk_members(root, commit, skill_path)
            if not members:
                _notice(
                    f"{item_id} {version.get('v')}: the tree at {commit} could "
                    f"not be listed, so there is nothing to review"
                )
                version["review"] = {"status": "unavailable"}
                unavailable += 1
                continue
            body = collect_text(
                root,
                commit=commit,
                skill_path=skill_path,
                members=members,
                max_chars=settings.max_chars,
            )
            block = review_one(body, settings, now=now)
            version["review"] = block
            if block["status"] == "reviewed":
                written += 1
            else:
                unavailable += 1

    write_index(document, Path(args.out))
    print(
        f"reviews: {reused} reused from the live index, {written} written, "
        f"{unavailable} unavailable"
    )
    return 0


def _walk_members(root: Path, commit: str, skill_path: str) -> List[tuple]:
    """List a skill folder's members at one commit, with their modes.

    :param root: the repository.
    :param commit: the commit the version names.
    :param skill_path: the folder, relative to the root.
    :returns: (relpath, mode) pairs, empty when the tree cannot be read.

    Read straight out of the tree, so the mode is the one git recorded,
    which is the same bit the digest was taken over.
    """
    result = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-r", "-z", commit, "--", skill_path],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return []
    members: List[tuple] = []
    for record in result.stdout.split("\0"):
        if not record.strip():
            continue
        meta, _, path = record.partition("\t")
        fields = meta.split()
        if len(fields) < 3 or fields[1] != "blob":
            continue
        # a symlink is a blob too, at mode 120000, and the digest does not
        # cover one. showing a reviewer a file the digest excludes would be
        # reviewing bytes nobody signed.
        if fields[0] not in ("100644", "100755"):
            continue
        members.append((path[len(skill_path) + 1:], fields[0]))
    return members


def cmd_sign(args: argparse.Namespace) -> int:
    """Sign the index, or skip loudly when there is no key.

    :param args: the parsed command line.
    :returns: 0 on a signature or a deliberate skip, 1 on a real failure.

    A skip writes ``signed=false`` to the step output so the deploy job can
    stand down without anybody reading a red build as a broken catalog.
    """
    root = Path(args.repo_root).resolve()
    index_path = Path(args.index)
    index_key = load_index_key(root)
    document = json.loads(index_path.read_text(encoding="utf-8"))
    raw_secret = os.environ.get(SIGNING_SECRET_ENV, "")

    def emit(signed: bool) -> None:
        """Tell the workflow whether anything was actually signed.

        :param signed: True only when a real signature was produced.

        The deploy job gates on this. It is written even when the answer
        is False, because a step output that is absent and one that says
        false must never be the same thing to the job reading it: a
        missing output would leave the gate evaluating an empty string.
        """
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as handle:
                handle.write(f"signed={'true' if signed else 'false'}\n")

    if not raw_secret:
        _notice(
            f"{SIGNING_SECRET_ENV} is empty, so the index was assembled but "
            f"not signed and will not be deployed. Create the signing secret "
            f"in Secrets Manager to publish."
        )
        emit(False)
        return 0
    try:
        signature = sign_index(
            index_path,
            secret_value=raw_secret,
            serial=int(document["serial"]),
            generated_at=str(document["generated_at"]),
            index_key=index_key,
        )
    except SigningSkipped as exc:
        _notice(f"not signed: {exc}. The index was assembled but is not deployed.")
        emit(False)
        return 0
    except SigningFailed as exc:
        print(f"::error::{exc}", file=sys.stderr)
        emit(False)
        return 1
    print(f"signed {index_path.name}, {len(signature.splitlines())} line signature")
    emit(True)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Parse the command line and run one command.

    :param argv: the arguments, for tests; defaults to the real ones.
    :returns: the process exit code.

    Example: main(["assemble", "--repo-root", ".", "--out", "index.json"])
    """
    parser = argparse.ArgumentParser(prog="index_builder", description=__doc__)
    parser.add_argument("--repo-root", default=".", help="the repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("assemble", help="prove the repository, write an unsigned index")
    build.add_argument("--out", required=True)
    build.add_argument("--catalog-url", default="")
    build.add_argument("--live-out", default="")
    build.add_argument("--generated-at", default=None)
    build.set_defaults(handler=cmd_assemble)

    check = sub.add_parser("gate", help="refuse a skill change with no release")
    check.add_argument("--base", required=True)
    check.add_argument("--head", default="HEAD")
    check.set_defaults(handler=cmd_gate)

    look = sub.add_parser("review", help="write the review block for every version")
    look.add_argument("--index", required=True)
    look.add_argument("--out", required=True)
    look.add_argument("--live-index", default="")
    look.set_defaults(handler=cmd_review)

    shelf = sub.add_parser(
        "marketplace",
        help="write, or prove fresh, .claude-plugin/marketplace.json",
    )
    shelf.add_argument(
        "--write", action="store_true",
        help="write the file; without this the command only checks it",
    )
    shelf.add_argument(
        "--out", default="",
        help="write somewhere other than the repository root, for tests",
    )
    shelf.set_defaults(handler=cmd_marketplace)

    stamp = sub.add_parser("sign", help="sign the index, or skip when there is no key")
    stamp.add_argument("--index", required=True)
    stamp.set_defaults(handler=cmd_sign)

    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
