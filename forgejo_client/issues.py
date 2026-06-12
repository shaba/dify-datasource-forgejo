"""Issue and pull-request read endpoints.

Note Forgejo/Gitea separate issues and PRs: ``/issues?type=issues`` excludes PRs,
and ``/pulls`` lists PRs. Comments for both live under the ``/issues`` namespace
(``/issues/{index}/comments``), because in Gitea a PR is an issue underneath.
"""

from __future__ import annotations

from typing import Any

from .http import Fetch, default_fetch, request, seg


def _repo_path(owner: str, repo: str) -> str:
    return f"repos/{seg(owner)}/{seg(repo)}"


def list_issues(base_url: str, owner: str, repo: str, *, state: str = "all",
                limit: int = 20, token: str | None = None,
                fetch: Fetch = default_fetch, timeout: int = 30) -> list[dict[str, Any]]:
    data = request(base_url, "GET", f"{_repo_path(owner, repo)}/issues",
                   params={"state": state, "type": "issues", "limit": limit},
                   token=token, fetch=fetch, timeout=timeout)
    return [i for i in (data or []) if isinstance(i, dict)]


def list_pulls(base_url: str, owner: str, repo: str, *, state: str = "all",
               limit: int = 20, token: str | None = None,
               fetch: Fetch = default_fetch, timeout: int = 30) -> list[dict[str, Any]]:
    data = request(base_url, "GET", f"{_repo_path(owner, repo)}/pulls",
                   params={"state": state, "limit": limit}, token=token,
                   fetch=fetch, timeout=timeout)
    return [p for p in (data or []) if isinstance(p, dict)]


def get_issue(base_url: str, owner: str, repo: str, index: int, *,
              token: str | None = None, fetch: Fetch = default_fetch,
              timeout: int = 30) -> dict[str, Any]:
    return request(base_url, "GET", f"{_repo_path(owner, repo)}/issues/{int(index)}",
                   token=token, fetch=fetch, timeout=timeout)


def get_pull(base_url: str, owner: str, repo: str, index: int, *,
             token: str | None = None, fetch: Fetch = default_fetch,
             timeout: int = 30) -> dict[str, Any]:
    return request(base_url, "GET", f"{_repo_path(owner, repo)}/pulls/{int(index)}",
                   token=token, fetch=fetch, timeout=timeout)


def get_issue_comments(base_url: str, owner: str, repo: str, index: int, *,
                       token: str | None = None, fetch: Fetch = default_fetch,
                       timeout: int = 30) -> list[dict[str, Any]]:
    data = request(base_url, "GET",
                   f"{_repo_path(owner, repo)}/issues/{int(index)}/comments",
                   token=token, fetch=fetch, timeout=timeout)
    return [c for c in (data or []) if isinstance(c, dict)]
