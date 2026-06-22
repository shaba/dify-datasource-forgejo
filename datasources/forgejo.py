from collections.abc import Generator, Mapping
from typing import Any

from dify_plugin.entities.datasource import (
    DatasourceGetPagesResponse,
    DatasourceMessage,
    GetOnlineDocumentPageContentRequest,
    OnlineDocumentInfo,
)
from dify_plugin.interfaces.datasource.online_document import OnlineDocumentDatasource

from forgejo_client import (
    ForgejoError,
    NotFound,
    redact_credentials,
    build_pages,
    build_repo_file_pages,
    find_readme_entry,
    get_contents,
    get_issue,
    get_issue_comments,
    get_pull,
    get_repo,
    get_authenticated_user,
    parse_extensions,
    parse_page_id,
    render_file,
    render_issue,
    render_pull,
    render_repo,
)


def _as_bool(value: Any) -> bool:
    """Datasource parameters may arrive as native bool or as strings."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _split_owner_repo(value: str) -> tuple[str, str]:
    cleaned = (value or "").strip().strip("/")
    if "/" not in cleaned:
        raise ValueError("Repository must be in 'owner/repo' form.")
    owner, name = cleaned.split("/", 1)
    if not owner or not name or "/" in name:
        raise ValueError("Repository must be in 'owner/repo' form.")
    return owner, name


def _redacted(exc: Exception) -> Exception:
    """Return a same-typed copy of ``exc`` with credentials stripped from its
    message, so nothing with embedded ``user:pass@`` reaches the SDK."""
    message = redact_credentials(exc)
    if isinstance(exc, ForgejoError):
        return type(exc)(message, status=exc.status)
    return type(exc)(message)


class ForgejoDataSource(OnlineDocumentDatasource):
    """Forgejo/Gitea online_document datasource (repos, READMEs, issues, PRs)."""

    def _creds(self) -> tuple[str, str]:
        credentials = self.runtime.credentials
        base_url = str(credentials.get("base_url") or "").strip()
        api_token = str(credentials.get("api_token") or "").strip()
        if not base_url:
            raise ValueError("Forgejo/Gitea base URL not found in credentials.")
        if not api_token:
            raise ValueError("API token not found in credentials.")
        return base_url, api_token

    def _get_pages(
        self, datasource_parameters: Mapping[str, Any]
    ) -> DatasourceGetPagesResponse:
        # Defense-in-depth: the client already redacts at the source, but if any
        # error still propagates out of the adapter (toward the SDK), re-raise it
        # with credentials stripped — mirroring the provider's redaction. The
        # error is re-raised, never swallowed.
        try:
            base_url, token = self._creds()

            user = get_authenticated_user(base_url, token=token)
            login = str(user.get("login") or "")
            workspace_name = f"{user.get('full_name') or login}'s Forgejo"
            workspace_icon = str(user.get("avatar_url") or "")
            workspace_id = str(user.get("id") or login)

            params = datasource_parameters or {}
            repository = str(params.get("repository") or "").strip()
            if repository:
                # File mode: ingest text files of one repository's tree.
                owner, name = _split_owner_repo(repository)
                extensions = parse_extensions(
                    str(params.get("file_extensions") or ""),
                    replace=_as_bool(params.get("extensions_replace")),
                )
                max_kb = _as_int(params.get("max_file_size_kb"), default=1024)
                max_bytes = max_kb * 1024 if max_kb > 0 else None
                pages = build_repo_file_pages(
                    base_url, owner, name,
                    extensions=extensions,
                    ref=str(params.get("ref") or "").strip() or None,
                    path_prefix=str(params.get("path_prefix") or "").strip(),
                    max_file_bytes=max_bytes,
                    include_issues=_as_bool(params.get("include_issues")),
                    include_pulls=_as_bool(params.get("include_pulls")),
                    token=token,
                )
            else:
                # Legacy mode: list the token user's repos (repo + README + issues + PRs).
                pages = build_pages(base_url, token=token)

            info = OnlineDocumentInfo(
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                workspace_icon=workspace_icon,
                pages=pages,
                total=len(pages),
            )
            return DatasourceGetPagesResponse(result=[info])
        except Exception as exc:
            raise _redacted(exc) from exc

    def _get_content(
        self, page: GetOnlineDocumentPageContentRequest
    ) -> Generator[DatasourceMessage, None, None]:
        # Wrap the whole generator body (the try/except spans the yields) so a
        # raise during iteration is redacted too. Re-raise, never swallow.
        try:
            base_url, token = self._creds()
            parsed = parse_page_id(page.page_id)
            full_name = f"{parsed.owner}/{parsed.repo}"

            if parsed.kind == "repo":
                content, title = self._repo_content(base_url, token, parsed.owner,
                                                     parsed.repo, full_name, parsed.ref)
                page_type = "repository"
            elif parsed.kind == "file":
                content, title = self._file_content(base_url, token, parsed.owner,
                                                     parsed.repo, parsed.extra, full_name,
                                                     parsed.ref)
                page_type = "file"
            elif parsed.kind == "issue":
                content, title = self._issue_content(base_url, token, parsed.owner,
                                                      parsed.repo, parsed.extra, full_name)
                page_type = "issue"
            elif parsed.kind == "pr":
                content, title = self._pull_content(base_url, token, parsed.owner,
                                                     parsed.repo, parsed.extra, full_name)
                page_type = "pull_request"
            else:  # pragma: no cover - parse_page_id already guards this
                raise ValueError(f"Unsupported page type: {page.page_id}")

            yield self.create_variable_message("page_id", page.page_id)
            yield self.create_variable_message("workspace_id", page.workspace_id)
            yield self.create_variable_message("content", content)
            yield self.create_variable_message("title", title)
            yield self.create_variable_message("repository", full_name)
            yield self.create_variable_message("type", page_type)
        except Exception as exc:
            raise _redacted(exc) from exc

    # --- per-kind fetch + render ------------------------------------------

    def _repo_content(self, base_url, token, owner, repo, full_name, ref=""):
        ref = ref or None
        info = get_repo(base_url, owner, repo, token=token)
        try:
            listing = get_contents(base_url, owner, repo, "", ref=ref, token=token)
            readme = find_readme_entry(listing)
            if readme is not None:
                readme = get_contents(base_url, owner, repo,
                                      str(readme.get("path") or readme.get("name") or ""),
                                      ref=ref, token=token)
        except NotFound:
            # A missing README is fine; auth/5xx/transport errors must propagate.
            readme = None
        return render_repo(info, readme, full_name=full_name), info.get("name") or full_name

    def _file_content(self, base_url, token, owner, repo, file_path, full_name, ref=""):
        entry = get_contents(base_url, owner, repo, file_path, ref=ref or None, token=token)
        if isinstance(entry, list):
            raise ValueError("Can only get content for files, not directories.")
        return (render_file(entry, full_name=full_name, file_path=file_path),
                entry.get("name") or file_path)

    def _issue_content(self, base_url, token, owner, repo, number, full_name):
        issue = get_issue(base_url, owner, repo, int(number), token=token)
        try:
            comments = get_issue_comments(base_url, owner, repo, int(number), token=token)
        except ForgejoError:
            comments = []
        title = f"Issue #{issue.get('number')}: {issue.get('title') or ''}"
        return render_issue(issue, comments, full_name=full_name), title

    def _pull_content(self, base_url, token, owner, repo, number, full_name):
        pull = get_pull(base_url, owner, repo, int(number), token=token)
        # PR comments share the /issues/{index}/comments endpoint in Gitea/Forgejo.
        try:
            comments = get_issue_comments(base_url, owner, repo, int(number), token=token)
        except ForgejoError:
            comments = []
        title = f"PR #{pull.get('number')}: {pull.get('title') or ''}"
        return render_pull(pull, comments, full_name=full_name), title
