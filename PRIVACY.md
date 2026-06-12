# Privacy Policy

The Forgejo Repository datasource plugin connects to a Forgejo or Gitea server
that **you** configure and reads data from it on your behalf.

## Data the plugin accesses

- Your account profile from `/api/v1/user` (login, display name, avatar) to label
  the workspace.
- The list of repositories your token can access (`/api/v1/user/repos`).
- Repository metadata, README files, issues and pull requests (with their
  comments) for the repositories you choose to ingest.

This data is fetched only when the Dify Knowledge base triggers a sync, and is
passed to Dify for indexing into your Knowledge base.

## Credentials

- The plugin stores the **server URL** and a **personal access token** you
  provide. The token is held by Dify as a secret credential.
- The token is sent only to the server URL you configured, in the
  `Authorization: token <api_token>` header over HTTPS (assuming an `https://`
  base URL).
- The plugin does not transmit your credentials or repository data to any third
  party other than your own Forgejo/Gitea server and your Dify instance.

## Data retention

The plugin itself stores nothing persistently. Ingested content lives in your
Dify Knowledge base under your control; remove it there to delete it.

## Contact

For questions, open an issue at
<https://github.com/shaba/dify-datasource-forgejo>.
