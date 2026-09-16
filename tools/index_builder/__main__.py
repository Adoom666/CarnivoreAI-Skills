"""The four commands the workflow runs, and what each one refuses.

Run as ``python -m index_builder <command>`` from the ``tools`` directory.

  assemble  read the repository, prove every release, decide the serial and
            write an UNSIGNED index. Refuses on anything it cannot prove.
  gate      refuse a diff that edits a skill without releasing it.
  review    fill in the review block for every version, preferring a
            review already COMMITTED under reviews/ for the same bytes, then
            one the live index already published, and calling the model only
            for a version that has neither. With --handle, --name and
            --version it instead reviews ONE version and commits the artifact.
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
from typing import Dict, List, Optional, Sequence, Tuple

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
from .releases import (
    RELEASES_DIR,
    SKILLS_DIR,
    ReleaseRefused,
    find_release_files,
    verify_release,
)
from .review import (
    ReviewSettings,
    api_key_from_secret,
    collect_text,
    existing_review,
    review_one,
)
from .review_store import Review, committed_review, write_review
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


def _write_job_summary(rows: Sequence[Tuple[str, str, str]]) -> None:
    """Record which source answered for each version, where a human reads it.

    Description: appends a markdown table to the job summary, so the build
      page says whether a model actually ran and for which versions. A step
      log is collapsed by default and scrolls away; the summary survives.
      Does nothing at all when GITHUB_STEP_SUMMARY is unset, which is every
      local run and every test.
    Inputs: rows (sequence of (item id, version, source)).
    Output: None.
    Example: _write_job_summary([("adoom666/sme", "1.0.0", "committed")])
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        "### security review",
        "",
        "| skill | version | review came from |",
        "|---|---|---|",
    ]
    for item_id, version, source in rows:
        lines.append(f"| {item_id} | {version} | {source} |")
    if not rows:
        lines.append("| none | | this build listed no versions |")
    lines.extend([
        "",
        "`committed` is a review already in the repository under `reviews/`, "
        "`live index` is one this catalog already published for the same "
        "bytes, and `model` means a model call was made for it on this run.",
        "",
    ])
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        # reporting, never a gate. a build must not fail because a log file
        # could not be appended to.
        print(f"::warning::could not write the job summary: {exc}")


def _review_settings(root: Path) -> ReviewSettings:
    """Read the model settings from catalog.yml and the key from the environment.

    Description: says loudly when there is no usable key, because the
      consequence, every unreviewed version recorded unavailable, is one
      somebody should be able to explain from the log alone.
    Inputs: root (Path) - the repository root, holding catalog.yml.
    Output: ReviewSettings; ``api_key`` is None when no usable key was set.
    Example: _review_settings(Path(".")).model -> "google/gemini-2.5-flash-lite"

    THE KEY IS NEVER LOGGED. It is read here, handed to one Authorization
    header, and nothing else in this process sees it.
    """
    config = load_config(root)
    raw_secret = os.environ.get(REVIEW_SECRET_ENV, "")
    api_key = api_key_from_secret(raw_secret) if raw_secret else None
    if api_key is None:
        _notice(
            f"no usable OpenRouter key in {REVIEW_SECRET_ENV}, so no model "
            f"call can be made and every version with neither a committed "
            f"nor a published review is recorded unavailable"
        )
    return ReviewSettings(
        api_key=api_key, model=config.review_model, max_chars=config.review_max_chars,
    )


