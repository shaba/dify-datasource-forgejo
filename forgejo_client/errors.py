"""Error types and credential-redaction helper for the Forgejo client.

``redact_credentials`` strips ``user:pass@`` userinfo from any URL embedded in an
error string before it reaches the LLM or end user. A misconfigured ``base_url``
could embed credentials, and requests' exception text often echoes the full URL;
redacting keeps that out of validation/diagnostic messages.
"""

from __future__ import annotations

import re


class ForgejoError(Exception):
    """Base class for Forgejo/Gitea client errors.

    Carries an optional ``status`` (the HTTP status code that triggered it, or
    ``None`` for transport/validation errors) so callers can decide which
    failures are tolerable (e.g. 404) versus fatal (401/403/5xx).
    """

    def __init__(self, *args: object, status: int | None = None) -> None:
        super().__init__(*args)
        self.status = status


class NotFound(ForgejoError):
    """Raised when the API returns 404."""


class ApiError(ForgejoError):
    """Raised on other non-2xx API responses or transport errors."""


# Matches scheme://user:pass@host userinfo; strip it before any error string
# reaches the LLM/end-user, in case base_url embeds credentials.
_USERINFO_RE = re.compile(r"(?P<scheme>[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/@\s]*@")


def redact_credentials(text: object) -> str:
    """Strip ``user:pass@`` userinfo from any URL embedded in a message."""
    return _USERINFO_RE.sub(r"\g<scheme>", str(text))
