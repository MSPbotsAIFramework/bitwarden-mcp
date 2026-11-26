"""Bitwarden Send tool (PRD-22483): create a text Send and return its share link."""

import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..send_client import BitwardenSendClient, SendError

MAX_SECRET_LENGTH = 1000
MAX_NAME_LENGTH = 100
EXPIRATION_RANGE = (1, 720)
ACCESS_COUNT_RANGE = (1, 100)


def _invalid(field: str, message: str) -> str:
    return json.dumps({"error": "invalid_argument", "field": field, "message": message})


def _validate(secret: str, expiration_hours: int, max_access_count: int, name: str) -> str | None:
    if not secret or len(secret) > MAX_SECRET_LENGTH:
        return _invalid("secret", f"must be 1..{MAX_SECRET_LENGTH} characters")
    if not EXPIRATION_RANGE[0] <= expiration_hours <= EXPIRATION_RANGE[1]:
        return _invalid("expiration_hours", "must be between 1 and 720")
    if not ACCESS_COUNT_RANGE[0] <= max_access_count <= ACCESS_COUNT_RANGE[1]:
        return _invalid("max_access_count", "must be between 1 and 100")
    if len(name) > MAX_NAME_LENGTH:
        return _invalid("name", f"must be at most {MAX_NAME_LENGTH} characters")
    return None


def register(
    mcp: FastMCP,
    send_client_factory: Callable[[], BitwardenSendClient | None],
    required_headers: list[str],
) -> None:
    @mcp.tool()
    async def bitwarden_create_text_send(
        secret: str,
        expiration_hours: int = 24,
        max_access_count: int = 1,
        name: str = "Credentials",
        hide_text: bool = True,
    ) -> str:
        """Create a text Bitwarden Send in the client's own Bitwarden and return its share link.

        The text is encrypted end to end; the connector never stores or logs it. Each call
        creates a new Send, so do not retry after a success.

        Args:
            secret: The text to deliver (1..1000 characters).
            expiration_hours: Hours until the link stops working (1..720, default 24).
            max_access_count: How many times the link can be opened (1..100, default 1).
            name: Label shown in the sending account's Send list (max 100 characters).
            hide_text: The recipient must click to reveal the text (default true).
        """
        problem = _validate(secret, expiration_hours, max_access_count, name)
        if problem:
            return problem
        client = send_client_factory()
        if client is None:
            return json.dumps(
                {"error": "missing_credentials", "required_headers": required_headers}
            )
        try:
            result = await client.create_text_send(
                secret, name, expiration_hours, max_access_count, hide_text
            )
        except SendError as e:
            return json.dumps(e.payload)
        return json.dumps(result)