def cmd_review(args: argparse.Namespace) -> int:
    """Write reviews, either for a whole index or for one version.

    :param args: the parsed command line.
    :returns: the process exit code.

    TWO MODES, AND THEY ARE EXCLUSIVE. With ``--index`` and ``--out`` this
    fills in every version's review block in an assembled index, which is
    what the build job runs. With ``--handle``, ``--name`` and ``--version``
    it reviews ONE version and commits the artifact under ``reviews/``.
    Naming neither set, or half of one, is refused rather than guessed at:
    the two do different things to different files.
    """
    single = bool(args.handle or args.name or args.version)
    if single:
        if not (args.handle and args.name and args.version):
            print(
                "::error::--handle, --name and --version go together; name "
                "all three to review one version",
                file=sys.stderr,
            )
            return 1
        if args.index or args.out:
            print(
                "::error::--index and --out fill in a whole assembled index; "
                "--handle, --name and --version review one version and commit "
                "it. Name one set or the other, not both",
                file=sys.stderr,
            )
            return 1
        return _review_one_version(args)
    if not (args.index and args.out):
        print(
            "::error::review needs either --index and --out, to fill in an "
            "assembled index, or --handle, --name and --version, to review "
            "one version and commit it",
            file=sys.stderr,
        )
        return 1
    return _review_index(args)


def _review_index(args: argparse.Namespace) -> int:
    """Fill in every version's review block, honestly, cheapest source first.

    :param args: the parsed command line.
    :returns: 0 always, because an unobtainable review is a recorded state
        and not a build failure.

    THREE SOURCES, IN THIS ORDER, AND THE ORDER IS THE WHOLE POINT.

    1. A review COMMITTED under ``reviews/`` for this exact version whose
       recorded digest IS this version's digest. Written by an approval, or
       by this command's single version mode.
    2. A review the LIVE INDEX already published for the same digest. This
       is the behaviour that existed before committed reviews and it is
       kept, so an index rebuilt against a repository with no committed
       artifacts still costs nothing.
    3. A model call.

    NOTHING BECOMES UNREVIEWED. Rung 3 is untouched: a version with neither
    a committed nor a published review is reviewed at build time exactly as
    it always was. The first two rungs exist to stop RE-reviewing bytes
    somebody already paid to review, never to stop reviewing.

    A DIGEST MISMATCH FALLS THROUGH, IT DOES NOT SUBSTITUTE. A committed
    review of different bytes is not a review of these bytes, so it is
    ignored, said so in the log, and the version is reviewed properly.
    """
    root = Path(args.repo_root).resolve()
    document = json.loads(Path(args.index).read_text(encoding="utf-8"))
    settings = _review_settings(root)

    live: Optional[Dict[str, object]] = None
    if args.live_index and Path(args.live_index).is_file():
        live = json.loads(Path(args.live_index).read_text(encoding="utf-8"))

    now = _now()
    counts = {"committed": 0, "live": 0, "model": 0, "unavailable": 0}
    rows: List[Tuple[str, str, str]] = []

    for item in document.get("items", []):
        item_id = item.get("id", "")
        handle = str(item.get("publisher") or "")
        name = str(item.get("name") or "")
        skill_path = f"{SKILLS_DIR}/{handle}/{name}"
        for version in item.get("versions", []):
            digest = version.get("digest", "")
            label = str(version.get("v") or "")

            saved = committed_review(root, handle, name, label, digest)
            if saved is not None:
                version["review"] = saved
                counts["committed"] += 1
                rows.append((item_id, label, "committed"))
                continue

            carried = existing_review(live, item_id, digest)
            if carried is not None:
                version["review"] = carried
                counts["live"] += 1
                rows.append((item_id, label, "live index"))
                continue

            commit = version.get("src", {}).get("commit", "")
            members = _walk_members(root, commit, skill_path)
            if not members:
                _notice(
                    f"{item_id} {label}: the tree at {commit} could not be "
                    f"listed, so there is nothing to review"
                )
                version["review"] = {"status": "unavailable"}
                counts["unavailable"] += 1
                rows.append((item_id, label, "unavailable"))
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
                counts["model"] += 1
                rows.append((item_id, label, "model"))
            else:
                counts["unavailable"] += 1
                rows.append((item_id, label, "unavailable"))

    write_index(document, Path(args.out))
    print(
        f"reviews: {counts['committed']} from committed artifacts, "
        f"{counts['live']} reused from the live index, "
        f"{counts['model']} written by a model call now, "
        f"{counts['unavailable']} unavailable"
    )
    _write_job_summary(rows)
    return 0


