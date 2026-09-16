"""The publish time security review, and the three ways it can come up empty.

WHAT THIS IS FOR. Signing proves WHO wrote a skill, never that the skill is
safe. So every version gets one model's read of its own text, written into
the index at publish time and shown by the app above the SKILL.md before
anyone consents to install. It is ADVISORY. The consent button stays a human
act and the SKILL.md text is always shown next to it.

WHERE IT SITS IN THE CHAIN, WHICH IS THE PART THAT MATTERS. The review is
written AFTER the publisher's own signature has already been verified, so it
is covered by the INDEX key alone and not by the publisher's. An index key
holder could therefore forge a benign review. That is stated in the app's own
documentation rather than hidden, and it is why the review can never be the
thing that authorises an install.

"NOTHING DAMAGING DETECTED" IS ONLY EVER THE MODEL'S OWN WORDS. Every way
this step can fail writes ``status: "unavailable"`` and no summary at all:
no key, no network, a timeout, a non JSON answer, a warning kind outside the
closed list, a missing field. The app renders that literally as "no AI
review". A blank review must never read as a clean one, which is the whole
reason the status is an explicit value rather than an absent block.

THE KEY IS NEVER LOGGED, NEVER WRITTEN TO DISK AND NEVER PUT IN A URL. It
arrives as a string, goes into one Authorization header, and nothing else in
this module ever sees it.
"""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

#: Where the chat completions live.
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

#: How long one review call may take before it is given up on.
REQUEST_TIMEOUT_SECONDS = 90

#: The most response bytes that will be read from one call.
MAX_RESPONSE_BYTES = 1024 * 1024

#: The closed list of warning kinds. A model that invents an eighth has its
#: whole answer discarded, because a kind the app cannot render is a warning
#: the user would never see.
WARNING_KINDS = frozenset({
    "network", "file_delete", "credential_access", "shell_exec",
    "obfuscation", "privilege", "other",
})

#: The two statuses the index may carry.
STATUS_REVIEWED = "reviewed"
STATUS_UNAVAILABLE = "unavailable"

#: The most characters one warning detail or summary may carry into the
#: index. A model that writes an essay does not get to bloat the document
#: everybody downloads.
MAX_SUMMARY_CHARS = 1200
MAX_DETAIL_CHARS = 400

#: The most warnings one version may carry.
MAX_WARNINGS = 12

SYSTEM_PROMPT = (
    "You are a security reviewer for a public catalog of AI agent skills. "
    "A skill is a folder of instructions, sometimes with scripts, that an AI "
    "coding agent will read and act on. You are shown the full text.\n\n"
    "Answer with a single JSON object and nothing else. No markdown fence, no "
    "prose before or after. The object has exactly two keys:\n\n"
    '  "summary": one short paragraph, plain lowercase english, saying what '
    "this skill does and whether you found anything damaging. Only say nothing "
    "damaging was found if that is actually your finding.\n"
    '  "warnings": a list, empty when you found nothing, of objects with '
    'exactly two keys, "kind" and "detail".\n\n'
    "kind must be one of exactly these seven strings:\n"
    "  network            reaches the network, downloads or uploads anything\n"
    "  file_delete        deletes, truncates or overwrites files\n"
    "  credential_access  reads keys, tokens, passwords, browser or cloud creds\n"
    "  shell_exec         runs shell commands, especially built from input\n"
    "  obfuscation        encoded, minified or otherwise hidden behaviour\n"
    "  privilege          sudo, permission changes, system or daemon edits\n"
    "  other              anything damaging that none of the six above name\n\n"
    "detail is one plain sentence naming the file and what it does.\n"
    "Describe behaviour that is present. Do not speculate about what a skill "
    "could be changed to do later."
)


class ReviewUnavailable(Exception):
    """One review could not be obtained, carrying why for the job log."""


@dataclass(frozen=True)
class ReviewSettings:
    """What the review step needs to run, as one value.

    - ``api_key``: the OpenRouter key, or None when the secret was absent,
      in which case every version is recorded unavailable.
    - ``model``: the OpenRouter model id from catalog.yml.
    - ``max_chars``: how much skill text is sent for one version.
    """

    api_key: Optional[str]
    model: str
    max_chars: int


