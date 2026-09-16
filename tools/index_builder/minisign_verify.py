"""A VERBATIM COPY of the product repo's src/core/catalog/minisign.py.

THE ONLY EDIT IS THE LOGGER. The product repo logs through structlog,
which this repo does not depend on, so a four line shim gives the stdlib
logger structlog's event-name-first call shape and every call site below
is left exactly as it is in the product repo. Nothing else may be edited
here: this module and the app's own verifier have to agree on whether a
signature is good, and the build job is the side that decides what gets
published. Port a fix to both or to neither.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from dataclasses import dataclass

import logging
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

class _KwLogger:
    """Give the stdlib logger structlog's event-name-first call shape.

    :param name: the module name the records are attributed to.

    Exists only so the call sites copied from the product repo need no
    edit at all. It carries the one method this module uses.
    """

    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(name)

    def warning(self, event: str, **context: object) -> None:
        """Log one warning as an event name plus its context mapping."""
        self._log.warning("%s %s", event, context)


logger = _KwLogger(__name__)

#: Signature algorithm marker for the prehashed format: the Ed25519
#: signature covers BLAKE2b-512 of the message.
ALG_PREHASHED: bytes = b"ED"

#: Signature algorithm marker for the legacy format: the Ed25519 signature
#: covers the raw message.
ALG_LEGACY: bytes = b"Ed"

#: The algorithm marker minisign puts in a PUBLIC KEY file. It is always
#: ``Ed`` there; the prehash choice lives on the signature, not on the key.
_PUBLIC_KEY_ALG: bytes = b"Ed"

_KEY_ID_BYTES: int = 8
_ED25519_PUBLIC_KEY_BYTES: int = 32
_ED25519_SIGNATURE_BYTES: int = 64

#: 2 byte algorithm + 8 byte key id + 32 byte Ed25519 public key.
_PUBLIC_KEY_BLOB_BYTES: int = 42

#: 2 byte algorithm + 8 byte key id + 64 byte Ed25519 signature.
_SIGNATURE_BLOB_BYTES: int = 74

_UNTRUSTED_COMMENT_PREFIX: str = "untrusted comment: "
_TRUSTED_COMMENT_PREFIX: str = "trusted comment: "


class MinisignFormatError(ValueError):
    """A key or signature could not be parsed as minisign.

    This is the MALFORMED outcome and it is deliberately distinct from a
    cryptographic failure. :func:`verify` returns False when the bytes
    parsed and the mathematics disagreed; it raises this when there were
    never well-formed bytes to check. Collapsing the two would let "we
    could not look" read as "we looked and it was wrong".
    """


def format_key_id(raw: bytes) -> str:
    """Render minisign's 8 key-id bytes the way minisign itself prints them.

    Description: the key id is stored as 8 raw bytes and DISPLAYED as a
      little-endian unsigned 64-bit integer in 16 uppercase hex digits.
      That endianness is not a guess: it is asserted in the test suite
      against the hex minisign writes into a generated ``.pub`` file's
      untrusted comment line.
    Inputs: raw (bytes) - exactly 8 bytes.
    Output: str - 16 uppercase hex characters.
    Example: format_key_id(bytes.fromhex("97e6f484b02a525f"))
      -> "5F522AB084F4E697"
    """
    if len(raw) != _KEY_ID_BYTES:
        raise MinisignFormatError(
            f"key id must be {_KEY_ID_BYTES} bytes, got {len(raw)}"
        )
    return "%016X" % int.from_bytes(raw, "little")


def _decode_base64(text: str, *, what: str) -> bytes:
    """Decode one base64 line, refusing anything that is not base64.

    Description: the single decode site, so no caller can decode leniently
      by accident. ``validate=True`` means a stray character is a refusal
      rather than being skipped, and the exception carries the LABEL only -
      never the payload, which may be key material.
    Inputs: text (str) - one base64 line. what (str) - a label used in the
      error message, for example "public key".
    Output: bytes.
    Example: _decode_base64("aGk=", what="probe") -> b"hi"
    """
    try:
        return base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MinisignFormatError(f"{what} is not valid base64") from exc


@dataclass(frozen=True)
class PublicKey:
    """One minisign public key, parsed.

    - ``key_id``: 16 uppercase hex characters, the same string minisign
      prints in a ``.pub`` file's untrusted comment.
    - ``raw``: the 32 raw Ed25519 public key bytes, WITHOUT the algorithm
      marker or the key id in front of them.
    """

    key_id: str
    raw: bytes


@dataclass(frozen=True)
class Signature:
    """One minisign signature, parsed.

    - ``key_id``: 16 uppercase hex characters, the key that must have
      signed this.
    - ``sig``: the 64 raw Ed25519 signature bytes over the message (or
      over BLAKE2b-512 of it when ``prehashed``).
    - ``trusted_comment``: the comment text WITHOUT its
      ``trusted comment: `` prefix. Trustworthy only because
      ``global_sig`` covers it.
    - ``global_sig``: the 64 raw Ed25519 signature bytes over
      ``sig || trusted_comment``.
    - ``prehashed``: True for algorithm ``ED``, False for legacy ``Ed``.
    """

    key_id: str
    sig: bytes
    trusted_comment: str
    global_sig: bytes
    prehashed: bool

    @classmethod
    def from_index_fields(
        cls,
        key_id: str,
        sig_b64: str,
        trusted_comment: str,
        global_sig_b64: str,
    ) -> "Signature":
        """Build a Signature from the index's embedded ``sig`` block.

        Description: the catalog index carries a signature as four JSON
          fields rather than as a ``.minisig`` file, and the encoding is
          FIXED as follows, so the build job and this verifier cannot
          drift apart:

          - ``sig`` is line 2 of the ``.minisig`` VERBATIM: base64 of the
            full 74 byte blob, algorithm + key id + 64 byte signature.
          - ``gsig`` is line 4 of the ``.minisig`` VERBATIM: base64 of the
            RAW 64 byte global signature, with no algorithm or key id in
            front of it (minisign writes none there).
          - ``tc`` is the trusted comment TEXT, without the
            ``trusted comment: `` prefix.
          - ``key_id`` is the 16 uppercase hex rendering, and it must
            agree with the key id embedded in ``sig``. A disagreement is
            a malformed index, not a failed verification, so it raises.
        Inputs: key_id (str), sig_b64 (str), trusted_comment (str),
          global_sig_b64 (str).
        Output: Signature.
        Example: Signature.from_index_fields(
          "5F522AB084F4E697", sig_line, "timestamp:...", gsig_line).prehashed
        """
        signature = _signature_from_blobs(
            _decode_base64(sig_b64, what="signature"),
            trusted_comment,
            _decode_base64(global_sig_b64, what="global signature"),
        )
        wanted = key_id.strip().upper()
        if wanted != signature.key_id:
            raise MinisignFormatError(
                "index sig block key id does not match the signature it "
                f"carries: {wanted} vs {signature.key_id}"
            )
        return signature


def _signature_from_blobs(
    blob: bytes, trusted_comment: str, global_sig: bytes,
) -> Signature:
    """Assemble a Signature from already-decoded bytes.

    Description: the one place the 74 byte layout is read, shared by the
      ``.minisig`` parser and the index-field constructor so the two
      cannot diverge on a length check.
    Inputs: blob (bytes) - algorithm + key id + signature. trusted_comment
      (str). global_sig (bytes) - the raw 64 byte global signature.
    Output: Signature.
    Example: _signature_from_blobs(blob, "", gsig).prehashed -> True
    """
    if len(blob) != _SIGNATURE_BLOB_BYTES:
        raise MinisignFormatError(
            f"signature must be {_SIGNATURE_BLOB_BYTES} bytes, "
            f"got {len(blob)}"
        )
    if len(global_sig) != _ED25519_SIGNATURE_BYTES:
        raise MinisignFormatError(
            f"global signature must be {_ED25519_SIGNATURE_BYTES} bytes, "
            f"got {len(global_sig)}"
        )
    alg = blob[:2]
    if alg == ALG_PREHASHED:
        prehashed = True
    elif alg == ALG_LEGACY:
        prehashed = False
    else:
        raise MinisignFormatError(
            f"unknown signature algorithm: {alg!r}"
        )
    return Signature(
        key_id=format_key_id(blob[2:10]),
        sig=blob[10:],
        trusted_comment=trusted_comment,
        global_sig=global_sig,
        prehashed=prehashed,
    )


def _base64_line(text: str, *, what: str) -> str:
    """Pull the base64 line out of a key or signature file's text.

    Description: accepts either the two-line file form (untrusted comment
      then base64) or a bare base64 line, because a public key is also
      distributed as a single string (``minisign -P``). Blank lines are
      ignored; a comment line with nothing after it is a refusal.
    Inputs: text (str). what (str) - label for the error message.
    Output: str - the base64 line.
    Example: _base64_line("untrusted comment: x\\nAAAA\\n", what="k") -> "AAAA"
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise MinisignFormatError(f"{what} is empty")
    if lines[0].startswith(_UNTRUSTED_COMMENT_PREFIX):
        lines = lines[1:]
    if not lines:
        raise MinisignFormatError(f"{what} carries a comment and no key line")
    return lines[0]