def _review_one_version(args: argparse.Namespace) -> int:
    """Review ONE version and commit the artifact under ``reviews/``.

    :param args: the parsed command line, carrying handle, name and version.
    :returns: 0 when a review was written, 1 when none was.

    THIS IS THE EXACT CALL THE APPROVAL ENDPOINT WILL MAKE. Adam's ruling of
    2026-09-16 is that approving a submitted skill is what triggers the AI
    work: the approve step runs the scan ONCE against the bytes it is about
    to publish and commits the result beside the release. That endpoint is
    not built yet, so this command is also the operation a maintainer runs
    by hand to backfill a version the build would otherwise review again.

    THE DIGEST COMES FROM THE VERIFIED RELEASE, NEVER FROM AN ARGUMENT. The
    release statement is verified first, with the same code the build uses,
    and the review is bound to the digest that verification produced. So a
    review can never be committed for bytes no publisher signed, and a
    version that does not verify refuses here rather than being mislabelled.

    NOTHING IS WRITTEN WHEN THE SCAN FAILS. An unavailable review is a
    transient failure, not a verdict. Committing one would leave a file the
    build ignores anyway and that a reader could mistake for a finding, so
    the command says why and exits 1 and the caller retries.
    """
    root = Path(args.repo_root).resolve()
    handle, name, version = args.handle, args.name, args.version
    config = load_config(root)
    publishers = load_publishers(root)

    release_file = root / RELEASES_DIR / handle / name / f"{version}.json"
    if not release_file.is_file():
        print(
            f"::error::there is no {RELEASES_DIR}/{handle}/{name}/{version}.json, "
            f"so there is no signed release whose bytes could be reviewed",
            file=sys.stderr,
        )
        return 1
    try:
        release = verify_release(
            root, release_file,
            publishers=publishers, repo_slug=_repo_slug(config.repo),
        )
    except ReleaseRefused as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    settings = _review_settings(root)
    if settings.api_key is None:
        print(
            f"::error::there is no usable OpenRouter key in "
            f"{REVIEW_SECRET_ENV}, so no review could be taken and nothing "
            f"was written",
            file=sys.stderr,
        )
        return 1

    skill_path = f"{SKILLS_DIR}/{handle}/{name}"
    members = _walk_members(root, release.commit, skill_path)
    if not members:
        print(
            f"::error::the tree at {release.commit} could not be listed, so "
            f"there is nothing to review",
            file=sys.stderr,
        )
        return 1
    body = collect_text(
        root,
        commit=release.commit,
        skill_path=skill_path,
        members=members,
        max_chars=settings.max_chars,
    )
    block = review_one(body, settings, now=_now())
    if block.get("status") != "reviewed":
        print(
            f"::error::the review of {handle}/{name} {version} could not be "
            f"obtained, so nothing was written. Run it again.",
            file=sys.stderr,
        )
        return 1

    written = write_review(
        root, handle, name, version, Review(digest=release.digest, block=block),
    )
    print(
        f"wrote {written.relative_to(root)}, bound to digest "
        f"{release.digest[:12]}, reviewed by {block.get('model')}"
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

    look = sub.add_parser(
        "review",
        help="fill in an index's review blocks, or commit one version's review",
    )
    look.add_argument("--index", default="", help="the assembled index to fill in")
    look.add_argument("--out", default="", help="where to write the filled in index")
    look.add_argument("--live-index", default="")
    look.add_argument(
        "--handle", default="",
        help="review one version and commit it: the publisher handle",
    )
    look.add_argument(
        "--name", default="",
        help="review one version and commit it: the skill name",
    )
    look.add_argument(
        "--version", default="",
        help="review one version and commit it: the version",
    )
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
