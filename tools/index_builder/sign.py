"""The one step that touches the index signing key, and how it lets go of it.

EVERYTHING ELSE IN THIS BUILD IS REPRODUCIBLE FROM PUBLIC INPUTS. This is
not, so it runs in its own job, reads its one secret from AWS Secrets Manager
through an OIDC assumed role, and hands the next job nothing but an artifact.

THE KEY IS ONLY EVER A STRING AND A FILE THAT IS DELETED. minisign will not
sign from standard input, so the key has to reach the disk. It is written to
a file created with mode 0600 inside a private temporary directory, and the
``finally`` overwrites the bytes before unlinking, so the delete does not
depend on the sign having worked. Nothing prints it, nothing logs it and the
path never goes into the job summary.

THE JOB VERIFIES ITS OWN OUTPUT BEFORE IT SHIPS IT. A signature nobody
checked is a signature that might be over the wrong bytes, and the first
place anyone would find out is a client refusing the whole catalog. So the
new ``.minisig`` is verified here, against the public key pinned IN THE
REPOSITORY rather than against anything derived from the secret: checking a
signature with a key that came out of the same secret would prove only that
the secret is self consistent.

AND IT SKIPS RATHER THAN FAILS WHEN THE SECRET IS ABSENT. Until Adam has
created the secret there is no key to sign with, and a red build every night
would teach everybody to ignore the build. An absent secret prints what is
missing and produces no signature, which is what stops the deploy.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .minisign_verify import MinisignFormatError, PublicKey, parse_signature, verify

#: The binary that does the signing. Installed from the Ubuntu universe
#: repository on the runner.
MINISIGN = "minisign"

#: How long one minisign invocation may take. It signs one small file; a
#: minute means it is sitting on a prompt that will never be answered.
SIGN_TIMEOUT_SECONDS = 60

#: How the trusted comment reads. It is covered by the global signature, so
#: a reader can trust what it says about the serial, and the app compares it
#: to nothing: it is there for a human looking at a signature by hand.
TRUSTED_COMMENT = "carnivore index serial {serial} {generated_at}"


class SigningSkipped(Exception):
    """There was no key to sign with, which is not a failure."""


class SigningFailed(Exception):
    """There was a key and the signing or its verification went wrong."""


@dataclass(frozen=True)
class SecretKeyMaterial:
    """The secret as Secrets Manager holds it, already split into parts.

    - ``secret_key``: the full text of the minisign ``.key`` file.
    - ``password``: empty for a key generated with ``minisign -G -W``,
      which is how this one is generated, so nothing ever prompts.
    """

    secret_key: str
    password: str


def parse_secret(secret_value: str) -> SecretKeyMaterial:
    """Read the signing secret out of its JSON envelope.

    Description: the secret is a JSON object with ``secret_key`` and
      ``password``. A missing or empty ``secret_key`` is treated as NO KEY
      rather than as a malformed one, because the honest reading of an
      empty secret is that Adam has not filled it in yet.
    Inputs: secret_value (str) - the raw secret string.
    Output: SecretKeyMaterial.
    Raises: SigningSkipped when there is no key text in it.
    Example: parse_secret('{"secret_key": "untrusted comment...", "password": ""}')
    """
    stripped = secret_value.strip()
    if not stripped:
        raise SigningSkipped("the index signing secret is empty")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise SigningFailed(
            "the index signing secret is not JSON; it must be an object with "
            "secret_key and password"
        ) from exc
    if not isinstance(parsed, dict):
        raise SigningFailed("the index signing secret is not a JSON object")
    key_text = parsed.get("secret_key")
    if not isinstance(key_text, str) or not key_text.strip():
        raise SigningSkipped("the index signing secret carries no secret_key")
    password = parsed.get("password")
    if password is None:
        password = ""
    if not isinstance(password, str):
        raise SigningFailed("the index signing secret's password is not a string")
    return SecretKeyMaterial(secret_key=key_text, password=password)


def _shred(path: Path) -> None:
    """Overwrite a file's bytes, then remove it.

    :param path: the key file.
    :returns: None.

    Overwriting first means a failure to unlink still leaves no key behind,
    and it does not depend on ``shred`` being installed. Every error here
    is swallowed deliberately, with this comment saying why: this runs in a
    ``finally`` and an exception raised from it would replace the real
    error the caller is already carrying.
    """
    try:
        size = path.stat().st_size
        with path.open("r+b") as handle:
            handle.write(b"\0" * size)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        pass
    try:
        path.unlink()
    except OSError:
        pass


def sign_index(
    index_path: Path,
    *,
    secret_value: str,
    serial: int,
    generated_at: str,
    index_key: Optional[PublicKey],
) -> str:
    """Sign the index and prove the signature before returning it.

    Description: writes the key to a 0600 file in a private temporary
      directory, runs ``minisign -S -W`` over the index with the trusted
      comment naming the serial, reads the ``.minisig`` it produced,
      verifies it against the key pinned in the repository, and shreds the
      key file whether or not any of that worked. Standard input is closed
      so a key that unexpectedly wants a password fails in a minute instead
      of hanging the job forever.
    Inputs: index_path (Path) - the exact bytes to sign. secret_value (str)
      - the raw secret. serial (int), generated_at (str) - for the trusted
      comment. index_key (PublicKey or None) - the key pinned in the
      repository, used to check this job's own output.
    Output: str - the contents of the ``.minisig`` file.
    Raises: SigningSkipped when the secret carries no key. SigningFailed
      when minisign fails, or when the signature does not verify.
    Example: sign_index(Path("index.json"), secret_value=raw, serial=1,
      generated_at="2026-09-15T00:00:00Z", index_key=pinned)
    """
    material = parse_secret(secret_value)
    if index_key is None:
        raise SigningFailed(
            "publishers/_index.json pins no index public key, so this job "
            "cannot check its own signature. Paste the public half before "
            "signing anything: an unchecked signature is how a catalog goes "
            "dark for every client at once."
        )

    signature_path = index_path.with_suffix(index_path.suffix + ".minisig")
    with tempfile.TemporaryDirectory(prefix="carnivore-sign-") as tmp:
        key_path = Path(tmp) / "index.key"
        handle = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as writer:
                writer.write(material.secret_key)
                if not material.secret_key.endswith("\n"):
                    writer.write("\n")
            comment = TRUSTED_COMMENT.format(serial=serial, generated_at=generated_at)
            result = subprocess.run(
                [
                    MINISIGN, "-S", "-W",
                    "-s", str(key_path),
                    "-m", str(index_path),
                    "-t", comment,
                ],
                capture_output=True, text=True, check=False,
                stdin=subprocess.DEVNULL, timeout=SIGN_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                raise SigningFailed(
                    f"minisign exited {result.returncode}: "
                    f"{result.stderr.strip() or 'no stderr'}"
                )
        finally:
            _shred(key_path)

    if not signature_path.is_file():
        raise SigningFailed(f"minisign wrote no {signature_path.name}")
    signature_text = signature_path.read_text(encoding="utf-8")

    try:
        signature = parse_signature(signature_text)
        ok = verify(index_path.read_bytes(), signature, index_key,
                    expect_prehashed=True)
    except MinisignFormatError as exc:
        raise SigningFailed(f"the signature this job made does not parse: {exc}") from exc
    if not ok:
        raise SigningFailed(
            "the signature this job made does not verify under the index key "
            "pinned in publishers/_index.json. The secret and the pinned "
            "public half are not a pair."
        )
    return signature_text
