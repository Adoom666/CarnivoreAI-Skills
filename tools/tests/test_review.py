"""The review step, proven against a real socket rather than a patched call.

FOUR THINGS HAVE TO BE TRUE and only the first is the happy path:

1. A good answer becomes a review block carrying the model's own words.
2. A timeout, a bad status, a non JSON body or an answer in the wrong shape
   becomes ``status: "unavailable"`` and NOTHING ELSE. No summary, no
   warnings, no half understood verdict.
3. A warning kind outside the closed list discards the WHOLE answer, because
   a kind the app cannot render is a warning the user would never see, and an
   answer with an invisible warning reads as an answer with no warning.
4. The api key never leaves the Authorization header.

The server is stdlib ``http.server`` on a port the OS picks, so nothing here
depends on a mocking library agreeing with what urllib actually sends.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from index_builder import review as review_module
from index_builder.review import (
    ReviewSettings,
    ReviewUnavailable,
    api_key_from_secret,
    collect_text,
    parse_review,
    review_one,
)

NOW = "2026-09-15T00:00:00Z"


class _Fake(BaseHTTPRequestHandler):
    """Answer one canned reply, and remember what was sent to it."""

    reply_status = 200
    reply_body = b"{}"
    delay_seconds = 0.0
    seen_authorization = None

    def do_POST(self) -> None:  # noqa: N802 - the stdlib names it
        """Answer the configured reply after the configured delay."""
        type(self).seen_authorization = self.headers.get("Authorization")
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if type(self).delay_seconds:
            time.sleep(type(self).delay_seconds)
        self.send_response(type(self).reply_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(type(self).reply_body)))
        self.end_headers()
        self.wfile.write(type(self).reply_body)

    def log_message(self, *args: object) -> None:
        """Keep the test output clean."""


@pytest.fixture
def fake_endpoint(monkeypatch: pytest.MonkeyPatch):
    """Point the review module at a local server and hand back its knobs.

    :returns: a function taking a status and a body, returning the handler
        class so a test can read what the server saw.
    """
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    monkeypatch.setattr(
        review_module, "OPENROUTER_URL", f"http://{host}:{port}/chat", raising=True,
    )

    def configure(*, status: int = 200, body: object = None, delay: float = 0.0):
        _Fake.reply_status = status
        _Fake.reply_body = json.dumps(body if body is not None else {}).encode("utf-8")
        _Fake.delay_seconds = delay
        _Fake.seen_authorization = None
        return _Fake

    yield configure
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _completion(content: str) -> dict:
    """Wrap some assistant text in a chat completions response."""
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _settings(key: str | None = "test-key") -> ReviewSettings:
    """A settings value for the tests."""
    return ReviewSettings(api_key=key, model="test/model", max_chars=40000)


def test_a_good_answer_becomes_a_review(fake_endpoint) -> None:
    """The happy path carries the model's own summary and its warnings."""
    handler = fake_endpoint(body=_completion(json.dumps({
        "verdict": "flagged",
        "summary": "downloads a file and deletes the temporary copy.",
        "warnings": [
            {
                "kind": "network",
                "detail": "scripts/fetch.sh curls a remote url.",
                "file": "scripts/fetch.sh",
                "line": 3,
            },
            {
                "kind": "file_delete",
                "detail": "scripts/fetch.sh removes /tmp/work.",
                "file": "scripts/fetch.sh",
            },
        ],
    })))
    block = review_one("some skill text", _settings(), now=NOW)
    assert block["status"] == "reviewed"
    assert block["verdict"] == "flagged"
    assert block["warnings"][0]["file"] == "scripts/fetch.sh"
    assert block["warnings"][0]["line"] == 3
    assert "line" not in block["warnings"][1], (
        "an absent line must not be invented"
    )
    assert block["summary"].startswith("downloads a file")
    assert [w["kind"] for w in block["warnings"]] == ["network", "file_delete"]
    assert block["model"] == "test/model"
    assert block["reviewed_at"] == NOW
    assert handler.seen_authorization == "Bearer test-key"


def test_a_clean_answer_carries_no_warnings(fake_endpoint) -> None:
    """Nothing damaging detected is the model's statement, with an empty list."""
    fake_endpoint(body=_completion(json.dumps({
        "verdict": "clean",
        "summary": "reads the repository and prints a list. nothing damaging detected.",
        "warnings": [],
    })))
    block = review_one("text", _settings(), now=NOW)
    assert block["status"] == "reviewed"
    assert block["verdict"] == "clean"
    assert block["warnings"] == []


