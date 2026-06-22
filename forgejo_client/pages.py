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

import re
from dataclasses import dataclass
from typing import Any, NamedTuple

from .errors import ForgejoError, NotFound
from .http import Fetch, default_fetch
from .issues import list_issues, list_pulls
from .repos import (
    find_readme_entry,
    get_contents,
    get_repo,
    list_tree_blobs,
    list_user_repos,
)

# Default file extensions ingested in repository file mode (see
# ``build_repo_file_pages``). Plain-text / lightweight-markup documents only; the
# user can add more (e.g. man sections ``.1``..``.8``) or replace this set via the
# datasource parameters. See ``parse_extensions``.
DEFAULT_TEXT_EXTENSIONS = frozenset({
    ".md", ".markdown", ".mdown", ".mkd",
    ".rst", ".txt", ".text",
    ".adoc", ".asciidoc", ".org", ".textile", ".rdoc", ".me",
})


def _norm_ext(token: str) -> str:
    """Normalise one extension token to leading-dot lowercase (``MD`` -> ``.md``)."""
    value = token.strip().lower()
    if not value:
        return ""
    return value if value.startswith(".") else f".{value}"


def parse_extensions(raw: str | None, *, replace: bool = False,
                     defaults: frozenset[str] = DEFAULT_TEXT_EXTENSIONS) -> frozenset[str]:
    """Build the effective extension allowlist from a user string.

    ``raw`` is comma/whitespace-separated (``"md, .txt  man 1"``); each token is
    normalised to leading-dot lowercase (``.md`` ``.txt`` ``.man`` ``.1``). With
    ``replace=False`` (default) the result is ``defaults`` **plus** the user's
    extensions; with ``replace=True`` it is **only** the user's (so an empty input
    yields an empty set that matches nothing). An empty ``raw`` keeps ``defaults``.
    """
    extra = frozenset(
        e for e in (_norm_ext(t) for t in re.split(r"[,\s]+", raw or "")) if e
    )
    return extra if replace else (frozenset(defaults) | extra)


def _matches_extension(path: str, extensions: frozenset[str]) -> bool:
    low = path.lower()
    return any(low.endswith(ext) for ext in extensions)


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
    ref: str = ""        # optional branch/tag/sha (file pages on a non-default ref)


def _peel_ref(value: str) -> tuple[str, str]:
    """Split an optional ``@ref`` suffix off the ``owner/repo`` part.

    ``owner/repo@branch`` -> ``("owner/repo", "branch")``; no ``@`` -> ``(value,
    "")``. Owners/repo names can't contain ``@``, and a git ref can't contain
    ``:`` (so the path part is never confused with a ref).
    """
    if "@" in value:
        repo_part, ref = value.rsplit("@", 1)
        return repo_part, ref
    return value, ""


def parse_page_id(page_id: str) -> ParsedPageId:
    """Split a page_id into its (kind, owner, repo, extra, ref) parts.

    ``repo:owner/name`` -> extra "".
    ``file:owner/name:path`` / ``issue:owner/name:N`` / ``pr:owner/name:N``.
    A file/repo page may carry a branch: ``file:owner/name@branch:path``.
    """
    if ":" not in page_id:
        raise ForgejoError(f"Malformed page_id: {page_id!r}")
    kind, rest = page_id.split(":", 1)
    if kind not in {"repo", "file", "issue", "pr"}:
        raise ForgejoError(f"Unsupported page type: {page_id!r}")
    if kind == "repo":
        repo_part, ref = _peel_ref(rest)
        owner, repo = _split_repo(repo_part, page_id)
        return ParsedPageId(kind, owner, repo, "", ref)
    if ":" not in rest:
        raise ForgejoError(f"Malformed page_id: {page_id!r}")
    repo_part, extra = rest.split(":", 1)
    repo_part, ref = _peel_ref(repo_part)
    owner, repo = _split_repo(repo_part, page_id)
    return ParsedPageId(kind, owner, repo, extra, ref)


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

        pages.extend(_issue_pages(base_url, owner, name, full, cap,
                                  token=token, fetch=fetch, timeout=timeout))
        pages.extend(_pull_pages(base_url, owner, name, full, cap,
                                 token=token, fetch=fetch, timeout=timeout))
    return pages


