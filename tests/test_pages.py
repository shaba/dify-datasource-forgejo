import re

import pytest

from forgejo_client import (
    ApiError,
    ForgejoError,
    build_pages,
    build_repo_file_pages,
    list_tree_blobs,
    parse_extensions,
    parse_page_id,
)
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


def test_parse_file_page_id_with_ref():
    p = parse_page_id("file:alice/proj@dev:docs/x.md")
    assert (p.kind, p.owner, p.repo, p.extra, p.ref) == (
        "file", "alice", "proj", "docs/x.md", "dev")


def test_parse_repo_page_id_with_ref():
    p = parse_page_id("repo:alice/proj@release-1.0")
    assert (p.repo, p.ref) == ("proj", "release-1.0")


def test_parse_file_page_id_without_ref_has_empty_ref():
    assert parse_page_id("file:alice/proj:README.md").ref == ""


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


# --- parse_extensions ------------------------------------------------------

def test_parse_extensions_defaults_when_empty():
    e = parse_extensions("")
    assert ".md" in e and ".txt" in e and ".rst" in e


def test_parse_extensions_adds_and_normalises():
    e = parse_extensions("PY, .Rb  man 1")
    assert {".py", ".rb", ".man", ".1"} <= e
    assert ".md" in e  # defaults retained when not replacing


def test_parse_extensions_replace_uses_only_given():
    assert parse_extensions(".py, md", replace=True) == frozenset({".py", ".md"})


def test_parse_extensions_replace_empty_matches_nothing():
    assert parse_extensions("", replace=True) == frozenset()


# --- list_tree_blobs (pagination + blob filtering) -------------------------

def test_list_tree_blobs_paginates_and_keeps_only_blobs():
    pages_data = {
        1: {"tree": [{"path": "a.md", "type": "blob", "sha": "1", "size": 1},
                     {"path": "sub", "type": "tree", "sha": "d"}],
            "total_count": 3, "truncated": True},
        2: {"tree": [{"path": "sub/b.md", "type": "blob", "sha": "2", "size": 1}],
            "total_count": 3},
    }
    calls = []

    def fetch(method, url, *, token=None, timeout=30):
        calls.append(url)
        m = re.search(r"[?&]page=(\d+)", url)
        page = int(m.group(1)) if m else 1
        return 200, pages_data.get(page, {"tree": []})

    blobs = list_tree_blobs(BASE, "alice", "proj", "main", fetch=fetch)
    assert [b["path"] for b in blobs] == ["a.md", "sub/b.md"]  # dir entry dropped
    assert len(calls) == 2  # paged until total_count reached


# --- build_repo_file_pages -------------------------------------------------

def _routes_repo_tree(tree):
    return {
        "repos/alice/proj/git/trees": (200, {"tree": tree, "total_count": len(tree)}),
        "repos/alice/proj": (200, {"full_name": "alice/proj", "name": "proj",
                                   "default_branch": "main"}),
    }


_TREE = [
    {"path": "README.md", "type": "blob", "sha": "sha-readme", "size": 10},
    {"path": "docs/guide.md", "type": "blob", "sha": "sha-guide", "size": 20},
    {"path": "src/main.py", "type": "blob", "sha": "sha-py", "size": 30},
    {"path": "docs", "type": "tree", "sha": "sha-dir"},
]


def test_build_repo_file_pages_filters_by_default_extensions_and_sets_sha():
    fetch, _ = make_fetch(_routes_repo_tree(_TREE))
    pages = build_repo_file_pages(BASE, "alice", "proj",
                                  extensions=parse_extensions(""), token="t", fetch=fetch)
    ids = [p["page_id"] for p in pages]
    assert "file:alice/proj:README.md" in ids
    assert "file:alice/proj:docs/guide.md" in ids
    assert not any("main.py" in i for i in ids)  # .py not in defaults
    page = next(p for p in pages if p["page_id"] == "file:alice/proj:README.md")
    assert page["last_edited_time"] == "sha-readme"   # blob sha is the change marker
    assert page["type"] == "file"
    assert page["metadata"]["ref"] == "main"


def test_build_repo_file_pages_custom_extension_adds_to_defaults():
    fetch, _ = make_fetch(_routes_repo_tree(_TREE))
    pages = build_repo_file_pages(BASE, "alice", "proj",
                                  extensions=parse_extensions("py"), token="t", fetch=fetch)
    ids = [p["page_id"] for p in pages]
    assert "file:alice/proj:src/main.py" in ids
    assert "file:alice/proj:README.md" in ids  # defaults still apply


def test_build_repo_file_pages_replace_extensions():
    fetch, _ = make_fetch(_routes_repo_tree(_TREE))
    pages = build_repo_file_pages(BASE, "alice", "proj",
                                  extensions=parse_extensions("py", replace=True),
                                  token="t", fetch=fetch)
    ids = [p["page_id"] for p in pages]
    assert ids == ["file:alice/proj:src/main.py"]


def test_build_repo_file_pages_path_prefix():
    fetch, _ = make_fetch(_routes_repo_tree(_TREE))
    pages = build_repo_file_pages(BASE, "alice", "proj", extensions=parse_extensions(""),
                                  path_prefix="docs", token="t", fetch=fetch)
    assert [p["page_id"] for p in pages] == ["file:alice/proj:docs/guide.md"]


def test_build_repo_file_pages_size_cap():
    fetch, _ = make_fetch(_routes_repo_tree(_TREE))
    pages = build_repo_file_pages(BASE, "alice", "proj", extensions=parse_extensions(""),
                                  max_file_bytes=15, token="t", fetch=fetch)
    # README.md (10) kept, docs/guide.md (20) dropped
    assert [p["page_id"] for p in pages] == ["file:alice/proj:README.md"]


def test_build_repo_file_pages_embeds_explicit_ref_in_page_id():
    fetch, _ = make_fetch(_routes_repo_tree(_TREE))
    pages = build_repo_file_pages(BASE, "alice", "proj", extensions=parse_extensions(""),
                                  ref="dev", token="t", fetch=fetch)
    ids = [p["page_id"] for p in pages]
    assert "file:alice/proj@dev:README.md" in ids
    page = next(p for p in pages if p["page_id"] == "file:alice/proj@dev:README.md")
    assert page["metadata"]["ref"] == "dev"


def test_build_repo_file_pages_issues_and_pulls_gated():
    routes = _routes_repo_tree(_TREE)
    # Full paths so they out-rank the shorter "repos/alice/proj" repo-info route.
    routes["repos/alice/proj/issues"] = (200, [{"number": 1, "title": "Bug", "state": "open",
                                                 "user": {"login": "bob"}, "updated_at": "x"}])
    routes["repos/alice/proj/pulls"] = (200, [{"number": 2, "title": "Feat", "state": "open",
                                               "user": {"login": "carol"}, "updated_at": "y"}])
    # Default: files only, no issues/PRs.
    fetch, _ = make_fetch(routes)
    pages = build_repo_file_pages(BASE, "alice", "proj",
                                  extensions=parse_extensions(""), token="t", fetch=fetch)
    assert not any(p["page_id"].startswith(("issue:", "pr:")) for p in pages)
    # Opt-in: include them.
    fetch, _ = make_fetch(routes)
    pages = build_repo_file_pages(BASE, "alice", "proj", extensions=parse_extensions(""),
                                  include_issues=True, include_pulls=True,
                                  token="t", fetch=fetch)
    ids = [p["page_id"] for p in pages]
    assert "issue:alice/proj:1" in ids and "pr:alice/proj:2" in ids
