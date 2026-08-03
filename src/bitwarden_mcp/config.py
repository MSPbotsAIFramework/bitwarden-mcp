from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Transport
    mcp_transport: Literal["stdio", "http"] = "stdio"
    mcp_http_port: int = 8080
    mcp_http_host: str = "0.0.0.0"

    # Auth mode:
    # "gateway" — production/SOP-compliant: credentials from HTTP headers per request
    #             (no global state, no cached access_token).
    # "env"     — local dev only: shared organization API key from env vars.
    auth_mode: Literal["env", "gateway"] = "gateway"

    # Bitwarden organization API key (only required in env mode)
    bitwarden_client_id: str | None = None
    bitwarden_client_secret: str | None = None
    bitwarden_api_url: str = "https://api.bitwarden.com"
    bitwarden_identity_url: str = "https://identity.bitwarden.com"

    # Header names used to pass credentials/region in gateway mode.
    # The client must include the two required headers on every /mcp request;
    # the URL overrides are optional (EU Cloud / self-hosted tenants).
    bitwarden_client_id_header: str = "x-bitwarden-client-id"
    bitwarden_client_secret_header: str = "x-bitwarden-client-secret"
    bitwarden_api_url_header: str = "x-bitwarden-api-url"
    bitwarden_identity_url_header: str = "x-bitwarden-identity-url"

    @property
    def has_credentials(self) -> bool:
        """Returns True if the server can serve API calls.

        Gateway mode always returns True — each request carries its own credentials.
        Env mode requires both BITWARDEN_CLIENT_ID and BITWARDEN_CLIENT_SECRET to be set.
        """
        if self.auth_mode == "gateway":
            return True
        return bool(self.bitwarden_client_id and self.bitwarden_client_secret)


def get_settings() -> Settings:
    return Settings()
