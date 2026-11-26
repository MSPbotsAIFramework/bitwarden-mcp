import contextvars
import sys
from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import BitwardenClient
from .config import Settings
from .send_client import BitwardenSendClient, SendCredentials


@dataclass(frozen=True)
class BitwardenCredentials:
    """Per-request credentials. Either set may be absent (a tenant can configure only one)."""

    api_url: str
    identity_url: str
    client_id: str | None = None
    client_secret: str | None = None
    user_client_id: str | None = None
    user_client_secret: str | None = None
    master_password: str | None = None

    @property
    def has_org(self) -> bool:
        return bool(self.client_id and self.client_secret)

    @property
    def has_send(self) -> bool:
        return bool(self.user_client_id and self.user_client_secret and self.master_password)


# ─────────────────────────────────────────────────────────────────────────────
# Per-request credentials contextvar for gateway mode.
# GatewayCredentialsMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent requests are isolated.
# ─────────────────────────────────────────────────────────────────────────────
_gateway_credentials_var: contextvars.ContextVar[BitwardenCredentials | None] = (
    contextvars.ContextVar("bitwarden_gateway_credentials", default=None)
)


def get_client_from_context(settings: Settings) -> BitwardenClient | None:
    """Resolve the active BitwardenClient for the current request context."""
    if settings.auth_mode == "gateway":
        creds = _gateway_credentials_var.get()
        if creds is None or not creds.has_org:
            return None
        return BitwardenClient(
            creds.client_id, creds.client_secret, creds.api_url, creds.identity_url
        )

    if not settings.has_org_credentials:
        return None
    return BitwardenClient(
        settings.bitwarden_client_id,
        settings.bitwarden_client_secret,
        settings.bitwarden_api_url,
        settings.bitwarden_identity_url,
    )


def get_send_client_from_context(settings: Settings) -> BitwardenSendClient | None:
    """Resolve the BitwardenSendClient for the current request, or None if the Send
    credentials (user API key + master password) are incomplete."""
    if settings.auth_mode == "gateway":
        creds = _gateway_credentials_var.get()
        if creds is None or not creds.has_send:
            return None
        return BitwardenSendClient(
            SendCredentials(
                creds.user_client_id,
                creds.user_client_secret,
                creds.master_password,
                creds.api_url,
                creds.identity_url,
            )
        )

    if not settings.has_send_credentials:
        return None
    return BitwardenSendClient(
        SendCredentials(
            settings.bitwarden_user_client_id,
            settings.bitwarden_user_client_secret,
            settings.bitwarden_master_password,
            settings.bitwarden_api_url,
            settings.bitwarden_identity_url,
        )
    )


class GatewayCredentialsMiddleware:
    """ASGI middleware for gateway mode.

    Reads the Bitwarden credential headers from each request and stores them in
    the contextvar for the duration of that request. Returns 401 unless a complete
    organization pair or a complete Send triple is present on /mcp requests; each
    tool reports the headers it is missing. The two URL-override headers are optional
    and fall back to Bitwarden's US Cloud endpoints.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        # Header lookup is case-insensitive in Starlette
        client_id = request.headers.get(self.settings.bitwarden_client_id_header.lower())
        client_secret = request.headers.get(self.settings.bitwarden_client_secret_header.lower())
        api_url = request.headers.get(
            self.settings.bitwarden_api_url_header.lower(), self.settings.bitwarden_api_url
        )
        identity_url = request.headers.get(
            self.settings.bitwarden_identity_url_header.lower(),
            self.settings.bitwarden_identity_url,
        )

        creds = BitwardenCredentials(
            api_url=api_url,
            identity_url=identity_url,
            client_id=client_id,
            client_secret=client_secret,
            user_client_id=request.headers.get(self.settings.bitwarden_user_client_id_header.lower()),
            user_client_secret=request.headers.get(
                self.settings.bitwarden_user_client_secret_header.lower()
            ),
            master_password=request.headers.get(
                self.settings.bitwarden_master_password_header.lower()
            ),
        )

        if not creds.has_org and not creds.has_send:
            org, send_h = self.settings.org_headers, self.settings.send_headers
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": (
                        f"Gateway mode requires all of: {', '.join(org)} "
                        f"(organization tools) or all of: {', '.join(send_h)} (Send tool)"
                    ),
                    "required_headers": {"organization": org, "send": send_h},
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_credentials_var.set(creds)
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_credentials_var.reset(ctx_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all tools."""
    # DNS-rebinding protection is disabled because the container runs behind
    # mcp-gateway on an internal Docker network and is never publicly exposed.
    mcp = FastMCP(
        name="bitwarden-mcp",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    def client_factory() -> BitwardenClient | None:
        return get_client_from_context(settings)

    def send_client_factory() -> BitwardenSendClient | None:
        return get_send_client_from_context(settings)

    if not settings.has_credentials:
        # Graceful degradation: register only a diagnostic tool when no credentials are available.
        @mcp.tool()
        async def bitwarden_test_connection() -> str:
            """Test Bitwarden Public API connection.

            Shows configuration requirements when credentials are missing.
            """
            return (
                "Error: Missing Bitwarden credentials.\n\n"
                "Set the required environment variables:\n"
                "  BITWARDEN_CLIENT_ID=...\n"
                "  BITWARDEN_CLIENT_SECRET=...\n"
                "  (Send tool: BITWARDEN_USER_CLIENT_ID, BITWARDEN_USER_CLIENT_SECRET, "
                "BITWARDEN_MASTER_PASSWORD)\n\n"
                "Or use gateway mode (per-request credentials):\n"
                "  AUTH_MODE=gateway\n"
                f"  Organization headers: {', '.join(settings.org_headers)}\n"
                f"  Send headers: {', '.join(settings.send_headers)}"
            )

        print(
            "Warning: No Bitwarden credentials found. Only the diagnostic tool is available.",
            file=sys.stderr,
        )
        return mcp

    from .tools import groups, members, sends

    members.register(mcp, client_factory)
    groups.register(mcp, client_factory)
    sends.register(mcp, send_client_factory, settings.send_headers)

    return mcp