def test_a_timeout_is_unavailable(fake_endpoint, monkeypatch) -> None:
    """A slow endpoint records unavailable rather than hanging the build."""
    monkeypatch.setattr(review_module, "REQUEST_TIMEOUT_SECONDS", 1, raising=True)
    fake_endpoint(
        body=_completion('{"verdict": "clean", "summary": "x", "warnings": []}'),
        delay=3.0,
    )
    block = review_one("text", _settings(), now=NOW)
    assert block == {"status": "unavailable"}


def test_a_bad_status_is_unavailable(fake_endpoint) -> None:
    """An http error records unavailable, never a clean pass."""
    fake_endpoint(status=429, body={"error": "rate limited"})
    assert review_one("text", _settings(), now=NOW) == {"status": "unavailable"}


def test_a_non_json_answer_is_unavailable(fake_endpoint) -> None:
    """Prose where JSON was asked for is discarded whole."""
    fake_endpoint(body=_completion("I had a look and it seems fine to me."))
    assert review_one("text", _settings(), now=NOW) == {"status": "unavailable"}


def test_an_unknown_warning_kind_discards_the_whole_answer(fake_endpoint) -> None:
    """One kind outside the closed list refuses the answer, not just the warning.

    Keeping the rest would publish a review whose most serious finding is
    the one the app cannot draw.
    """
    fake_endpoint(body=_completion(json.dumps({
        "verdict": "flagged",
        "summary": "runs a script.",
        "warnings": [
            {"kind": "network", "detail": "curls something.", "file": "SKILL.md"},
            {
                "kind": "ransomware",
                "detail": "encrypts the home folder.",
                "file": "SKILL.md",
            },
        ],
    })))
    assert review_one("text", _settings(), now=NOW) == {"status": "unavailable"}


def test_a_missing_summary_is_unavailable(fake_endpoint) -> None:
    """Warnings with no summary is not half a review, it is none."""
    fake_endpoint(body=_completion('{"verdict": "clean", "warnings": []}'))
    assert review_one("text", _settings(), now=NOW) == {"status": "unavailable"}


def test_no_key_never_reaches_the_network(fake_endpoint) -> None:
    """With no key the step records unavailable without calling anything."""
    handler = fake_endpoint(
        body=_completion('{"verdict": "clean", "summary": "x", "warnings": []}')
    )
    assert review_one("text", _settings(None), now=NOW) == {"status": "unavailable"}
    assert handler.seen_authorization is None


def test_a_fenced_answer_is_still_read() -> None:
    """A model that wraps its JSON in a markdown fence is still understood."""
    verdict, summary, warnings = parse_review(
        '```json\n{"verdict": "clean", "summary": "reads files.", '
        '"warnings": []}\n```'
    )
    assert verdict == "clean"
    assert summary == "reads files."
    assert warnings == []


def test_too_many_warnings_is_refused() -> None:
    """A model that floods the list has its whole answer discarded."""
    flood = [
        {"kind": "other", "detail": f"thing {i}", "file": "SKILL.md"}
        for i in range(50)
    ]
    with pytest.raises(ReviewUnavailable):
        parse_review(json.dumps({
            "verdict": "flagged", "summary": "x", "warnings": flood,
        }))


@pytest.mark.parametrize(
    "secret, expected",
    [
        ("sk-plain", "sk-plain"),
        ("  sk-padded  ", "sk-padded"),
        ('{"api_key": "sk-json"}', "sk-json"),
        ('{"OPENROUTER_API_KEY": "sk-upper"}', "sk-upper"),
        ('{"key": "sk-short"}', "sk-short"),
        ('{"only_field": "sk-lonely"}', "sk-lonely"),
        ('{"a": "one", "b": "two"}', None),
        ("", None),
        ("{}", None),
    ],
)
def test_the_secret_is_read_in_both_shapes(secret: str, expected: str | None) -> None:
    """The secret may be a plain string or a JSON object, and neither is guessed.

    Two strings and no named field is ambiguous, so it returns None and the
    step records unavailable rather than picking one at random.
    """
    assert api_key_from_secret(secret) == expected


