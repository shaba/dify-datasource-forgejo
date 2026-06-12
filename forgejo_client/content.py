"""Markdown renderers for page content.

Each renderer turns API payloads into a single Markdown string suitable for
ingestion into a Knowledge base. They are pure functions over plain dicts, so the
datasource adapter only has to fetch and yield.
"""

from __future__ import annotations

from typing import Any

from .repos import decode_file_content


def render_repo(repo: dict[str, Any], readme_entry: dict[str, Any] | None,
                *, full_name: str) -> str:
    name = repo.get("name") or full_name
    lines = [f"# {name}", ""]
    lines.append(f"**Repository:** {repo.get('full_name') or full_name}")
    lines.append(f"**Description:** {repo.get('description') or 'No description'}")
    lines.append(f"**Language:** {repo.get('language') or 'Not specified'}")
    lines.append(f"**Stars:** {repo.get('stars_count', 0)}")
    lines.append(f"**Forks:** {repo.get('forks_count', 0)}")
    lines.append(f"**Open issues:** {repo.get('open_issues_count', 0)}")
    if repo.get("default_branch"):
        lines.append(f"**Default branch:** {repo.get('default_branch')}")
    lines.append(f"**Created:** {repo.get('created_at', '')}")
    lines.append(f"**Updated:** {repo.get('updated_at', '')}")
    if repo.get("html_url"):
        lines.append(f"**URL:** {repo.get('html_url')}")
    lines.append("")

    lines.append("## README")
    lines.append("")
    text = decode_file_content(readme_entry) if readme_entry else None
    if text is not None:
        lines.append(text)
    else:
        lines.append("No README file found.")
    return "\n".join(lines)


def render_file(entry: dict[str, Any], *, full_name: str, file_path: str) -> str:
    name = entry.get("name") or file_path
    text = decode_file_content(entry)
    if text is None:
        download = entry.get("download_url")
        body = "(binary or undecodable content)"
        if download:
            body += f"\nDownload: {download}"
    else:
        body = text
    if str(name).lower().endswith((".md", ".markdown", ".rst", ".txt")):
        return f"# {name}\n\n{body}"
    return f"# {full_name}/{file_path}\n\n{body}"


def render_issue(issue: dict[str, Any], comments: list[dict[str, Any]],
                 *, full_name: str) -> str:
    number = issue.get("number")
    lines = [f"# Issue #{number}: {issue.get('title') or ''}", ""]
    lines.append(f"**Repository:** {full_name}")
    lines.append(f"**Author:** {(issue.get('user') or {}).get('login', '')}")
    lines.append(f"**State:** {issue.get('state', '')}")
    lines.append(f"**Created:** {issue.get('created_at', '')}")
    lines.append(f"**Updated:** {issue.get('updated_at', '')}")
    if issue.get("html_url"):
        lines.append(f"**URL:** {issue.get('html_url')}")
    labels = [str((label_obj.get("name") or "")).strip()
              for label_obj in (issue.get("labels") or []) if isinstance(label_obj, dict)]
    labels = [label for label in labels if label]
    if labels:
        lines.append(f"**Labels:** {', '.join(labels)}")
    lines.append("")
    if issue.get("body"):
        lines.append("## Description")
        lines.append("")
        lines.append(str(issue.get("body")))
        lines.append("")
    _append_comments(lines, comments)
    return "\n".join(lines).rstrip() + "\n"


def render_pull(pull: dict[str, Any], comments: list[dict[str, Any]],
                *, full_name: str) -> str:
    number = pull.get("number")
    base = (pull.get("base") or {}).get("ref") or (pull.get("base") or {}).get("label") or ""
    head = (pull.get("head") or {}).get("ref") or (pull.get("head") or {}).get("label") or ""
    state = "merged" if pull.get("merged") else (pull.get("state") or "")
    lines = [f"# Pull Request #{number}: {pull.get('title') or ''}", ""]
    lines.append(f"**Repository:** {full_name}")
    lines.append(f"**Author:** {(pull.get('user') or {}).get('login', '')}")
    lines.append(f"**State:** {state}")
    lines.append(f"**Base branch:** {base}")
    lines.append(f"**Head branch:** {head}")
    lines.append(f"**Created:** {pull.get('created_at', '')}")
    lines.append(f"**Updated:** {pull.get('updated_at', '')}")
    if pull.get("html_url"):
        lines.append(f"**URL:** {pull.get('html_url')}")
    lines.append("")
    if pull.get("body"):
        lines.append("## Description")
        lines.append("")
        lines.append(str(pull.get("body")))
        lines.append("")
    _append_comments(lines, comments)
    return "\n".join(lines).rstrip() + "\n"


def _append_comments(lines: list[str], comments: list[dict[str, Any]]) -> None:
    if not comments:
        return
    lines.append("## Comments")
    lines.append("")
    for comment in comments:
        who = (comment.get("user") or {}).get("login", "")
        when = comment.get("created_at", "")
        lines.append(f"### {who} - {when}")
        lines.append("")
        lines.append(str(comment.get("body") or ""))
        lines.append("")
