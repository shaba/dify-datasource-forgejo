from collections.abc import Mapping
from typing import Any

from dify_plugin.errors.tool import ToolProviderCredentialValidationError
from dify_plugin.interfaces.datasource import DatasourceProvider

from forgejo_client import ForgejoError, redact_credentials, validate


class ForgejoDatasourceProvider(DatasourceProvider):
    def _validate_credentials(self, credentials: Mapping[str, Any]) -> None:
        base_url = str(credentials.get("base_url") or "").strip()
        api_token = str(credentials.get("api_token") or "").strip()
        if not base_url:
            raise ToolProviderCredentialValidationError(
                "Forgejo/Gitea base URL is required."
            )
        if not api_token:
            raise ToolProviderCredentialValidationError(
                "A personal access token is required."
            )
        try:
            validate(base_url, api_token)
        except ForgejoError as exc:
            raise ToolProviderCredentialValidationError(
                redact_credentials(exc)
            ) from exc
