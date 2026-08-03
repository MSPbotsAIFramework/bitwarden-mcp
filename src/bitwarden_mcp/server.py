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


@dataclass(frozen=True)
class BitwardenCredentials:
    client_id: str
    client_secret: str
    api_url: str
    identity_url: str


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
        if creds is None:
            return None
        return BitwardenClient(
            creds.client_id, creds.client_secret, creds.api_url, creds.identity_url
        )

    if not settings.has_credentials:
        return None
    return BitwardenClient(
        settings.bitwarden_client_id,
        settings.bitwarden_client_secret,
        settings.bitwarden_api_url,
        settings.bitwarden_identity_url,
    )


class GatewayCredentialsMiddleware:
    """ASGI middleware for gateway mode.

    Reads the Bitwarden credential headers from each request and stores them in
    the contextvar for the duration of that request. Returns 401 if either of
    the two required headers is missing on /mcp requests. The two URL-override
    headers are optional and fall back to Bitwarden's US Cloud endpoints.
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

        required_headers = [
            self.settings.bitwarden_client_id_header,
            self.settings.bitwarden_client_secret_header,
        ]

        if not client_id or not client_secret:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Gateway mode requires all of: {', '.join(required_headers)}",
                    "required_headers": required_headers,
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_credentials_var.set(
            BitwardenCredentials(
                client_id=client_id,
                client_secret=client_secret,
                api_url=api_url,
                identity_url=identity_url,
            )
        )
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
                "  BITWARDEN_CLIENT_SECRET=...\n\n"
                "Or use gateway mode (per-request credentials):\n"
                "  AUTH_MODE=gateway\n"
                f"  Send headers: {settings.bitwarden_client_id_header}, "
                f"{settings.bitwarden_client_secret_header}"
            )

        print(
            "Warning: No Bitwarden credentials found. Only the diagnostic tool is available.",
            file=sys.stderr,
        )
        return mcp

    from .tools import groups, members

    members.register(mcp, client_factory)
    groups.register(mcp, client_factory)

    return mcp
