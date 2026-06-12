from forgejo_client import render_file, render_issue, render_pull, render_repo
from tests.conftest import b64


def test_render_repo_includes_metadata_and_readme():
    repo = {"name": "proj", "full_name": "alice/proj", "description": "A tool",
            "language": "Python", "stars_count": 5, "forks_count": 2,
            "open_issues_count": 1, "default_branch": "main",
            "html_url": "https://git.example.com/alice/proj"}
    readme = {"encoding": "base64", "content": b64("# Hello\nbody")}
    out = render_repo(repo, readme, full_name="alice/proj")
    assert "# proj" in out
    assert "**Language:** Python" in out
    assert "## README" in out
    assert "# Hello" in out


def test_render_repo_without_readme():
    repo = {"name": "proj", "full_name": "alice/proj"}
    out = render_repo(repo, None, full_name="alice/proj")
    assert "No README file found." in out


def test_render_file_markdown_gets_title():
    entry = {"name": "README.md", "encoding": "base64", "content": b64("body text")}
    out = render_file(entry, full_name="alice/proj", file_path="README.md")
    assert out.startswith("# README.md")
    assert "body text" in out


def test_render_file_binary_shows_download():
    entry = {"name": "logo.png", "download_url": "https://git.example.com/logo.png"}
    out = render_file(entry, full_name="alice/proj", file_path="logo.png")
    assert "binary or undecodable" in out
    assert "Download:" in out


def test_render_file_empty_file_is_blank_not_binary():
    # content == "" is a genuinely empty file: render an empty body, not the
    # "(binary or undecodable content)" fallback.
    entry = {"name": "empty.txt", "encoding": "base64", "content": b64("")}
    out = render_file(entry, full_name="alice/proj", file_path="empty.txt")
    assert "binary or undecodable" not in out
    assert "Download:" not in out
    assert out == "# empty.txt\n\n"


def test_render_issue_with_comments():
    issue = {"number": 3, "title": "Crash", "state": "open",
             "user": {"login": "bob"}, "created_at": "c", "updated_at": "u",
             "html_url": "https://git.example.com/alice/proj/issues/3",
             "body": "It crashes", "labels": [{"name": "bug"}]}
    comments = [{"user": {"login": "carol"}, "created_at": "d", "body": "me too"}]
    out = render_issue(issue, comments, full_name="alice/proj")
    assert "# Issue #3: Crash" in out
    assert "**Labels:** bug" in out
    assert "## Comments" in out
    assert "me too" in out


def test_render_pull_shows_branches_and_merged_state():
    pull = {"number": 9, "title": "Add X", "merged": True, "state": "closed",
            "user": {"login": "dan"}, "created_at": "c", "updated_at": "u",
            "base": {"ref": "main"}, "head": {"ref": "feature"},
            "body": "implements X"}
    out = render_pull(pull, [], full_name="alice/proj")
    assert "# Pull Request #9: Add X" in out
    assert "**State:** merged" in out
    assert "**Base branch:** main" in out
    assert "**Head branch:** feature" in out
