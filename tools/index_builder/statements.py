"""The exact bytes a publisher signs, copied from the product repo.

THIS FILE IS A COPY OF TWO RENDERERS AND THEIR FIELD SHAPES:
``release_statement`` from the product repo's ``src/models/catalog_statement.py``
and ``revoke_statement`` from its ``src/core/catalog/revocation.py``, with the
two regular expressions and the match helper they need lifted out of
``src/models/catalog.py`` so this module stands alone.

WHY A COPY AT ALL. The build job runs in this repository and cannot import
the app. The app verifies what this job publishes. So the same bytes are
rendered twice, by two programs, and one differing byte is a signature that
does not verify, which on the verifying side is indistinguishable from a
forgery. The layout is therefore spelled out line by line in both places and
a change to it is obvious in a diff.

WHAT KEEPS THE TWO HONEST. ``digest_vectors.json`` is shared byte for byte
between the two repositories and a test in each reproduces every vector, so
the DIGEST cannot drift silently. The statement layout has no such vector
file; it is guarded by being written out in full, in both files, with this
warning at the top of each. Change one and you must change the other in the
same afternoon or the catalog stops verifying.
"""

from __future__ import annotations

import re

#: A skill name. Lowercase, starts alphanumeric, 64 characters at most.
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")

#: A publisher handle. The GitHub login shape, 39 characters at most.
PUBLISHER_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$")

#: A git commit, always the full 40 lowercase hex and never abbreviated.
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

#: A folder digest, 64 lowercase hex.
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

#: The first line of a release statement. Signing a statement with a
#: different first line is signing a different kind of claim.
RELEASE_STATEMENT_HEADER = "carnivore-release-v1"

#: The first line of a revocation statement.
REVOKE_STATEMENT_HEADER = "carnivore-revoke-v1"

#: The two things a revocation can name.
KIND_KEY = "key"
KIND_VERSION = "version"

#: What separates an item id from a version inside a version revocation's
#: subject. It is not legal in a version string, so the subject parses back
#: unambiguously.
VERSION_SUBJECT_SEPARATOR = "@"


def match_or_raise(value: str, pattern: "re.Pattern[str]", what: str) -> str:
    """Return the value when it matches, raise with its name when it does not.

    :param value: the candidate string.
    :param pattern: the compiled shape it must match.
    :param what: the field name, used in the error message only.
    :returns: the value unchanged.
    :raises ValueError: when the value does not match.

    Example: match_or_raise("work", SKILL_NAME_RE, "name") -> "work"
    """
    if not pattern.match(value):
        raise ValueError(f"{what} {value!r} does not match {pattern.pattern}")
    return value


def release_statement(
    *,
    kind: str,
    publisher: str,
    name: str,
    version: str,
    repo: str,
    path: str,
    commit: str,
    digest: str,
) -> bytes:
    """Render the exact bytes a publisher signs for one release.

    Description: NINE LINES, EACH TERMINATED BY ONE LF (0x0A), in this
      order and no other, encoded UTF-8::

        carnivore-release-v1\\n
        <kind>\\n
        <publisher>\\n
        <name>\\n
        <version>\\n
        <repo>\\n
        <path>\\n
        <commit>\\n
        <digest>\\n

      There is no trailing blank line, no CR anywhere, and no separator
      other than the LF.

      EVERY FIELD IS REFUSED IF IT CONTAINS A LINE BREAK. A newline inside
      ``repo`` or ``path`` would let one signed statement be read as a
      different statement with different fields, which is the canonical
      form injection this line-oriented format is otherwise wide open to.
      ``publisher`` and ``name`` are additionally held to their own
      shapes, because those two become a filesystem path.
    Inputs: kind, publisher, name, version, repo, path, commit, digest -
      all str, all keyword only so no call site can transpose two of them.
    Output: bytes - the statement, ready to sign or verify.
    Raises: ValueError on an empty field, a field containing CR or LF, or
      a publisher or name that fails its shape.
    Example: release_statement(kind="skill", publisher="adoom666",
      name="work", version="1.0.0", repo="Adoom666/CarnivoreAI-Skills",
      path="skills/adoom666/work", commit="a" * 40, digest="b" * 64)
      .startswith(b"carnivore-release-v1\\n") -> True
    """
    fields = {
        "kind": kind,
        "publisher": publisher,
        "name": name,
        "version": version,
        "repo": repo,
        "path": path,
        "commit": commit,
        "digest": digest,
    }
    for field_name, value in fields.items():
        if not value:
            raise ValueError(f"release statement field {field_name} is empty")
        if "\n" in value or "\r" in value:
            raise ValueError(
                f"release statement field {field_name} contains a line break"
            )
    match_or_raise(fields["publisher"], PUBLISHER_RE, "publisher")
    match_or_raise(fields["name"], SKILL_NAME_RE, "name")

    lines = [RELEASE_STATEMENT_HEADER, *fields.values()]
    return ("".join(f"{line}\n" for line in lines)).encode("utf-8")


def version_subject(item_id: str, version: str) -> str:
    """Render the subject of a version revocation.

    :param item_id: ``<publisher>/<name>``, both signed fields.
    :param version: the version string.
    :returns: ``"<item_id>@<version>"``.

    Example: version_subject("adoom666/work", "1.2.0") -> "adoom666/work@1.2.0"
    """
    return f"{item_id}{VERSION_SUBJECT_SEPARATOR}{version}"


def revoke_statement(*, kind: str, subject: str, since: str) -> bytes:
    """Render the exact bytes a publisher signs to revoke something.

    Description: FOUR LINES, EACH TERMINATED BY ONE LF (0x0A), in this
      order and no other, encoded UTF-8::

        carnivore-revoke-v1\\n
        <kind>\\n
        <subject>\\n
        <since>\\n

      There is no trailing blank line, no CR anywhere, and no separator
      other than the LF. Same line oriented shape as the release
      statement, and refused the same way when a field carries a break.
      ``kind`` is held to the two values that exist, because a statement
      whose kind the verifier does not recognise revokes nothing.
    Inputs: kind (str) - ``"key"`` or ``"version"``. subject (str) - a key
      id, or ``"<item_id>@<version>"``. since (str) - the timestamp, as it
      will appear in the index.
    Output: bytes - the statement, ready to sign or verify.
    Raises: ValueError on an unknown kind, an empty field, or a field
      carrying CR or LF.
    Example: revoke_statement(kind="key", subject="5F522AB084F4E697",
      since="2026-09-15") -> b"carnivore-revoke-v1\\nkey\\n5F52...\\n2026-09-15\\n"
    """
    if kind not in (KIND_KEY, KIND_VERSION):
        raise ValueError(f"revocation kind must be key or version, got {kind!r}")
    fields = {"kind": kind, "subject": subject, "since": since}
    for field_name, value in fields.items():
        if not value:
            raise ValueError(f"revocation statement field {field_name} is empty")
        if "\n" in value or "\r" in value:
            raise ValueError(
                f"revocation statement field {field_name} contains a line break"
            )

    lines = [REVOKE_STATEMENT_HEADER, *fields.values()]
    return ("".join(f"{line}\n" for line in lines)).encode("utf-8")