def parse_public_key(text: str) -> PublicKey:
    """Parse a minisign public key.

    Description: accepts the ``.pub`` FILE content (untrusted comment line
      then one base64 line) or a bare base64 line as printed by
      ``minisign -G``. The algorithm marker on a public key is always
      ``Ed``; anything else is refused rather than assumed.
    Inputs: text (str).
    Output: PublicKey.
    Raises: MinisignFormatError on bad base64, a wrong length, or an
      unknown algorithm marker.
    Example: parse_public_key(pub_file_text).key_id -> "5F522AB084F4E697"
    """
    blob = _decode_base64(
        _base64_line(text, what="public key"), what="public key"
    )
    if len(blob) != _PUBLIC_KEY_BLOB_BYTES:
        raise MinisignFormatError(
            f"public key must be {_PUBLIC_KEY_BLOB_BYTES} bytes, "
            f"got {len(blob)}"
        )
    if blob[:2] != _PUBLIC_KEY_ALG:
        raise MinisignFormatError(
            f"unknown public key algorithm: {blob[:2]!r}"
        )
    return PublicKey(key_id=format_key_id(blob[2:10]), raw=blob[10:])


def parse_signature(text: str) -> Signature:
    """Parse a ``.minisig`` file.

    Description: the four lines are an untrusted comment, the base64
      signature blob, a ``trusted comment: `` line, and the base64 global
      signature. The trusted comment is taken VERBATIM after its prefix,
      with no stripping, because the global signature covers those exact
      bytes and a trimmed comment verifies as a forgery.
    Inputs: text (str) - the whole ``.minisig`` file.
    Output: Signature.
    Raises: MinisignFormatError when a line is missing, the trusted
      comment line is absent, base64 is malformed, a length is wrong, or
      the algorithm is unknown.
    Example: parse_signature(minisig_text).prehashed -> True
    """
    lines = text.splitlines()
    if len(lines) < 4:
        raise MinisignFormatError(
            f"signature file must have 4 lines, got {len(lines)}"
        )
    if not lines[2].startswith(_TRUSTED_COMMENT_PREFIX):
        raise MinisignFormatError(
            "signature file line 3 is not a trusted comment"
        )
    return _signature_from_blobs(
        _decode_base64(lines[1], what="signature"),
        lines[2][len(_TRUSTED_COMMENT_PREFIX):],
        _decode_base64(lines[3], what="global signature"),
    )


