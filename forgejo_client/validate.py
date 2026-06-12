"""Credential validation for the provider."""

from __future__ import annotations

from .errors import ApiError, ForgejoError, redact_credentials
from .http import Fetch, default_fetch
from .repos import get_authenticated_user


def validate(base_url: str, token: str, *,
             fetch: Fetch = default_fetch, timeout: int = 15) -> None:
    """Verify the server + token by calling ``/api/v1/user``.

    Raises ``ForgejoError`` on failure with any embedded ``user:pass@`` redacted.
    """
    base_url = (base_url or "").strip()
    if not base_url:
        raise ForgejoError("Forgejo/Gitea base URL is required.")
    if not (token or "").strip():
        raise ForgejoError("A personal access token is required.")
    try:
        get_authenticated_user(base_url, token=token, fetch=fetch, timeout=timeout)
    except ForgejoError as exc:
        raise ApiError(redact_credentials(exc)) from exc
    except Exception as exc:  # noqa: BLE001  (transport errors etc.)
        raise ApiError(redact_credentials(exc)) from exc
