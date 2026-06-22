"""Repository, user and file-content endpoints.

Gitea/Forgejo has **no** dedicated ``/readme`` endpoint (unlike GitHub). To get a
README we list the repository root via ``/repos/{owner}/{repo}/contents`` and pick
the first entry whose name looks like a README, then fetch that file's contents.
"""

from __future__ import annotations

import base64
from typing import Any

from .http import Fetch, default_fetch, request, seg, seg_path

# Ordered preference for README detection in the repo root listing.
README_NAMES = (
    "README.md",
    "readme.md",
    "Readme.md",
    "README.rst",
    "README.txt",
    "README",
)


def get_version(base_url: str, *, token: str | None = None,
                fetch: Fetch = default_fetch, timeout: int = 30) -> dict[str, Any]:
    return request(base_url, "GET", "version", token=token, fetch=fetch, timeout=timeout)


def get_authenticated_user(base_url: str, *, token: str | None = None,
                           fetch: Fetch = default_fetch, timeout: int = 30) -> dict[str, Any]:
    return request(base_url, "GET", "user", token=token, fetch=fetch, timeout=timeout)


def get_repo(base_url: str, owner: str, repo: str, *, token: str | None = None,
             fetch: Fetch = default_fetch, timeout: int = 30) -> dict[str, Any]:
    return request(base_url, "GET", f"repos/{seg(owner)}/{seg(repo)}", token=token,
                   fetch=fetch, timeout=timeout)


def list_user_repos(base_url: str, *, max_repos: int = 50, token: str | None = None,
                    fetch: Fetch = default_fetch, timeout: int = 30) -> list[dict[str, Any]]:
    """Repositories of the token's user, paginated via ``/user/repos``.

    Forgejo/Gitea paginate with 1-based ``page`` and a ``limit`` per page (capped
    at the server's max). The server may clamp ``limit`` below our request, so we
    stop on an *empty* page rather than a short one (a short-page stop would
    truncate after page 1 on servers whose max page size is below ``per_page``).
    We still stop early once we reach ``max_repos``.
    """
    out: list[dict[str, Any]] = []
    page = 1
    per_page = 50
    while len(out) < max_repos:
        data = request(base_url, "GET", "user/repos",
                       params={"page": page, "limit": per_page},
                       token=token, fetch=fetch, timeout=timeout)
        batch = [r for r in (data or []) if isinstance(r, dict)]
        if not batch:
            break
        out.extend(batch)
        page += 1
    return out[:max_repos]


def get_contents(base_url: str, owner: str, repo: str, path: str = "", *,
                 ref: str | None = None, token: str | None = None,
                 fetch: Fetch = default_fetch, timeout: int = 30) -> Any:
    api_path = f"repos/{seg(owner)}/{seg(repo)}/contents"
    encoded = seg_path(path)
    if encoded:
        api_path = f"{api_path}/{encoded}"
    return request(base_url, "GET", api_path, params={"ref": ref}, token=token,
                   fetch=fetch, timeout=timeout)


def get_tree(base_url: str, owner: str, repo: str, ref: str, *,
             recursive: bool = True, page: int = 1, per_page: int = 1000,
             token: str | None = None, fetch: Fetch = default_fetch,
             timeout: int = 30) -> Any:
    """One page of the git-trees listing for ``ref`` (a branch name or commit sha).

    Forgejo/Gitea resolve a branch name in the ``{sha}`` slot, so the caller can
    pass the default branch directly.
    """
    return request(
        base_url, "GET",
        f"repos/{seg(owner)}/{seg(repo)}/git/trees/{seg(ref)}",
        params={"recursive": "true" if recursive else None,
                "page": page, "per_page": per_page},
        token=token, fetch=fetch, timeout=timeout,
    )


def list_tree_blobs(base_url: str, owner: str, repo: str, ref: str, *,
                    token: str | None = None, fetch: Fetch = default_fetch,
                    timeout: int = 30, per_page: int = 1000,
                    max_pages: int = 1000) -> list[dict[str, Any]]:
    """All blob (file) entries of ``ref`` via the recursive git-trees API.

    Gitea/Forgejo paginate the recursive tree and report ``total_count`` (and set
    ``truncated`` on the first page when there is more): we page until we've seen
    ``total_count`` entries or a page comes back empty, so a large tree (e.g. a man
    corpus with tens of thousands of files) isn't silently cut off at one page.
    Each returned entry carries ``path``, ``sha`` and ``size``.
    """
    blobs: list[dict[str, Any]] = []
    entries_seen = 0
    page = 1
    while page <= max_pages:
        data = get_tree(base_url, owner, repo, ref, recursive=True, page=page,
                        per_page=per_page, token=token, fetch=fetch, timeout=timeout)
        tree = data.get("tree") if isinstance(data, dict) else None
        batch = [e for e in (tree or []) if isinstance(e, dict)]
        if not batch:
            break
        entries_seen += len(batch)
        blobs.extend(e for e in batch if e.get("type") == "blob")
        total = data.get("total_count") if isinstance(data, dict) else None
        if total is None or entries_seen >= int(total):
            break
        page += 1
    return blobs


def find_readme_entry(listing: Any) -> dict[str, Any] | None:
    """Pick a README entry from a repo-root directory listing, or None."""
    if not isinstance(listing, list):
        return None
    by_name = {str(e.get("name") or ""): e for e in listing if isinstance(e, dict)}
    for name in README_NAMES:
        if name in by_name:
            return by_name[name]
    for name, entry in by_name.items():
        if name.lower().startswith("readme"):
            return entry
    return None


def decode_file_content(entry: dict[str, Any]) -> str | None:
    """Decode a base64 ``content`` field from a contents file entry.

    Returns ``None`` when the entry carries no decodable content (binary/large
    files come without a ``content`` field, so the caller can fall back to the
    download URL). A genuinely *empty* file has ``content == ""`` (a present but
    empty field), which decodes to ``""`` — distinct from absent content.
    """
    content = entry.get("content")
    if entry.get("encoding") == "base64" and content is not None:
        try:
            return base64.b64decode(content).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
    return None