def _ed25519_ok(
    public_key: PublicKey, signature: bytes, payload: bytes,
) -> bool:
    """One Ed25519 verification, reduced to a bool.

    Description: ``cryptography`` signals failure by raising, and this is
      the only place that is turned into a return value, so no caller can
      forget the try block. A malformed public key is a FORMAT error and
      is raised, because "this key is 31 bytes" is not the same answer as
      "these bytes are not signed by this key".
    Inputs: public_key (PublicKey), signature (bytes), payload (bytes).
    Output: bool.
    Example: _ed25519_ok(key, sig, digest) -> True
    """
    if len(public_key.raw) != _ED25519_PUBLIC_KEY_BYTES:
        raise MinisignFormatError(
            f"public key must be {_ED25519_PUBLIC_KEY_BYTES} bytes, "
            f"got {len(public_key.raw)}"
        )
    if len(signature) != _ED25519_SIGNATURE_BYTES:
        raise MinisignFormatError(
            f"signature must be {_ED25519_SIGNATURE_BYTES} bytes, "
            f"got {len(signature)}"
        )
    try:
        Ed25519PublicKey.from_public_bytes(public_key.raw).verify(
            signature, payload
        )
    except InvalidSignature:
        return False
    return True


def _algorithm_name(prehashed: bool) -> str:
    """Name the minisign algorithm a prehash flag stands for.

    Description: exists so a mismatch is logged as ``ED`` against ``Ed``,
      the markers minisign itself writes, rather than as two booleans,
      which are indistinguishable to whoever reads the log line.
    Inputs: prehashed (bool).
    Output: str - "ED" for the prehashed construction, "Ed" for legacy.
    Example: _algorithm_name(True) -> "ED"
    """
    return (ALG_PREHASHED if prehashed else ALG_LEGACY).decode("ascii")


