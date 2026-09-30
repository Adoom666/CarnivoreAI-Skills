"""The refusal every kind rule raises, shared so the rules import one thing.

The status and code are the hosted validators' own (``hosted/catalog/api``
in the product repository), so a submission refused there and a release
refused here name the same reason. The shared vectors file holds the two
to the same answers.
"""

from __future__ import annotations

#: The longest theme or skill description accepted, in characters.
MAX_DESCRIPTION_CHARS = 1024


class KindRefused(Exception):
    """One folder broke a kind's rules.

    Attributes:
        status: the HTTP status the hosted validator answers with.
        code: the stable machine readable reason.
        detail: a sentence naming what was wrong.

    Example: KindRefused(409, "plugin_not_safe", "hooks/x").code
    """

    def __init__(self, status: int, code: str, detail: str) -> None:
        """Record the status, the code and the sentence.

        :param status: the HTTP status.
        :param code: the stable code.
        :param detail: the human sentence.
        """
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail
