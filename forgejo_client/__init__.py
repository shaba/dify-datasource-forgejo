"""Pure Forgejo/Gitea client + page-model core for the Dify datasource.

No ``dify_plugin`` dependency: this package speaks only HTTP and plain dicts, so
it can be unit-tested in isolation. Forgejo is a Gitea fork and both share the
``<base_url>/api/v1`` REST API, so this client works against either server.

The datasource and provider classes are thin adapters that import from here.
"""

from .errors import ApiError, ForgejoError, NotFound, redact_credentials
from .http import Fetch, default_fetch, request
from .pages import (
    DEFAULT_TEXT_EXTENSIONS,
    PageCap,
    build_pages,
    build_repo_file_pages,
    parse_extensions,
    parse_page_id,
)
from .repos import (
    decode_file_content,
    find_readme_entry,
    get_authenticated_user,
    get_contents,
    get_repo,
    get_tree,
    get_version,
    list_tree_blobs,
    list_user_repos,
)
from .content import (
    render_file,
    render_issue,
    render_pull,
    render_repo,
)
from .issues import (
    get_issue,
    get_issue_comments,
    get_pull,
    list_issues,
    list_pulls,
)
from .validate import validate

__all__ = [
    "ApiError",
    "ForgejoError",
    "NotFound",
    "redact_credentials",
    "Fetch",
    "default_fetch",
    "request",
    "DEFAULT_TEXT_EXTENSIONS",
    "PageCap",
    "build_pages",
    "build_repo_file_pages",
    "parse_extensions",
    "parse_page_id",
    "decode_file_content",
    "find_readme_entry",
    "get_authenticated_user",
    "get_contents",
    "get_repo",
    "get_tree",
    "get_version",
    "list_tree_blobs",
    "list_user_repos",
    "render_file",
    "render_issue",
    "render_pull",
    "render_repo",
    "get_issue",
    "get_issue_comments",
    "get_pull",
    "list_issues",
    "list_pulls",
    "validate",
]