def verify(
    message: bytes,
    signature: Signature,
    public_key: PublicKey,
    *,
    expect_prehashed: bool,
) -> bool:
    """Whether this signature covers this message under this key, in the
    construction the caller named.

    Description: four checks, all of which must pass.

      1. The algorithm is the one the caller expects. The 2 byte marker
         is outside both signatures, so it is a claim to be checked and
         never a fact: a signature downgraded from ``ED`` to ``Ed``
         keeps all 64 of its signature bytes and would otherwise be
         checked against the raw message instead, returning True over
         bytes the publisher never signed. The refusal is a
         cryptographic False rather than a format error, because the
         bytes parsed perfectly well and the answer to the question the
         caller asked is no.
      2. The signature names the key it is being checked against. A key
         id mismatch is refused without touching the mathematics, because
         a signature by a DIFFERENT key is a different question from a
         bad signature and answering "false" for the right reason matters
         when the answer is read in a log.
      3. The message signature, over BLAKE2b-512 of the message when
         ``expect_prehashed`` and over the raw message when not. The
         transform is driven by the CALLER's expectation, never by the
         document's own marker.
      4. The GLOBAL signature, over the 64 signature bytes followed by the
         trusted comment encoded as UTF-8. This is never optional: a
         vector whose only mutation is the trusted comment must fail.
    Inputs: message (bytes) - the signed bytes. signature (Signature).
      public_key (PublicKey). expect_prehashed (bool) - KEYWORD ONLY and
      REQUIRED, with no default: True for the catalog's ``ED``
      construction, False for legacy ``Ed``.
    Output: bool - True only when all four checks pass. False on any
      cryptographic mismatch, including an algorithm that is not the
      expected one and a key id that is not this key's.
    Raises: MinisignFormatError when a length makes the check impossible.
    Example: verify(b"hello\\n", parse_signature(sig), parse_public_key(pub),
      expect_prehashed=True) -> True
    """
    if signature.prehashed != expect_prehashed:
        logger.warning(
            "minisign_algorithm_mismatch",
            expected_algorithm=_algorithm_name(expect_prehashed),
            actual_algorithm=_algorithm_name(signature.prehashed),
        )
        return False

    if signature.key_id != public_key.key_id:
        logger.warning(
            "catalog_minisign_key_id_mismatch",
            signature_key_id=signature.key_id,
            public_key_id=public_key.key_id,
        )
        return False

    payload = (
        hashlib.blake2b(message, digest_size=64).digest()
        if expect_prehashed
        else message
    )
    if not _ed25519_ok(public_key, signature.sig, payload):
        logger.warning(
            "catalog_minisign_message_signature_invalid",
            key_id=public_key.key_id,
            prehashed=signature.prehashed,
            message_bytes=len(message),
        )
        return False

    global_payload = signature.sig + signature.trusted_comment.encode("utf-8")
    if not _ed25519_ok(public_key, signature.global_sig, global_payload):
        logger.warning(
            "catalog_minisign_global_signature_invalid",
            key_id=public_key.key_id,
        )
        return False

    return True
