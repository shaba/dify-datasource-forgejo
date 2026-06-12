import pytest
import requests

from forgejo_client import ApiError, ForgejoError, NotFound, request
from forgejo_client.errors import redact_credentials
from forgejo_client.http import build_url, default_fetch, seg_path
from tests.conftest import make_fetch

BASE = "https://git.example.com"


def test_build_url_appends_api_v1_and_params():
    url = build_url(BASE + "/", "user/repos", {"page": 1, "limit": 50, "empty": ""})
    assert url == "https://git.example.com/api/v1/user/repos?page=1&limit=50"


def test_seg_path_encodes_each_segment_preserving_slashes():
    assert seg_path("docs/My File.md") == "docs/My%20File.md"
    assert seg_path("/a/b/") == "a/b"
    assert seg_path("") == ""


def test_request_raises_notfound_on_404():
    fetch, _ = make_fetch({"/api/v1/user": (404, {"message": "gone"})})
    with pytest.raises(NotFound):
        request(BASE, "GET", "user", fetch=fetch)


def test_request_raises_apierror_on_401_with_clear_message():
    fetch, _ = make_fetch({"/api/v1/user": (401, {"message": "bad token"})})
    with pytest.raises(ApiError) as exc:
        request(BASE, "GET", "user", fetch=fetch)
    assert "401" in str(exc.value)


def test_request_returns_body_on_200():
    fetch, _ = make_fetch({"/api/v1/version": (200, {"version": "1.21.0"})})
    assert request(BASE, "GET", "version", fetch=fetch) == {"version": "1.21.0"}


def test_redact_credentials_strips_userinfo():
    msg = "failed for https://alice:secret@git.example.com/api/v1/user"
    assert "secret" not in redact_credentials(msg)
    assert "https://git.example.com" in redact_credentials(msg)


def test_request_redacts_userinfo_in_error_at_source():
    # base_url with embedded credentials; a 5xx error must not leak user:pass@.
    base = "https://alice:secret@git.example.com"
    fetch, _ = make_fetch({"/api/v1/user": (500, {"message": "boom"})})
    with pytest.raises(ApiError) as exc:
        request(base, "GET", "user", fetch=fetch)
    assert "secret" not in str(exc.value)


def test_default_fetch_rejects_non_http_scheme():
    # A misconfigured base_url targeting another transport must be rejected.
    with pytest.raises(ApiError) as exc:
        default_fetch("GET", "file:///etc/passwd")
    assert isinstance(exc.value, ForgejoError)
    assert "file" in str(exc.value)


def test_default_fetch_normalizes_transport_error_and_redacts(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError(
            "failed connecting to https://alice:secret@git.example.com/api/v1/user"
        )

    monkeypatch.setattr(requests, "request", boom)
    with pytest.raises(ApiError) as exc:
        default_fetch("GET", "https://alice:secret@git.example.com/api/v1/user",
                      token="t")
    # Normalised to a catchable ForgejoError and credentials redacted.
    assert isinstance(exc.value, ForgejoError)
    assert "secret" not in str(exc.value)


def test_default_fetch_passes_no_redirects_and_timeout(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"ok": True}

    def fake_request(method, url, **kwargs):
        captured.update(kwargs)
        return _Resp()

    monkeypatch.setattr(requests, "request", fake_request)
    status, data = default_fetch("GET", "https://git.example.com/api/v1/user",
                                 token="t", timeout=0)
    assert status == 200
    assert captured["allow_redirects"] is False
    # timeout falls back to 30 when a falsy value is passed.
    assert captured["timeout"] == 30
    assert captured["headers"]["Authorization"] == "token t"
