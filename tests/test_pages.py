import pytest

from forgejo_client import ApiError, ForgejoError, build_pages, parse_page_id
from forgejo_client.pages import PageCap
from tests.conftest import make_fetch

BASE = "https://git.example.com"


# --- parse_page_id ---------------------------------------------------------

def test_parse_repo_page_id():
    p = parse_page_id("repo:alice/proj")
    assert (p.kind, p.owner, p.repo, p.extra) == ("repo", "alice", "proj", "")


def test_parse_file_page_id_keeps_path_with_colons_and_slashes():
    p = parse_page_id("file:alice/proj:docs/README.md")
    assert (p.kind, p.owner, p.repo, p.extra) == ("file", "alice", "proj", "docs/README.md")


def test_parse_issue_and_pr_page_ids():
    assert parse_page_id("issue:alice/proj:42").extra == "42"
    assert parse_page_id("pr:alice/proj:7").kind == "pr"


def test_parse_rejects_unknown_kind_and_malformed():
    with pytest.raises(ForgejoError):
        parse_page_id("wiki:alice/proj")
    with pytest.raises(ForgejoError):
        parse_page_id("repo:noslash")
    with pytest.raises(ForgejoError):
        parse_page_id("noseparator")


# --- build_pages -----------------------------------------------------------

def _routes_one_repo():
    return {
        "page=1": (200, [{"full_name": "alice/proj", "name": "proj",
                          "owner": {"login": "alice"},
                          "updated_at": "2026-01-01T00:00:00Z",
                          "html_url": "https://git.example.com/alice/proj"}]),
        "page=2": (200, []),  # empty page terminates the repo page-walk
        "/contents/": (404, {"message": "no file"}),  # specific paths -> not used here
        "/contents": (200, [{"name": "README.md", "type": "file", "path": "README.md"}]),
        "/issues": (200, [{"number": 1, "title": "Bug", "state": "open",
                           "user": {"login": "bob"}, "updated_at": "x"}]),
        "/pulls": (200, [{"number": 2, "title": "Feature", "state": "open",
                          "user": {"login": "carol"}, "updated_at": "y"}]),
    }


def test_build_pages_emits_repo_readme_issue_and_pr():
    fetch, _ = make_fetch(_routes_one_repo())
    pages = build_pages(BASE, token="t", fetch=fetch)
    ids = [p["page_id"] for p in pages]
    assert "repo:alice/proj" in ids
    assert "file:alice/proj:README.md" in ids
    assert "issue:alice/proj:1" in ids
    assert "pr:alice/proj:2" in ids
    repo_page = next(p for p in pages if p["page_id"] == "repo:alice/proj")
    assert repo_page["type"] == "repository"
    assert repo_page["page_name"] == "proj"


def test_build_pages_skips_readme_when_absent():
    routes = _routes_one_repo()
    routes["/contents"] = (200, [{"name": "main.py", "type": "file", "path": "main.py"}])
    fetch, _ = make_fetch(routes)
    pages = build_pages(BASE, token="t", fetch=fetch)
    assert not any(p["page_id"].startswith("file:") for p in pages)


def test_build_pages_swallows_notfound_subfetch_errors():
    # A 404 on issues/pulls means "this repo has none" -> swallowed, repo lists.
    routes = _routes_one_repo()
    routes["/issues"] = (404, {"message": "no issues"})
    routes["/pulls"] = (404, {"message": "no pulls"})
    fetch, _ = make_fetch(routes)
    pages = build_pages(BASE, token="t", fetch=fetch)
    assert "repo:alice/proj" in [p["page_id"] for p in pages]
    assert not any(p["page_id"].startswith(("issue:", "pr:")) for p in pages)


def test_build_pages_does_not_swallow_auth_error_on_subfetch():
    # A 401/403 on a sub-fetch is an auth/scope failure: it must propagate so the
    # knowledge base is not silently truncated.
    for status in (401, 403):
        routes = _routes_one_repo()
        routes["/issues"] = (status, {"message": "forbidden"})
        fetch, _ = make_fetch(routes)
        with pytest.raises(ApiError):
            build_pages(BASE, token="t", fetch=fetch)


def test_build_pages_does_not_swallow_server_error_on_subfetch():
    # A 5xx on a sub-fetch must also propagate.
    routes = _routes_one_repo()
    routes["/pulls"] = (500, {"message": "boom"})
    fetch, _ = make_fetch(routes)
    with pytest.raises(ApiError):
        build_pages(BASE, token="t", fetch=fetch)


def test_build_pages_respects_caps():
    routes = {
        "page=1": (200, [{"full_name": "alice/proj", "name": "proj",
                          "owner": {"login": "alice"}, "updated_at": "z"}]),
        "page=2": (200, []),
        "/contents": (404, {"message": "none"}),
        "/issues": (200, [{"number": i, "title": f"i{i}", "user": {"login": "u"},
                           "state": "open", "updated_at": "x"} for i in range(40)]),
        "/pulls": (200, []),
    }
    fetch, _ = make_fetch(routes)
    cap = PageCap(max_repos=50, issues_per_repo=5, pulls_per_repo=5)
    pages = build_pages(BASE, token="t", cap=cap, fetch=fetch)
    issue_pages = [p for p in pages if p["page_id"].startswith("issue:")]
    assert len(issue_pages) == 5
