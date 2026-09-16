"""What number this index gets, and why the job would rather fail than guess.

THE SERIAL IS A ROLLBACK CONTROL, NOT A BUILD NUMBER. The app remembers the
highest serial it has ever verified under a given index key and refuses
anything lower, which is what stops somebody who can serve bytes from
replaying an older, good, signed index carrying a version that has since
been revoked. That only works if the serial only ever goes up.

SO THE NEW SERIAL IS COUNTED FROM THE LIVE ONE, AND THE LIVE ONE IS ONLY
BELIEVED WHEN ITS SIGNATURE CHECKS OUT. Three outcomes, and the third is the
whole point of the file:

- The live index is UNREACHABLE or 404: nothing has ever been published, so
  the serial is ``max(1, min_serial)`` from ``catalog.yml``.
- The live index is reachable AND verifies under the pinned index key: the
  serial is the live one plus one.
- The live index is reachable and does NOT verify: THE BUILD FAILS. It is
  tempting to treat this as "no live index" and start again from the floor,
  and that is exactly the move an attacker wants, because a lower serial
  republished under the real key resets every client's floor. A build that
  cannot read its own predecessor stops and asks for a human.

NO KEY PINNED IS THE SAME REFUSAL. Until ``publishers/_index.json`` carries
the index public key, a reachable live index cannot be checked at all, so it
is refused for the same reason. An unreachable one is still the first deploy.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional, Tuple

from .minisign_verify import MinisignFormatError, PublicKey, parse_signature, verify

#: How long each of the two fetches may take.
FETCH_TIMEOUT_SECONDS = 20

#: The most index bytes this will read. An index far larger than this is
#: either not our index or is something trying to exhaust the runner.
MAX_INDEX_BYTES = 8 * 1024 * 1024

#: The serial the very first published index gets when catalog.yml asks for
#: nothing higher. Zero is reserved for "no index has ever verified".
FIRST_SERIAL = 1

#: Appended to the index URL to find the detached signature beside it.
SIGNATURE_SUFFIX = ".minisig"


class SerialRefused(Exception):
    """The live index could not be read well enough to count from it."""


@dataclass(frozen=True)
class SerialDecision:
    """The serial this build will use, and how it was arrived at.

    - ``serial``: the number to stamp on the new index.
    - ``outcome``: ``"first-deploy"`` or ``"live-verified"``.
    - ``live_serial``: what the live index said, when there was one.
    - ``detail``: one line for the job log, naming what actually happened.
    - ``live_document``: the live index document, and ONLY when its
      signature verified under the pinned index key. The review step
      reuses an existing review from it so a user reinstalling a version
      sees the same words, and reusing from an UNVERIFIED document would
      let whoever serves the CDN inject a clean looking review. So this
      is None on every path except the verified one.
    """

    serial: int
    outcome: str
    live_serial: Optional[int]
    detail: str
    live_document: Optional[dict] = None


def _fetch(url: str) -> Optional[bytes]:
    """GET one URL, or return None when it is absent or unreachable.

    :param url: the absolute https URL.
    :returns: the body, or None on a 404 or a transport failure.
    :raises SerialRefused: on any other HTTP status, or an oversized body.

    A 404 and a connection failure are the SAME answer here, "there is
    nothing published yet", and both are safe because neither can be
    produced by an attacker to lower a serial: a lower serial needs a
    signature, and a missing index produces none. Every other status is
    refused, because a 500 or a 403 from the CDN is not evidence that the
    index does not exist.
    """
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_INDEX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise SerialRefused(
            f"{url} answered HTTP {exc.code}, which is neither a published "
            f"index nor an absent one"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError):
        return None
    if len(body) > MAX_INDEX_BYTES:
        raise SerialRefused(f"{url} is larger than {MAX_INDEX_BYTES} bytes")
    return body


def _live_serial(index_bytes: bytes) -> Tuple[int, dict]:
    """Read the serial out of an index whose signature already verified.

    :param index_bytes: the verified index document.
    :returns: its serial and the parsed document.
    :raises SerialRefused: when the document has no usable serial.

    Called only after the signature check, so this is parsing something
    the index key already vouched for.
    """
    try:
        document = json.loads(index_bytes)
    except json.JSONDecodeError as exc:
        raise SerialRefused(f"the live index is not JSON: {exc}") from exc
    serial = document.get("serial") if isinstance(document, dict) else None
    if not isinstance(serial, int) or isinstance(serial, bool) or serial < 0:
        raise SerialRefused("the live index carries no non negative integer serial")
    return serial, document


def decide_serial(
    *, catalog_url: str, index_key: Optional[PublicKey], min_serial: int,
) -> SerialDecision:
    """Work out the serial for this build, or refuse to build.

    Description: fetches the live index and its detached signature, and
      applies the three outcomes in the module docstring. Both files must
      be absent for this to count as a first deploy: an index served
      without its signature is a signature somebody removed, and that is
      refused rather than treated as nothing.
    Inputs: catalog_url (str) - the live index URL, empty when there is no
      hosted catalog yet. index_key (PublicKey or None) - the pinned index
      key. min_serial (int) - the floor from catalog.yml.
    Output: SerialDecision.
    Raises: SerialRefused when a live index exists that cannot be verified.
    Example: decide_serial(catalog_url="", index_key=None, min_serial=0)
      -> SerialDecision(serial=1, outcome="first-deploy", ...)
    """
    if not catalog_url:
        return SerialDecision(
            serial=max(FIRST_SERIAL, min_serial),
            outcome="first-deploy",
            live_serial=None,
            detail="no catalog url is configured, so there is no live index to count from",
            live_document=None,
        )

    index_bytes = _fetch(catalog_url)
    signature_text = _fetch(catalog_url + SIGNATURE_SUFFIX)

    if index_bytes is None and signature_text is None:
        return SerialDecision(
            serial=max(FIRST_SERIAL, min_serial),
            outcome="first-deploy",
            live_serial=None,
            detail=f"{catalog_url} and its signature are both absent, so this is the first deploy",
            live_document=None,
        )
    if index_bytes is None or signature_text is None:
        missing = "the index" if index_bytes is None else "its signature"
        raise SerialRefused(
            f"{catalog_url}: {missing} is absent while the other is served. "
            f"Half a published index is not a first deploy and the serial "
            f"will not be guessed from it."
        )
    if index_key is None:
        raise SerialRefused(
            f"{catalog_url} is serving an index but publishers/_index.json pins "
            f"no index key, so it cannot be verified. Paste the index public "
            f"key before building again; the serial will not be guessed."
        )

    try:
        signature = parse_signature(signature_text.decode("utf-8"))
        ok = verify(index_bytes, signature, index_key, expect_prehashed=True)
    except (MinisignFormatError, UnicodeDecodeError) as exc:
        raise SerialRefused(
            f"{catalog_url}: the live signature could not be checked: {exc}"
        ) from exc
    if not ok:
        raise SerialRefused(
            f"{catalog_url}: the live index does not verify under the pinned "
            f"index key. The serial will not be counted from an index this "
            f"job cannot trust."
        )

    live, document = _live_serial(index_bytes)
    return SerialDecision(
        serial=max(live + 1, min_serial),
        outcome="live-verified",
        live_serial=live,
        detail=f"the live index verified at serial {live}, so this one is {max(live + 1, min_serial)}",
        live_document=document,
    )


def decision_lines(decision: SerialDecision) -> Tuple[str, ...]:
    """Render the decision for the job log.

    :param decision: what decide_serial returned.
    :returns: the lines to print, so a reader of a green run can still see
        which of the three outcomes happened.

    Example: decision_lines(d)[0] -> "serial: 1 (first-deploy)"
    """
    return (
        f"serial: {decision.serial} ({decision.outcome})",
        f"reason: {decision.detail}",
    )