def _issue_pages(base_url: str, owner: str, name: str, full: str, cap: PageCap, *,
                 token: str | None, fetch: Fetch, timeout: int) -> list[dict[str, Any]]:
    """``issue:`` pages for one repo. ``NotFound`` -> none; auth/5xx propagate."""
    try:
        issues = list_issues(base_url, owner, name, state="all",
                             limit=cap.issues_per_repo, token=token,
                             fetch=fetch, timeout=timeout)
    except NotFound:
        return []
    out: list[dict[str, Any]] = []
    for issue in issues[: cap.issues_per_repo]:
        number = issue.get("number")
        if number is None:
            continue
        out.append({
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
    return out


def _pull_pages(base_url: str, owner: str, name: str, full: str, cap: PageCap, *,
                token: str | None, fetch: Fetch, timeout: int) -> list[dict[str, Any]]:
    """``pr:`` pages for one repo. ``NotFound`` -> none; auth/5xx propagate."""
    try:
        pulls = list_pulls(base_url, owner, name, state="all",
                           limit=cap.pulls_per_repo, token=token,
                           fetch=fetch, timeout=timeout)
    except NotFound:
        return []
    out: list[dict[str, Any]] = []
    for pr in pulls[: cap.pulls_per_repo]:
        number = pr.get("number")
        if number is None:
            continue
        out.append({
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
    return out


def build_repo_file_pages(base_url: str, owner: str, repo: str, *,
                          extensions: frozenset[str], ref: str | None = None,
                          path_prefix: str = "", max_file_bytes: int | None = None,
                          include_issues: bool = False, include_pulls: bool = False,
                          cap: PageCap | None = None, token: str | None = None,
                          fetch: Fetch = default_fetch, timeout: int = 30) -> list[dict[str, Any]]:
    """Pages for a *single* repository: one ``file:`` page per text file in the
    tree, filtered by ``extensions`` (see :func:`parse_extensions`), an optional
    ``path_prefix`` subtree, and an optional ``max_file_bytes`` size cap; plus
    optionally ``issue:``/``pr:`` pages.

    ``ref`` defaults to the repo's default branch; when an explicit ``ref`` is
    given it is embedded in the ``file:`` page_id (``file:owner/repo@ref:path``) so
    content is later fetched from the same branch.

    ``last_edited_time`` is each file's git **blob SHA** — a precise per-file change
    marker that is cheap (it comes straight from the tree listing). Note: Dify does
    not currently diff online_document pages on it, but it is correct provenance
    and future-proofs an incremental sync.
    """
    cap = cap or PageCap()
    info = get_repo(base_url, owner, repo, token=token, fetch=fetch, timeout=timeout)
    full = str(info.get("full_name") or f"{owner}/{repo}")
    name = str(info.get("name") or repo)
    explicit_ref = (ref or "").strip()
    effective_ref = explicit_ref or str(info.get("default_branch") or "").strip() or "HEAD"
    repo_ref = f"{full}@{explicit_ref}" if explicit_ref else full
    prefix = (path_prefix or "").strip().strip("/")

    blobs = list_tree_blobs(base_url, owner, repo, effective_ref, token=token,
                            fetch=fetch, timeout=timeout)
    pages: list[dict[str, Any]] = []
    for entry in blobs:
        path = str(entry.get("path") or "")
        if not path or not _matches_extension(path, extensions):
            continue
        if prefix and not (path == prefix or path.startswith(prefix + "/")):
            continue
        size = entry.get("size")
        if max_file_bytes is not None and isinstance(size, int) and size > max_file_bytes:
            continue
        pages.append({
            "page_id": f"file:{repo_ref}:{path}",
            "page_name": path,
            "type": "file",
            "last_edited_time": str(entry.get("sha") or ""),
            "url": "",
            "metadata": {
                "repository": full,
                "file_path": path,
                "ref": effective_ref,
                "blob_sha": str(entry.get("sha") or ""),
            },
        })

    if include_issues:
        pages.extend(_issue_pages(base_url, owner, name, full, cap,
                                  token=token, fetch=fetch, timeout=timeout))
    if include_pulls:
        pages.extend(_pull_pages(base_url, owner, name, full, cap,
                                 token=token, fetch=fetch, timeout=timeout))
    return pages
