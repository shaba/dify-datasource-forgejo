"""Minimal HTTP layer for the Forgejo/Gitea ``/api/v1`` REST API.

The single ``request`` entry point is parameterised on a ``Fetch`` callable so
unit tests can inject a fake transport and never touch the network. The default
transport uses ``requests`` with the Forgejo token auth header
(``Authorization: token <api_token>``).
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote, urlencode, urlsplit

import requests

from .errors import ApiError, NotFound, redact_credentials

# A Fetch performs one HTTP call and returns (status_code, parsed_body).
# parsed_body is the decoded JSON, or the raw text if the body is not JSON.
Fetch = Callable[..., "tuple[int, Any]"]

USER_AGENT = "dify-datasource-forgejo/0.0.1"


def default_fetch(
    method: str,
    url: str,
    *,
    token: str | None = None,
    timeout: int = 30,
) -> tuple[int, Any]:
    # Reject non-HTTP(S) transports so a misconfigured base_url (e.g. file://,
    # ftp://) can't be coerced into targeting another transport. The message is
    # redacted in case the URL embeds user:pass@ userinfo.
    scheme = urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise ApiError(redact_credentials(f"Unsupported URL scheme {scheme!r}: {url}"))
    headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"token {token}"
    # allow_redirects=False: the /api/v1 endpoints shouldn't redirect, and a
    # redirect would forward the Authorization: token header to another host.
    # timeout is always set (default 30s) so a hung server can't block forever.
    try:
        response = requests.request(
            method, url, headers=headers, timeout=timeout or 30,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        # Normalise transport errors (ConnectionError/Timeout/SSLError) into a
        # ForgejoError catchable by callers, with credentials redacted.
        raise ApiError(redact_credentials(f"Forgejo API request failed: {exc}")) from exc
    try:
        data = response.json()
    except ValueError:
        data = response.text
    return response.status_code, data


def api_base(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/api/v1"


def seg(value: Any) -> str:
    """Percent-encode a single path segment (owner / repo / username)."""
    return quote(str(value), safe="")


def seg_path(value: Any) -> str:
    """Percent-encode a multi-segment path, preserving ``/`` separators."""
    stripped = str(value).strip("/")
    if not stripped:
        return ""
    return "/".join(seg(part) for part in stripped.split("/"))


def build_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    url = f"{api_base(base_url)}/{path.lstrip('/')}"
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if clean:
            url = f"{url}?{urlencode(clean)}"
    return url


def request(
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    params: dict[str, Any] | None = None,
    fetch: Fetch = default_fetch,
    timeout: int = 30,
) -> Any:
    url = build_url(base_url, path, params)
    status, data = fetch(method, url, token=token, timeout=timeout)
    if status == 404:
        raise NotFound(_message(data) or f"Not found: {path}", status=404)
    if status == 401:
        raise ApiError("Invalid Forgejo API token (401 Unauthorized).", status=401)
    if status >= 400:
        # The message can embed the API URL and the response body, either of
        # which may contain user:pass@ from a misconfigured base_url; redact at
        # the source so credentials never reach the user/LLM via ingestion.
        raise ApiError(
            redact_credentials(f"Forgejo API error {status}: {_message(data) or data}"),
            status=status,
        )
    return data


def _message(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or "").strip()
    if isinstance(data, str):
        return data.strip()
    return ""