def api_key_from_secret(secret_value: str) -> Optional[str]:
    """Pull the OpenRouter key out of whatever shape the secret is in.

    Description: the secret may be a plain string or a JSON object, because
      it is an existing secret this catalog borrows rather than one created
      for it. A JSON object is searched for ``api_key``, then
      ``OPENROUTER_API_KEY``, then ``key``, and finally, when the object
      holds exactly ONE string value, that value. Anything else returns
      None, which the caller treats exactly like an absent secret: every
      version is recorded unavailable and nothing is invented.

      THE VALUE IS NEVER LOGGED OR RETURNED IN AN ERROR. A failure here
      says which shape was not understood, never what was in it.
    Inputs: secret_value (str) - the raw secret, as Secrets Manager holds it.
    Output: the key, or None when no key could be read.
    Example: api_key_from_secret('{"api_key": "sk-x"}') -> "sk-x"
    """
    stripped = secret_value.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped
    if isinstance(parsed, str):
        return parsed.strip() or None
    if not isinstance(parsed, dict):
        return None
    for field in ("api_key", "OPENROUTER_API_KEY", "key"):
        value = parsed.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    strings = [v.strip() for v in parsed.values() if isinstance(v, str) and v.strip()]
    return strings[0] if len(strings) == 1 else None


def _git_show(repo_root: Path, commit: str, path: str) -> Optional[str]:
    """Read one file's text out of the git object database.

    :param repo_root: the repository.
    :param commit: the commit to read at.
    :param path: the path, relative to the repository root.
    :returns: the text, or None when it is absent or not decodable.

    Read from the object database rather than from a checkout because the
    review runs long after the verification step removed its worktree, and
    the commit is exactly the one the signature covered.
    """
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{commit}:{path}"],
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def collect_text(
    repo_root: Path, *, commit: str, skill_path: str,
    members: Sequence[Tuple[str, str]], max_chars: int,
) -> str:
    """Gather the text a reviewer is shown for one version.

    Description: SKILL.md first, then every script bearing member, each
      under a header naming its path and its mode so the model can see
      which files are executable. The whole thing is capped; when the cap
      bites, the text is cut and a line SAYS it was cut, because a model
      reviewing a truncated file without knowing it was truncated will
      happily report that the rest is fine.
    Inputs: repo_root (Path). commit (str). skill_path (str) - the folder.
      members (sequence of (relpath, mode)) - the digest entries.
      max_chars (int) - the cap from catalog.yml.
    Output: str, the review body.
    Example: collect_text(root, commit=sha, skill_path="skills/a/b",
      members=(("SKILL.md", "100644"),), max_chars=40000)
    """
    wanted: List[Tuple[str, str]] = []
    for relpath, mode in members:
        if relpath == "SKILL.md":
            wanted.insert(0, (relpath, mode))
        elif relpath.startswith("scripts/") or mode == "100755":
            wanted.append((relpath, mode))

    chunks: List[str] = []
    used = 0
    truncated = False
    for relpath, mode in wanted:
        text = _git_show(repo_root, commit, f"{skill_path}/{relpath}")
        if text is None:
            chunks.append(f"--- {relpath} (mode {mode}): not readable as utf-8 text ---")
            continue
        header = f"--- {relpath} (mode {mode}) ---\n"
        room = max_chars - used - len(header)
        if room <= 0:
            truncated = True
            break
        if len(text) > room:
            text = text[:room]
            truncated = True
        chunks.append(header + text)
        used += len(header) + len(text)
    body = "\n\n".join(chunks)
    if truncated:
        body += (
            "\n\n--- this text was cut short at the catalog's size limit; "
            "files below this point were not shown to you ---"
        )
    return body


