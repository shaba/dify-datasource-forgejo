import pytest

from forgejo_client import (
    ForgejoError,
    decode_file_content,
    find_readme_entry,
    list_user_repos,
    validate,
)
from forgejo_client.repos import get_contents
from tests.conftest import b64, make_fetch

BASE = "https://git.example.com"


def _repo(i: int) -> dict:
    return {"full_name": f"alice/repo{i}", "name": f"repo{i}",
            "owner": {"login": "alice"}, "updated_at": "2026-01-01T00:00:00Z"}


def test_list_user_repos_paginates_until_empty_page():
    page1 = [_repo(i) for i in range(50)]
    page2 = [_repo(i) for i in range(50, 60)]
    # Both pages share the /user/repos path; distinguish by the page= query.
    # The walk stops on an empty page, not a short one, so page2 (10 items < 50)
    # must NOT terminate the loop; page3 (empty) does.
    fetch, api = make_fetch({
        "page=1": (200, page1),
        "page=2": (200, page2),
        "page=3": (200, []),
    })
    repos = list_user_repos(BASE, max_repos=200, token="t", fetch=fetch)
    assert len(repos) == 60
    assert any("page=2" in c for c in api.calls)
    assert any("page=3" in c for c in api.calls)


def test_list_user_repos_paginates_when_server_page_size_below_per_page():
    # Server clamps each page to 10 items even though we request limit=50.
    # The walk must NOT stop on the first short page; it stops on an empty page.
    fetch, api = make_fetch({
        "page=1": (200, [_repo(i) for i in range(0, 10)]),
        "page=2": (200, [_repo(i) for i in range(10, 20)]),
        "page=3": (200, [_repo(i) for i in range(20, 25)]),
        "page=4": (200, []),
    })
    repos = list_user_repos(BASE, max_repos=100, token="t", fetch=fetch)
    assert len(repos) == 25
    assert any("page=4" in c for c in api.calls)


def test_list_user_repos_small_pages_respects_cap():
    # 10 items/page, cap 25 -> exactly 25, stops once the cap is reached.
    fetch, _ = make_fetch({
        "page=1": (200, [_repo(i) for i in range(0, 10)]),
        "page=2": (200, [_repo(i) for i in range(10, 20)]),
        "page=3": (200, [_repo(i) for i in range(20, 30)]),
    })
    repos = list_user_repos(BASE, max_repos=25, token="t", fetch=fetch)
    assert len(repos) == 25


def test_list_user_repos_respects_max_repos():
    fetch, _ = make_fetch({"page=1": (200, [_repo(i) for i in range(50)])})
    repos = list_user_repos(BASE, max_repos=10, token="t", fetch=fetch)
    assert len(repos) == 10


def test_find_readme_entry_prefers_canonical_name():
    listing = [
        {"name": "src", "type": "dir"},
        {"name": "README.rst", "type": "file", "path": "README.rst"},
        {"name": "README.md", "type": "file", "path": "README.md"},
    ]
    entry = find_readme_entry(listing)
    assert entry["name"] == "README.md"


def test_find_readme_entry_falls_back_to_readme_prefix():
    listing = [{"name": "Readme.adoc", "type": "file", "path": "Readme.adoc"}]
    assert find_readme_entry(listing)["name"] == "Readme.adoc"


def test_find_readme_entry_none_when_absent():
    assert find_readme_entry([{"name": "main.py", "type": "file"}]) is None
    assert find_readme_entry({"not": "a list"}) is None


def test_decode_file_content_base64():
    entry = {"encoding": "base64", "content": b64("hello world")}
    assert decode_file_content(entry) == "hello world"


def test_decode_file_content_non_base64_returns_none():
    assert decode_file_content({"encoding": "raw", "content": "x"}) is None


def test_decode_file_content_empty_file_is_empty_string_not_none():
    # An empty file has a present-but-empty content field; it must decode to ""
    # (distinct from absent content, which is None -> binary/download fallback).
    assert decode_file_content({"encoding": "base64", "content": b64("")}) == ""
    assert decode_file_content({"encoding": "base64", "content": ""}) == ""


def test_decode_file_content_absent_content_is_none():
    # Binary/large files come back without a content field -> None.
    assert decode_file_content({"encoding": "base64"}) is None


def test_get_contents_no_readme_endpoint_uses_contents():
    # Confirms README is fetched through /contents, never a /readme endpoint.
    fetch, api = make_fetch({
        "/contents/README.md": (200, {"name": "README.md", "encoding": "base64",
                                       "content": b64("# Hi")}),
    })
    entry = get_contents(BASE, "alice", "repo1", "README.md", token="t", fetch=fetch)
    assert decode_file_content(entry) == "# Hi"
    assert all("/readme" not in c for c in api.calls)


def test_validate_ok():
    fetch, _ = make_fetch({"/api/v1/user": (200, {"login": "alice"})})
    validate(BASE, "t", fetch=fetch)  # no raise


def test_validate_rejects_bad_token():
    fetch, _ = make_fetch({"/api/v1/user": (401, {"message": "nope"})})
    with pytest.raises(ForgejoError):
        validate(BASE, "t", fetch=fetch)


def test_validate_requires_url_and_token():
    fetch, _ = make_fetch({"/api/v1/user": (200, {"login": "alice"})})
    with pytest.raises(ForgejoError):
        validate("", "t", fetch=fetch)
    with pytest.raises(ForgejoError):
        validate(BASE, "", fetch=fetch)