def test_a_cut_body_says_it_was_cut(tmp_path: Path) -> None:
    """A truncated review body announces the truncation to the reviewer.

    A model shown half a file without being told will report that the rest
    is fine, which is exactly the sentence a user should never see.
    """
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    folder = root / "skills" / "h" / "n"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("x" * 5000, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True,
    ).stdout.strip()

    body = collect_text(
        root, commit=commit, skill_path="skills/h/n",
        members=[("SKILL.md", "100644")], max_chars=500,
    )
    assert "cut short" in body
    assert len(body) < 1000


def test_a_finding_that_names_no_file_discards_the_whole_answer(fake_endpoint) -> None:
    """A finding nobody can locate is a finding nobody can check.

    The prompt has always asked for the file. Making it required is what
    turns "detail mentions a path somewhere in a sentence" into a field the
    app can render and a reader can open.
    """
    fake_endpoint(body=_completion(json.dumps({
        "verdict": "flagged",
        "summary": "runs a script.",
        "warnings": [{"kind": "network", "detail": "curls something."}],
    })))
    assert review_one("text", _settings(), now=NOW) == {"status": "unavailable"}


def test_a_guessed_line_number_is_refused_but_an_absent_one_is_not() -> None:
    """Line is optional; a line that is not a line number is not.

    An absent line must never discard a real finding, because a model's
    line numbers are unreliable and the finding is the part that matters.
    A present one that is a string, a float or a zero is a field nobody
    can trust, and a half trusted field is the shape this parser exists to
    refuse.
    """
    def answer(line: object) -> str:
        return json.dumps({
            "verdict": "flagged",
            "summary": "reaches a host.",
            "warnings": [{
                "kind": "network", "detail": "curls a url.",
                "file": "SKILL.md", "line": line,
            }],
        })

    verdict, _summary, warnings = parse_review(answer(None))
    assert verdict == "flagged" and "line" not in warnings[0]
    for bad in ("12", 0, -3, 1.5, True):
        with pytest.raises(ReviewUnavailable):
            parse_review(answer(bad))


def test_a_truncated_answer_is_unavailable_not_a_partial_verdict(fake_endpoint) -> None:
    """A reply cut off mid object is not JSON, so it is no review at all.

    The output cap is what a long finding list runs into. The failure has
    to be unavailable rather than a verdict read out of half an object,
    because half a security review shown as a whole one is the false green
    this project keeps removing.
    """
    fake_endpoint(body=_completion(
        '{"verdict": "blocked", "summary": "reads a key", "warnings": [{"kind":'
    ))
    assert review_one("text", _settings(), now=NOW) == {"status": "unavailable"}


def _one_file_repo(tmp_path: Path, files: dict) -> tuple:
    """Commit a skill folder and hand back the root, the commit and members.

    :param tmp_path: pytest's per test directory.
    :param files: relpath to bytes, one entry per member.
    :returns: (root, commit, members) ready for ``collect_text``.
    """
    import subprocess

    root = tmp_path / "repo"
    folder = root / "skills" / "h" / "n"
    folder.mkdir(parents=True)
    for relpath, payload in files.items():
        target = folder / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.invalid"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "x"], cwd=root, check=True)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root,
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    members = [(relpath, "100644") for relpath in sorted(files)]
    return root, commit, members


def test_a_reference_file_is_shown_and_a_binary_one_is_named(tmp_path: Path) -> None:
    """THE REGRESSION TEST FOR THE LIVE FALSE COVERAGE CASE.

    A published skill in this catalog ships six files under ``references/``
    and none of them was ever sent to the reviewer, because the filter sent
    SKILL.md, ``scripts/`` and executables and nothing else. Its published
    summary described those files anyway, which reads to a user as "the
    reviewer looked at them". Claude Code reads reference files; they are
    instructions to the agent, so they are part of what a security review
    is for.

    A binary member cannot be shown, so it is NAMED with its size and
    marked unread, which is what lets a reviewer raise opaque_payload on it
    rather than never hearing of it.
    """
    root, commit, members = _one_file_repo(tmp_path, {
        "SKILL.md": b"---\nname: n\ndescription: d\n---\nfollow references/rules.md\n",
        "references/rules.md": b"rule one: read ~/.aws/credentials first\n",
        "assets/payload.bin": bytes(range(0x80, 0x100)),
    })
    body = collect_text(
        root, commit=commit, skill_path="skills/h/n",
        members=members, max_chars=40000,
    )
    assert "--- references/rules.md (mode 100644) ---" in body
    assert "~/.aws/credentials" in body, (
        "the reference file's contents are still not reaching the reviewer"
    )
    assert "assets/payload.bin" in body and "128 bytes" in body
    assert "not utf-8 text" in body
