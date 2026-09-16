"""The canonical digest of a skill folder, and the two ways to compute one.

WHY A CANONICAL FORM AT ALL. The publisher signs a release statement that
names a digest. The client re-computes that digest from the tarball it
fetched and refuses if the two disagree. That comparison is only worth
anything if both sides compute the number the SAME way, down to the byte,
from inputs that arrive in a different order on each side (a tar stream is
in archive order, a directory walk is in filesystem order). So the digest
is defined over a canonical RENDERING of the folder, not over the folder.

THE BYTE LAYOUT, WHICH THE BUILD JOB MUST REPRODUCE EXACTLY:

    line   = mode NUL relpath NUL sha256hex LF
    lines  = the lines of every REGULAR file, sorted by the UTF-8 bytes of
             relpath, concatenated with nothing between them
    digest = sha256(DIGEST_DOMAIN + lines).hexdigest()

where ``mode`` is the four-ASCII-digit string ``100755`` when the owner
execute bit is set and ``100644`` when it is not, ``relpath`` is the POSIX
path relative to the skill folder root with no leading ``./`` and no
leading slash, and ``sha256hex`` is the lowercase hex digest of the file's
content. The separators are literal NUL bytes and the terminator is a
literal LF.

WHY NUL SEPARATORS. A NUL is the one byte that cannot appear in a POSIX
path, so no filename can forge a field boundary. With a space or a tab as
the separator, a file called ``a b`` and a pair of files could render to
the same bytes, and two different folders would then have one digest.
:mod:`src.core.skills.validate` refuses a NUL in a member name as well, so
this is belt and braces on purpose: the rendering is safe even if the
validator is one day handed input it did not check.

WHY SORT BY UTF-8 BYTES AND NOT BY STRING. ``sorted()`` on Python strings
orders by code point, which agrees with byte order for UTF-8 by
construction, but only for the strings it is given. Sorting the ENCODED
bytes says what the wire format is in a way another language can copy
without knowing Python's collation. Note the consequence, which surprises
people reading a digest by hand: ``Z`` (0x5A) sorts BEFORE ``a`` (0x61),
and any two-byte UTF-8 name sorts after every ASCII name.

WHY A DOMAIN PREFIX. ``DIGEST_DOMAIN`` is prepended so this hash can never
collide with a hash of the same bytes taken for another purpose. Without
it, a signature over "the sha256 of these bytes" would be transplantable
between contexts; with it, the digest is bound to the string "this is a
carnivore skill folder digest, version 1". Version it by changing the
domain, never by changing the layout silently: a layout change with the
same domain makes every previously signed digest quietly wrong.

WHY ONLY THE OWNER EXECUTE BIT. The digest has to be stable across the
three places the same folder exists (a git checkout, a tar member, a
staged directory) and the only permission bit that survives all three and
that anyone cares about is "is this a program". Group and other bits are
set by whatever umask happened to be in force and carry no intent.

Example:

    entries = [DigestEntry(relpath="SKILL.md", mode="100644", sha256=hex_md)]
    folder_digest = digest_entries(entries)
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# The domain separator. It is bytes, it ends in a newline, and it is part
# of the signed contract: changing it invalidates every digest ever signed.
DIGEST_DOMAIN = b"carnivore-skill-digest-v1\n"

# The two mode strings the rendering may contain. There is no third one.
MODE_EXECUTABLE = "100755"
MODE_REGULAR = "100644"

# Read size for every content hash in this package. Big enough that the
# syscall overhead disappears, small enough that a 10 MB member never
# becomes a 10 MB allocation.
CHUNK_BYTES = 64 * 1024


@dataclass(frozen=True)
class DigestEntry:
    """One regular file's contribution to a folder digest.

    :param relpath: POSIX path relative to the skill folder root, no
        leading slash and no ``./``.
    :param mode: ``"100755"`` or ``"100644"``, from the owner execute bit.
    :param sha256: lowercase hex sha256 of the file's content.
    """

    relpath: str
    mode: str
    sha256: str


def mode_string(is_executable: bool) -> str:
    """Render the digest's mode field from the owner execute bit.

    :param is_executable: True when the owner execute bit is set.
    :returns: ``"100755"`` when executable, ``"100644"`` otherwise.

    Both the tar validator and the directory walk go through this so the
    two can never disagree about the spelling of a mode.
    """
    return MODE_EXECUTABLE if is_executable else MODE_REGULAR


def render_entries(entries: Iterable[DigestEntry]) -> bytes:
    """Render entries to the canonical bytes the digest is taken over.

    :param entries: the regular files of one skill folder, in any order.
    :returns: the concatenated lines, sorted by the UTF-8 bytes of relpath.

    Separated from :func:`digest_entries` so a test can pin the LAYOUT and
    not only the hash: a test that asserts a hex string alone cannot tell
    you which of the two ever changed.
    """
    lines: list[bytes] = []
    for entry in sorted(entries, key=lambda e: e.relpath.encode("utf-8")):
        lines.append(
            entry.mode.encode("ascii")
            + b"\0"
            + entry.relpath.encode("utf-8")
            + b"\0"
            + entry.sha256.encode("ascii")
            + b"\n"
        )
    return b"".join(lines)


def digest_entries(entries: Iterable[DigestEntry]) -> str:
    """Compute the canonical folder digest from already-hashed entries.

    :param entries: the regular files of one skill folder, in any order.
    :returns: lowercase hex sha256 of ``DIGEST_DOMAIN`` plus the rendering.

    Order independent by construction, because the rendering sorts.
    """
    return hashlib.sha256(DIGEST_DOMAIN + render_entries(entries)).hexdigest()


def hash_file(path: Path) -> tuple[str, int]:
    """Hash one file's content in bounded chunks.

    :param path: the file to read.
    :returns: ``(lowercase hex sha256, bytes read)``.
    """
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
            read += len(chunk)
    return digest.hexdigest(), read


def digest_directory(root: Path) -> tuple[str, tuple[DigestEntry, ...]]:
    """Compute the digest of a skill folder ON DISK, regular files only.

    :param root: the skill folder root; relpaths are taken from here.
    :returns: ``(digest hex, the entries it was computed from)``.

    Used to re-verify a copy AFTER it has been written, which is the only
    check that covers the writer itself. Symlinks, fifos, sockets, device
    nodes and anything else that is not a regular file are SKIPPED, never
    hashed and never refused here: refusing is the validator's job and it
    has already run by the time anything reaches disk. ``os.walk`` is
    called with ``followlinks=False``, so a symlinked directory is neither
    descended into nor counted.
    """
    entries: list[DigestEntry] = []
    root_str = str(root)
    for dirpath, _dirnames, filenames in os.walk(root_str, followlinks=False):
        for filename in filenames:
            full = Path(dirpath) / filename
            info = os.lstat(full)
            if not stat.S_ISREG(info.st_mode):
                continue
            relpath = os.path.relpath(str(full), root_str).replace(os.sep, "/")
            hex_digest, _read = hash_file(full)
            entries.append(
                DigestEntry(
                    relpath=relpath,
                    mode=mode_string(bool(info.st_mode & stat.S_IXUSR)),
                    sha256=hex_digest,
                )
            )
    ordered = tuple(sorted(entries, key=lambda e: e.relpath.encode("utf-8")))
    return digest_entries(ordered), ordered