def _post(url: str, payload: Dict[str, object], api_key: str) -> Dict[str, object]:
    """Make the one HTTP call this module makes.

    :param url: the chat completions endpoint.
    :param payload: the request body.
    :param api_key: the bearer token, used here and nowhere else.
    :returns: the parsed response object.
    :raises ReviewUnavailable: on any transport or decoding failure.

    Every failure becomes one exception type, because every failure has the
    same consequence: the version is recorded unavailable.
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://catalog.carnivore.ai",
            "X-Title": "carnivore catalog index builder",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw = response.read(MAX_RESPONSE_BYTES)
    except urllib.error.HTTPError as exc:
        raise ReviewUnavailable(f"the review endpoint answered HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ReviewUnavailable(f"the review endpoint could not be reached: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReviewUnavailable("the review endpoint did not answer with JSON") from exc
    if not isinstance(parsed, dict):
        raise ReviewUnavailable("the review response is not an object")
    return parsed


def _content_of(response: Dict[str, object]) -> str:
    """Pull the assistant text out of a chat completions response.

    :param response: the parsed response.
    :returns: the message content.
    :raises ReviewUnavailable: when the shape is not the one documented.
    """
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ReviewUnavailable("the review response carries no choices")
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ReviewUnavailable("the review response carries no message content")
    return content


def parse_review(content: str) -> Tuple[str, List[Dict[str, str]]]:
    """Read the model's answer strictly, or refuse the whole thing.

    Description: parses the content as one JSON object and holds it to the
      documented shape. STRICTLY: an unknown warning kind, a missing
      detail, a non string summary or a list of the wrong shape discards
      the ENTIRE answer rather than the offending part. A half understood
      security review shown as a whole one is worse than none, and none is
      an honest state this index can carry.
    Inputs: content (str) - the assistant's message text.
    Output: (summary, warnings) - the summary and the validated warnings.
    Raises: ReviewUnavailable when the answer is not the documented shape.
    Example: parse_review('{"summary": "reads files", "warnings": []}')
      -> ("reads files", [])
    """
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[: -3]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewUnavailable("the model did not answer with a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ReviewUnavailable("the model's answer is not a JSON object")

    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ReviewUnavailable("the model's answer carries no summary")

    raw_warnings = parsed.get("warnings", [])
    if not isinstance(raw_warnings, list):
        raise ReviewUnavailable("the model's warnings field is not a list")
    if len(raw_warnings) > MAX_WARNINGS:
        raise ReviewUnavailable(
            f"the model returned {len(raw_warnings)} warnings, more than the "
            f"{MAX_WARNINGS} this index carries"
        )

    warnings: List[Dict[str, str]] = []
    for entry in raw_warnings:
        if not isinstance(entry, dict):
            raise ReviewUnavailable("a warning is not an object")
        kind = entry.get("kind")
        detail = entry.get("detail")
        if kind not in WARNING_KINDS:
            raise ReviewUnavailable(
                f"the model used the warning kind {kind!r}, which is not one "
                f"of the seven the app can render"
            )
        if not isinstance(detail, str) or not detail.strip():
            raise ReviewUnavailable("a warning carries no detail")
        assert isinstance(kind, str)
        warnings.append({
            "kind": kind,
            "detail": detail.strip()[:MAX_DETAIL_CHARS],
        })
    return summary.strip()[:MAX_SUMMARY_CHARS], warnings


def review_one(
    body: str, settings: ReviewSettings, *, now: str,
) -> Dict[str, object]:
    """Review one version's text, or record honestly that it could not be.

    Description: one call, one strict parse. EVERY failure path returns the
      same two key block, ``{"status": "unavailable"}``, with no summary
      and no warnings, and the reason goes to the job log rather than into
      the index: a reader of the app should see "no AI review", not an
      error message from a build machine.
    Inputs: body (str) - the skill text. settings (ReviewSettings).
      now (str) - the timestamp to stamp a successful review with.
    Output: the review block for the index.
    Example: review_one(text, settings, now="2026-09-15T00:00:00Z")["status"]
    """
    if settings.api_key is None:
        return {"status": STATUS_UNAVAILABLE}
    payload = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": body},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 1200,
        "temperature": 0,
    }
    try:
        response = _post(OPENROUTER_URL, payload, settings.api_key)
        summary, warnings = parse_review(_content_of(response))
    except ReviewUnavailable as exc:
        print(f"::warning::review unavailable: {exc}")
        return {"status": STATUS_UNAVAILABLE}
    return {
        "status": STATUS_REVIEWED,
        "summary": summary,
        "warnings": warnings,
        "model": settings.model,
        "reviewed_at": now,
    }


def existing_review(
    live_document: Optional[Dict[str, object]], item_id: str, digest: str,
) -> Optional[Dict[str, object]]:
    """Find a review already published for exactly these bytes.

    Description: matches on the DIGEST, never on the version string, so a
      version republished with different content is reviewed again while
      an unchanged one keeps the words a user has already read. The live
      document is only ever the one whose signature verified under the
      pinned index key; an unverified one is never passed in, because a
      review lifted from bytes nobody signed is a review an attacker wrote.
    Inputs: live_document (dict or None) - the VERIFIED live index.
      item_id (str) - ``<publisher>/<name>``. digest (str).
    Output: the review block to reuse, or None.
    Example: existing_review(live, "adoom666/work", digest) -> {...}
    """
    if not isinstance(live_document, dict):
        return None
    items = live_document.get("items")
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict) or item.get("id") != item_id:
            continue
        versions = item.get("versions")
        if not isinstance(versions, list):
            return None
        for version in versions:
            if not isinstance(version, dict) or version.get("digest") != digest:
                continue
            review = version.get("review")
            if isinstance(review, dict) and review.get("status") == STATUS_REVIEWED:
                return review
        return None
    return None
