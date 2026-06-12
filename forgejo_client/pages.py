"""Page model: the ``page_id`` scheme and the ``_get_pages`` listing builder.

Page-id scheme (mirrors the official GitHub datasource):

* ``repo:{owner}/{name}``              — repository metadata + README
* ``file:{owner}/{name}:{path}``       — a single file (we emit README only)
* ``issue:{owner}/{name}:{number}``    — one issue with comments
* ``pr:{owner}/{name}:{number}``       — one pull request with comments

``build_pages`` returns plain dicts compatible with the SDK ``OnlineDocumentPage``
model (fields: ``page_id``, ``page_name``, ``type``, ``last_edited_time``); extra
keys (``url``, ``metadata``) are tolerated/ignored by pydantic, matching the
GitHub reference's page dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple

from .errors import ForgejoError, NotFound
from .http import Fetch, default_fetch
from .issues import list_issues, list_pulls
from .repos import find_readme_entry, get_contents, list_user_repos


@dataclass(frozen=True)
class PageCap:
    """Caps to keep page listings bounded.

    Defaults: at most 50 repos, and per repo at most 20 issues and 20 PRs. With
    one ``repo`` page plus a possible ``file`` (README) page per repo, the worst
    case is roughly ``max_repos * (2 + 20 + 20)`` pages.
    """

    max_repos: int = 50
    issues_per_repo: int = 20
    pulls_per_repo: int = 20


class ParsedPageId(NamedTuple):
    kind: str            # "repo" | "file" | "issue" | "pr"
    owner: str
    repo: str
    extra: str           # file path, or issue/pr number; "" for repo


def parse_page_id(page_id: str) -> ParsedPageId:
    """Split a page_id into its (kind, owner, repo, extra) parts.

    ``repo:owner/name`` -> extra "".
    ``file:owner/name:path`` / ``issue:owner/name:N`` / ``pr:owner/name:N``.
    """
    if ":" not in page_id:
        raise ForgejoError(f"Malformed page_id: {page_id!r}")
    kind, rest = page_id.split(":", 1)
    if kind not in {"repo", "file", "issue", "pr"}:
        raise ForgejoError(f"Unsupported page type: {page_id!r}")
    if kind == "repo":
        owner, repo = _split_repo(rest, page_id)
        return ParsedPageId(kind, owner, repo, "")
    if ":" not in rest:
        raise ForgejoError(f"Malformed page_id: {page_id!r}")
    repo_part, extra = rest.split(":", 1)
    owner, repo = _split_repo(repo_part, page_id)
    return ParsedPageId(kind, owner, repo, extra)


def _split_repo(value: str, page_id: str) -> tuple[str, str]:
    if "/" not in value:
        raise ForgejoError(f"Malformed page_id (expected owner/repo): {page_id!r}")
    owner, repo = value.split("/", 1)
    if not owner or not repo:
        raise ForgejoError(f"Malformed page_id (empty owner/repo): {page_id!r}")
    return owner, repo


def _owner_name(repo: dict[str, Any]) -> tuple[str, str]:
    full = str(repo.get("full_name") or "").strip()
    if full and "/" in full:
        owner, name = full.split("/", 1)
        return owner, name
    owner = str((repo.get("owner") or {}).get("login") or "").strip()
    name = str(repo.get("name") or "").strip()
    return owner, name


def build_pages(base_url: str, *, token: str | None, cap: PageCap | None = None,
                fetch: Fetch = default_fetch, timeout: int = 30) -> list[dict[str, Any]]:
    """Build the flat page list for one workspace.

    Per repository we emit: a ``repo:`` page, a ``file:`` README page (only if a
    README exists), and up to ``cap.issues_per_repo`` ``issue:`` pages and
    ``cap.pulls_per_repo`` ``pr:`` pages. Only ``NotFound`` (404) sub-fetch
    failures are swallowed — a repo with genuinely no README/issues/PRs still
    lists fine. Auth (401/403) and server (5xx)/transport errors propagate so a
    scope/auth problem fails loudly instead of silently truncating the listing.
    """
    cap = cap or PageCap()
    repos = list_user_repos(base_url, max_repos=cap.max_repos, token=token,
                            fetch=fetch, timeout=timeout)
    pages: list[dict[str, Any]] = []
    for repo in repos:
        owner, name = _owner_name(repo)
        if not owner or not name:
            continue
        full = f"{owner}/{name}"
        updated = str(repo.get("updated_at") or "")

        pages.append({
            "page_id": f"repo:{full}",
            "page_name": name,
            "type": "repository",
            "last_edited_time": updated,
            "url": repo.get("html_url", ""),
            "metadata": {
                "description": repo.get("description", ""),
                "language": repo.get("language", ""),
                "stars": repo.get("stars_count", 0),
                "private": repo.get("private", False),
            },
        })

        # README (no dedicated endpoint: list root, detect a README file).
        try:
            listing = get_contents(base_url, owner, name, "", token=token,
                                   fetch=fetch, timeout=timeout)
            readme = find_readme_entry(listing)
        except NotFound:
            readme = None
        if readme is not None:
            readme_path = str(readme.get("path") or readme.get("name") or "README.md")
            pages.append({
                "page_id": f"file:{full}:{readme_path}",
                "page_name": f"{name} - {readme.get('name') or 'README'}",
                "type": "file",
                "last_edited_time": updated,
                "url": readme.get("html_url", ""),
                "metadata": {"repository": full, "file_path": readme_path},
            })

        # Issues (PRs excluded by type=issues in the client).
        try:
            issues = list_issues(base_url, owner, name, state="all",
                                 limit=cap.issues_per_repo, token=token,
                                 fetch=fetch, timeout=timeout)
        except NotFound:
            issues = []
        for issue in issues[: cap.issues_per_repo]:
            number = issue.get("number")
            if number is None:
                continue
            pages.append({
                "page_id": f"issue:{full}:{number}",
                "page_name": f"Issue #{number}: {issue.get('title') or ''}",
                "type": "issue",
                "last_edited_time": str(issue.get("updated_at") or ""),
                "url": issue.get("html_url", ""),
                "metadata": {
                    "repository": full,
                    "issue_number": number,
                    "state": issue.get("state", ""),
                    "author": (issue.get("user") or {}).get("login", ""),
                },
            })

        # Pull requests.
        try:
            pulls = list_pulls(base_url, owner, name, state="all",
                               limit=cap.pulls_per_repo, token=token,
                               fetch=fetch, timeout=timeout)
        except NotFound:
            pulls = []
        for pr in pulls[: cap.pulls_per_repo]:
            number = pr.get("number")
            if number is None:
                continue
            pages.append({
                "page_id": f"pr:{full}:{number}",
                "page_name": f"PR #{number}: {pr.get('title') or ''}",
                "type": "pull_request",
                "last_edited_time": str(pr.get("updated_at") or ""),
                "url": pr.get("html_url", ""),
                "metadata": {
                    "repository": full,
                    "pr_number": number,
                    "state": pr.get("state", ""),
                    "author": (pr.get("user") or {}).get("login", ""),
                },
            })
    return pages
