"""The four commands the workflow runs, and what each one refuses.

Run as ``python -m index_builder <command>`` from the ``tools`` directory.

  assemble  read the repository, prove every release, decide the serial and
            write an UNSIGNED index. Refuses on anything it cannot prove.
  gate      refuse a diff that edits a skill without releasing it.
  review    fill in the review block for every version, preferring a
            review already COMMITTED under reviews/ for the same bytes, then
            one the live index already published, and calling the model only
            for a version that has neither. With --handle, --name and
            --version it instead reviews ONE version and commits the artifact,
            and exits non zero when that version's verdict is blocked. With
            --from-index it instead COPIES the review this catalog already
            published for the same digest into reviews/, calling no model.
  check-reviews  refuse the build unless EVERY published version carries a
            committed review bound to its exact folder digest, and that
            review is not blocked without a written override. Holds no
            credential and calls no model, so it runs on a pull request
            from anybody.
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
from .digest import digest_directory
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
    VerifiedRelease,
    find_release_files,
    verify_release,
)
from .review import (
    VERDICT_BLOCKED,
    VERDICT_CLEAN,
    ReviewSettings,
    api_key_from_secret,
    collect_staged_text,
    collect_text,
    existing_review,
    review_one,
)
from .review_store import (
    OVERRIDE_FIELD,
    OVERRIDE_KEYS,
    Review,
    ReviewArtifactInvalid,
    committed_review,
    is_overridden,
    read_review,
    review_path,
    write_review,
)
from .serial import SerialRefused, decide_serial, decision_lines
from .sign import SigningFailed, SigningSkipped, sign_index

#: The environment variable carrying the OpenRouter secret's raw value.
REVIEW_SECRET_ENV = "OPENROUTER_SECRET_VALUE"

#: The environment variable carrying the index signing secret's raw value.
SIGNING_SECRET_ENV = "INDEX_SIGNING_SECRET_VALUE"

#: The three ways a published version fails the publish gate. They are
#: named apart because the move that fixes each one is different, and a
#: refusal an operator cannot act on is a refusal that gets forced past.
REFUSE_ABSENT = "no committed review for these bytes"
REFUSE_STALE = "committed review is for a different digest"
REFUSE_BLOCKED = "blocked without override"


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


def _write_job_summary(
    rows: Sequence[Tuple[str, ...]], *,
    heading: str = "security review",
    columns: Sequence[str] = ("skill", "version", "review came from", "verdict"),
    note: str = (
        "`committed` is a review already in the repository under `reviews/`, "
        "`live index` is one this catalog already published for the same "
        "bytes, and `model` means a model call was made for it on this run. "
        "`blocked` refuses the publish unless the committed review carries a "
        "written override."
    ),
) -> None:
    """Record what happened to each version, where a human reads it.

    Description: appends a markdown table to the job summary, so the build
      page says whether a model actually ran, for which versions, and what
      it decided. A step log is collapsed by default and scrolls away; the
      summary survives. Does nothing at all when GITHUB_STEP_SUMMARY is
      unset, which is every local run and every test. ONE WRITER, two
      callers: the review step and the publish gate print different columns
      of the same shape, and a second writer would be a second format to
      keep in step.
    Inputs: rows (sequence of tuples, one cell per column). heading (str).
      columns (sequence of str). note (str) - the sentence under the table.
    Output: None.
    Example: _write_job_summary([("adoom666/sme", "1.0.0", "committed",
      "clean")])
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [
        f"### {heading}",
        "",
        "| " + " | ".join(columns) + " |",
        "|" + "---|" * len(columns),
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    if not rows:
        lines.append("| none |" + " |" * (len(columns) - 1))
    lines.extend(["", note, ""])
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    except OSError as exc:
        # reporting, never a gate. a build must not fail because a log file
        # could not be appended to.
        print(f"::warning::could not write the job summary: {exc}")


def _verdict_of(block: Dict[str, object]) -> str:
    """What one review block decided, in one word for a table.

    Description: an unavailable review has NO verdict and must never read
      as a clean one, so it prints ``none`` rather than an empty cell a
      reader would skim past.
    Inputs: block (dict) - a review block.
    Output: str - the verdict, or ``none``.
    Example: _verdict_of({"status": "reviewed", "verdict": "clean"}) -> "clean"
    """
    verdict = block.get("verdict")
    return str(verdict) if isinstance(verdict, str) and verdict else "none"


def _short(digest: str) -> str:
    """One digest, shortened for a message, with an empty one named.

    Description: a refusal quotes two digests so a reader can see at a
      glance whether they differ. An empty one prints ``unknown`` rather
      than nothing, because a blank in that sentence reads like a match.
    Inputs: digest (str) - a hex digest, possibly empty.
    Output: str.
    Example: _short("a" * 64) -> "aaaaaaaaaaaa"
    """
    return digest[:12] if digest else "unknown"


def _verified_release(
    root: Path, handle: str, name: str, version: str,
) -> Optional[VerifiedRelease]:
    """Verify one version's signed release statement, or say why not.

    Description: the digest a review is bound to comes from HERE, never
      from the folder being reviewed and never from the index being
      replaced, so a review can never be committed for bytes no publisher
      signed.
    Inputs: root (Path) - the repository root. handle (str). name (str).
      version (str).
    Output: the verified release, or None when it could not be verified,
      in which case the reason has already been printed to stderr.
    Example: _verified_release(root, "adoom666", "sme", "1.0.0")
    """
    config = load_config(root)
    publishers = load_publishers(root)
    release_file = root / RELEASES_DIR / handle / name / f"{version}.json"
    if not release_file.is_file():
        print(
            f"::error::there is no {RELEASES_DIR}/{handle}/{name}/{version}.json, "
            f"so there is no signed release whose bytes could be reviewed",
            file=sys.stderr,
        )
        return None
    try:
        return verify_release(
            root, release_file,
            publishers=publishers, repo_slug=_repo_slug(config.repo),
        )
    except ReleaseRefused as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return None


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
    single = bool(args.handle or args.name or args.version or args.staged
                  or args.from_index)
    if single:
        if not (args.handle and args.name and args.version):
            print(
                "::error::--handle, --name and --version go together; name "
                "all three to review one version. --staged needs them too, "
                "because they are where the artifact is written",
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
        if args.from_index:
            if args.staged or args.override_blocked is not None or args.require_clean:
                print(
                    "::error::--from-index copies a review that was already "
                    "taken and published; it calls no model and decides no "
                    "verdict, so --staged, --override-blocked and "
                    "--require-clean do not apply to it",
                    file=sys.stderr,
                )
                return 1
            return _review_from_index(args)
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
    rows: List[Tuple[str, ...]] = []

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
                rows.append((item_id, label, "committed", _verdict_of(saved)))
                continue

            carried = existing_review(live, item_id, digest)
            if carried is not None:
                version["review"] = carried
                counts["live"] += 1
                rows.append((item_id, label, "live index", _verdict_of(carried)))
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
                rows.append((item_id, label, "unavailable", "none"))
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
                rows.append((item_id, label, "model", _verdict_of(block)))
            else:
                counts["unavailable"] += 1
                rows.append((item_id, label, "unavailable", "none"))

    write_index(document, Path(args.out))
    print(
        f"reviews: {counts['committed']} from committed artifacts, "
        f"{counts['live']} reused from the live index, "
        f"{counts['model']} written by a model call now, "
        f"{counts['unavailable']} unavailable"
    )
    _write_job_summary(rows)
    return 0


def _override_actor(root: Path) -> str:
    """Name who is waving a blocked version through.

    Description: an override that cannot say WHO is not an override, so
      this refuses rather than writing ``unknown``. Read from the
      repository's own git identity first, because that is the name that
      will be on the commit carrying the file, then from the environment.
    Inputs: root (Path) - the catalog checkout.
    Output: str - the actor's name.
    Raises: RuntimeError when neither source names anybody.
    Example: _override_actor(Path(".")) -> "Adoom666"
    """
    result = subprocess.run(
        ["git", "-C", str(root), "config", "user.name"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    for variable in ("GITHUB_ACTOR", "USER", "LOGNAME"):
        value = os.environ.get(variable, "").strip()
        if value:
            return value
    raise RuntimeError(
        "nothing here names who is overriding: set git config user.name in "
        "the catalog checkout, or export USER"
    )


def _print_findings(block: Dict[str, object]) -> None:
    """Print a review's verdict and every finding under it.

    Description: what an operator reads INSTEAD of the publish command
      when a version is blocked. One line per finding, naming the kind,
      the file, the line when the model was sure of one, and the sentence.
    Inputs: block (dict) - a reviewed block.
    Output: None.
    Example: _print_findings({"verdict": "blocked", "warnings": [...]})
    """
    print(f"verdict: {_verdict_of(block)}")
    summary = block.get("summary")
    if isinstance(summary, str) and summary:
        print(f"summary: {summary}")
    warnings = block.get("warnings")
    if not isinstance(warnings, list) or not warnings:
        print("findings: none")
        return
    print(f"findings: {len(warnings)}")
    for entry in warnings:
        if not isinstance(entry, dict):
            continue
        where = str(entry.get("file", "?"))
        line = entry.get("line")
        if isinstance(line, int):
            where = f"{where}:{line}"
        print(f"  {entry.get('kind')}  {where}  {entry.get('detail')}")


def _review_one_version(args: argparse.Namespace) -> int:
    """Review ONE version and commit the artifact under ``reviews/``.

    :param args: the parsed command line, carrying handle, name and version.
    :returns: 0 when the version may be published, 1 when it may not.

    THIS IS THE APPROVAL GATE. Adam's ruling of 2026-09-16 is that
    approving a submitted skill is what triggers the AI work, and the
    ruling of 2026-09-19 is that the same single pass answers the
    description question and the security checklist together and returns a
    VERDICT the publish is gated on. ``fetch_approved.py`` runs this
    against the bytes it just staged and refuses to print the publish
    command when it exits non zero.

    TWO SOURCES OF BYTES, AND THE VERDICT IS THE SAME EITHER WAY. With
    ``--staged`` the bytes are a folder on disk that has not been committed
    yet, which is the approval moment; the digest is computed from that
    folder with the same code the app uses. Without it the release
    statement is verified first and the review is bound to the digest THAT
    produced, so a review can never be committed for bytes no publisher
    signed.

    A BLOCKED VERDICT EXITS NON ZERO UNLESS A HUMAN OVERRODE IT.
    ``--override-blocked`` takes the reason, requires it to be a real
    sentence, prints the findings it is waving through and writes the
    reason, the actor and the moment into the committed artifact. IT NEVER
    CHANGES THE VERDICT: the artifact still says blocked, the card still
    marks the item, and the diff carrying the override goes past CODEOWNERS
    like every other reviewed byte.

    NOTHING IS WRITTEN WHEN THE SCAN FAILS. An unavailable review is a
    transient failure, not a verdict. Committing one would leave a file the
    build ignores anyway and that a reader could mistake for a finding, so
    the command says why and exits 1 and the caller retries.
    """
    root = Path(args.repo_root).resolve()
    handle, name, version = args.handle, args.name, args.version
    reason = str(args.override_blocked or "").strip()
    if args.override_blocked is not None and not reason:
        print(
            "::error::--override-blocked needs the reason the block is being "
            "waved through; it is written into the committed review and read "
            "by whoever reviews the pull request",
            file=sys.stderr,
        )
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

    if args.staged:
        folder = Path(args.staged).expanduser().resolve()
        if not (folder / "SKILL.md").is_file():
            print(
                f"::error::{folder} holds no SKILL.md, so there is no skill "
                f"there to review",
                file=sys.stderr,
            )
            return 1
        digest, entries = digest_directory(folder)
        members = [(entry.relpath, entry.mode) for entry in entries]
        body = collect_staged_text(
            folder, members=members, max_chars=settings.max_chars,
        )
    else:
        release = _verified_release(root, handle, name, version)
        if release is None:
            return 1
        digest = release.digest
        skill_path = f"{SKILLS_DIR}/{handle}/{name}"
        members = _walk_members(root, release.commit, skill_path)
        if not members:
            print(
                f"::error::the tree at {release.commit} could not be listed, "
                f"so there is nothing to review",
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

    verdict = _verdict_of(block)
    _print_findings(block)

    if reason:
        if verdict != VERDICT_BLOCKED:
            print(
                f"::error::--override-blocked was given but the verdict is "
                f"{verdict}, not {VERDICT_BLOCKED}. There is nothing to "
                f"override and nothing was written",
                file=sys.stderr,
            )
            return 1
        try:
            actor = _override_actor(root)
        except RuntimeError as exc:
            print(f"::error::{exc}", file=sys.stderr)
            return 1
        block[OVERRIDE_FIELD] = dict(zip(OVERRIDE_KEYS, (reason, actor, _now())))
        _notice(
            f"the blocked verdict for {handle}/{name} {version} is being "
            f"overridden by {actor}: {reason}"
        )

    written = write_review(
        root, handle, name, version, Review(digest=digest, block=block),
    )
    print(
        f"wrote {written.relative_to(root)}, bound to digest "
        f"{digest[:12]}, reviewed by {block.get('model')}"
    )

    if verdict == VERDICT_BLOCKED and not is_overridden(block):
        print(
            f"::error::{handle}/{name} {version} is BLOCKED by its security "
            f"review and must not be published. Read the findings above. To "
            f"publish it anyway, run this again with "
            f"--override-blocked \"<reason>\"",
            file=sys.stderr,
        )
        return 1
    if args.require_clean and verdict != VERDICT_CLEAN:
        print(
            f"::error::{handle}/{name} {version} reviewed {verdict} and "
            f"--require-clean was asked for, so it is refused here",
            file=sys.stderr,
        )
        return 1
    return 0


def _live_digests_note(live: object, item_id: str) -> str:
    """Name what the source index does hold for an item, for a refusal.

    Description: a refusal saying only "no match" leaves the operator
      guessing between a missing item and moved bytes, which are different
      problems with different fixes.
    Inputs: live (object) - the parsed index document. item_id (str).
    Output: str - a clause to append to a sentence, or "".
    Example: _live_digests_note(doc, "adoom666/sme") -> " (it holds 1.0.0 at dfd68a92024a)"
    """
    items = live.get("items") if isinstance(live, dict) else None
    if not isinstance(items, list):
        return ""
    for item in items:
        if not isinstance(item, dict) or item.get("id") != item_id:
            continue
        versions = item.get("versions")
        if not isinstance(versions, list):
            return ""
        held = ", ".join(
            f"{entry.get('v')} at {_short(str(entry.get('digest') or ''))}"
            for entry in versions if isinstance(entry, dict)
        )
        return f" (it holds {held})" if held else ""
    return f" (it lists no item {item_id})"


def _review_from_index(args: argparse.Namespace) -> int:
    """Commit the review this catalog already published for these bytes.

    :param args: the parsed command line, carrying handle, name, version
        and the index to copy the review out of.
    :returns: 0 when the artifact was written, 1 when it was not.

    THE MIGRATION PATH, AND IT NEVER CALLS THE MODEL. Versions published
    before a committed review was required carry their review only in the
    signed index. This copies one into ``reviews/`` with its verdict, its
    findings and any override intact, so the publish gate has a committed
    artifact to read without paying for a second opinion that could differ
    from the words users have already been shown.

    THE DIGEST COMES FROM THE SIGNED RELEASE, NEVER FROM THE INDEX. The
    release statement is verified first and the review is copied only when
    the source index bound it to THAT digest, so a review of other bytes
    cannot be laundered into the reviews tree by editing what it is copied
    from. A mismatch refuses and writes nothing.

    IT APPROVES NOTHING BY ITSELF. The copied verdict is the one that was
    taken; a blocked one stays blocked and still refuses the build unless
    the override it already carries says otherwise.
    """
    root = Path(args.repo_root).resolve()
    handle, name, version = args.handle, args.name, args.version
    source = Path(args.from_index).expanduser()
    if not source.is_file():
        print(
            f"::error::{source} is not a file, so there is no published "
            f"review to copy",
            file=sys.stderr,
        )
        return 1
    release = _verified_release(root, handle, name, version)
    if release is None:
        return 1
    digest = release.digest
    try:
        live = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"::error::{source} could not be read as JSON ({exc}), so no "
            f"review was copied",
            file=sys.stderr,
        )
        return 1
    item_id = f"{handle}/{name}"
    block = existing_review(live, item_id, digest)
    if block is None:
        print(
            f"::error::{source} carries no usable review bound to digest "
            f"{_short(digest)} for {item_id} {version}"
            f"{_live_digests_note(live, item_id)}. A review of other bytes "
            f"is not a review of these bytes, so nothing was written.",
            file=sys.stderr,
        )
        return 1
    written = write_review(
        root, handle, name, version, Review(digest=digest, block=dict(block)),
    )
    print(
        f"copied the published review into {written.relative_to(root)}, "
        f"bound to digest {_short(digest)}, verdict {_verdict_of(block)}"
    )
    return 0


def cmd_check_reviews(args: argparse.Namespace) -> int:
    """Refuse a version whose exact bytes no committed review approved.

    :param args: the parsed command line, naming the assembled index.
    :returns: 0 when every published version may be published, 1 when one
        may not.

    THE PUBLISH GATE, AND IT RUNS ON PULL REQUESTS. The approval gate lives
    in the script a maintainer runs on his own machine, and a gate that
    only lives in one script is a gate a hand commit walks past. This step
    reads the COMMITTED reviews for the versions the index just assembled
    and refuses the whole build unless EVERY published version carries one
    bound to its exact folder digest. It holds no cloud credential and
    calls no model, so it runs in the verify job for anybody's pull
    request, which is the thing the review job cannot do.

    THE HOLE THIS CLOSES. Until 2026-09-19 an absent committed review and a
    committed review of other bytes both printed a row and passed. So an
    operator who edited the folder AFTER the staged review, or who never
    took one, published bytes nothing had approved: the build reviewed them
    and wrote the verdict into the index, which records a finding rather
    than acting on it.

    THREE WAYS TO FAIL, NAMED APART, because the operator's next move is
    different for each one:

    - ``no committed review for these bytes``: nothing under ``reviews/``
      for this version, or a file that exists and cannot be read. Review
      the bytes and commit the artifact.
    - ``committed review is for a different digest``: the folder changed
      after the review was taken. Review it again.
    - ``blocked without override``: the review read these exact bytes and
      refused them. Publish needs a written override, or different bytes.

    ONLY A COMMITTED REVIEW APPROVES BYTES. A review the LIVE INDEX carries
    for the same digest is good enough to SAVE A MODEL CALL, which is all
    rung 2 of the review step uses it for, and it is not good enough to
    ADMIT anything: the live index is the artifact this build replaces, so
    letting it approve bytes makes the gate's input its own output, and one
    bad build would then approve those bytes for every build after it. A
    committed artifact sits under ``reviews/``, which ``CODEOWNERS`` routes
    to the owner, so it reaches publication through a diff a human read.
    """
    root = Path(args.repo_root).resolve()
    document = json.loads(Path(args.index).read_text(encoding="utf-8"))
    rows: List[Tuple[str, ...]] = []
    refused: List[str] = []

    for item in document.get("items", []):
        item_id = str(item.get("id", ""))
        handle = str(item.get("publisher") or "")
        name = str(item.get("name") or "")
        for version in item.get("versions", []):
            label = str(version.get("v") or "")
            digest = str(version.get("digest") or "")
            found = read_review(root, handle, name, label)
            if found is None:
                # A FILE THAT EXISTS AND CANNOT BE READ IS NOT AN ABSENT
                # ONE. Both refuse, because neither approves these bytes,
                # and the sentence still says which, so the operator knows
                # whether to write a review or repair one.
                try:
                    exists = review_path(root, handle, name, label).is_file()
                except ReviewArtifactInvalid:
                    exists = False
                if exists:
                    why = "its committed review exists and could not be read"
                    rows.append((item_id, label, "unreadable", "refused"))
                else:
                    why = (f"there is no reviews/{handle}/{name}/"
                           f"{label}.json")
                    rows.append((item_id, label, "none", "refused"))
                refused.append(
                    f"{item_id} {label}: {REFUSE_ABSENT} (folder digest "
                    f"{_short(digest)}, reviewed digest none). {why}, so "
                    f"nothing has approved the bytes this version publishes."
                )
                continue
            verdict = _verdict_of(found.block)
            if found.digest != digest:
                rows.append((item_id, label, verdict, "refused, other bytes"))
                refused.append(
                    f"{item_id} {label}: {REFUSE_STALE} (folder digest "
                    f"{_short(digest)}, reviewed digest "
                    f"{_short(found.digest)}). The folder was edited after "
                    f"the review was taken, so review it again and commit "
                    f"the artifact."
                )
                continue
            overridden = is_overridden(found.block)
            note = "overridden" if overridden else "committed"
            rows.append((item_id, label, verdict, note))
            if verdict == VERDICT_BLOCKED and not overridden:
                refused.append(
                    f"{item_id} {label}: {REFUSE_BLOCKED} (folder digest "
                    f"{_short(digest)}, reviewed digest "
                    f"{_short(found.digest)}). The review read these exact "
                    f"bytes and refused them; publishing one anyway needs "
                    f"--override-blocked \"<reason>\" written into the "
                    f"committed review, which goes past CODEOWNERS in the "
                    f"pull request diff."
                )

    for row in rows:
        print(f"{row[0]} {row[1]}: {row[2]} ({row[3]})")
    if not rows:
        print("this index lists no versions, so no review was checked")
    _write_job_summary(
        rows,
        heading="committed review verdicts",
        columns=("skill", "version", "verdict", "source"),
        note=(
            "every published version needs a review committed under "
            "`reviews/` and bound to its exact folder digest. an absent "
            "one, one bound to other bytes, and a `blocked` one with no "
            "written override each refuse this build."
        ),
    )
    if refused:
        for line in refused:
            print(f"::error::{line}", file=sys.stderr)
        print(
            f"::error::this build is refused: {len(refused)} published "
            f"version(s) are not approved by a committed review of their "
            f"exact bytes. A version publishes only with a review committed "
            f"under reviews/ and bound to its folder digest. Edit the "
            f"folder, re-run the review.",
            file=sys.stderr,
        )
        return 1
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
    look.add_argument(
        "--staged", default="",
        help="review a skill folder ON DISK that is not committed yet, which "
             "is the approval moment; the digest is computed from the folder",
    )
    look.add_argument(
        "--from-index", default="",
        help="commit the review this catalog ALREADY published for these "
             "exact bytes, read out of the named index file. Calls no "
             "model and refuses when the digests differ",
    )
    look.add_argument(
        "--override-blocked", default=None, metavar="REASON",
        help="publish a blocked version anyway, writing this reason, who you "
             "are and when into the committed review. It never changes the "
             "verdict",
    )
    look.add_argument(
        "--require-clean", action="store_true",
        help="refuse anything that is not clean, not only what is blocked",
    )
    look.set_defaults(handler=cmd_review)

    audit = sub.add_parser(
        "check-reviews",
        help="refuse the build when a committed review is blocked",
    )
    audit.add_argument("--index", required=True, help="the assembled index")
    audit.set_defaults(handler=cmd_check_reviews)

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
