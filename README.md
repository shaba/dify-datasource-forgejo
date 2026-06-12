# Forgejo Repository Datasource

A Dify **online document** datasource that ingests Forgejo (and Gitea)
repositories, READMEs, issues and pull requests into a Dify Knowledge base.

Forgejo is a Gitea fork; both expose the same `<base_url>/api/v1` REST API, so
this plugin **works with Gitea too** — the shared `/api/v1` surface is used for
everything.

## Configuration

The plugin needs two credentials:

| Field | Description | Example |
| --- | --- | --- |
| **Server URL** (`base_url`) | Base URL of your Forgejo/Gitea server, **without** `/api/v1` | `https://example.com` |
| **Personal Access Token** (`api_token`) | A personal access token for your account (secret) | `…` |

Credentials are validated on save by calling `GET /api/v1/user`; an invalid URL
or token is rejected with a clear message (any `user:pass@` embedded in the URL
is redacted from error text).

### How to create a Forgejo/Gitea token

1. Sign in to your Forgejo/Gitea server.
2. Go to **Settings → Applications → Generate New Token**.
3. Give it a name and grant at least **read** scopes for repositories, issues and
   user (e.g. `read:repository`, `read:issue`, `read:user`; the exact scope names
   vary by server version).
4. Copy the generated token and paste it into the **Personal Access Token** field.

## What gets ingested

For the authenticated user's repositories (from `/api/v1/user/repos`, paginated),
the datasource exposes these pages:

- **Repository** (`repo:{owner}/{name}`) — repository metadata plus its README.
- **README file** (`file:{owner}/{name}:{path}`) — only when a README exists.
  Gitea/Forgejo has **no** `/readme` endpoint, so the plugin lists the repo root
  via `/repos/{owner}/{repo}/contents` and picks a README-named entry.
- **Issues** (`issue:{owner}/{name}:{number}`) — title, body and comments.
- **Pull requests** (`pr:{owner}/{name}:{number}`) — title, body and comments.

Each repository page yields a Markdown document; issues and PRs include their
comment threads.

### Listing caps

To keep page listings bounded, the datasource caps what it enumerates:

- at most **50 repositories**,
- at most **20 issues** per repository,
- at most **20 pull requests** per repository.

Repositories beyond the cap, and issues/PRs beyond their per-repo caps, are not
listed as pages (the caps are defined in `forgejo_client/pages.py:PageCap`).

Note that the per-repo issue and pull-request counts are also bounded by the
server's maximum page size: each is fetched in a single request, so a server
whose max page size is below the per-repo cap will return fewer items.

## Forgejo/Gitea API endpoints used

- `GET /api/v1/user` — authenticated user (workspace label, credential check)
- `GET /api/v1/user/repos` — the user's repositories (paginated)
- `GET /api/v1/repos/{owner}/{repo}` — repository metadata
- `GET /api/v1/repos/{owner}/{repo}/contents[/{path}]` — repo root listing,
  README detection and file contents
- `GET /api/v1/repos/{owner}/{repo}/issues?state=all&type=issues` — issues
- `GET /api/v1/repos/{owner}/{repo}/issues/{n}` and `/{n}/comments` — issue + comments
- `GET /api/v1/repos/{owner}/{repo}/pulls?state=all` and `/pulls/{n}` — pull requests
  (PR comments use the shared `/issues/{n}/comments` endpoint)

All requests authenticate with the `Authorization: token <api_token>` header.

## Credits

The plugin icon (`_assets/icon.svg`) is the Forgejo logo by
[Caesar Schinas](https://caesarschinas.com/), licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) and used
unmodified. See `_assets/icon.LICENSE`. The icon is licensed separately from the
plugin source code (Apache-2.0); per the ShareAlike term it remains under
CC BY-SA 4.0.

## License

Apache-2.0. Copyright 2026 Alexey Shabalin.
