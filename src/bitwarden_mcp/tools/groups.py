"""Bitwarden vault group tools — create and list groups.

Tool naming convention: bitwarden_<action>_<resource>
"""

import json
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP

from ..api_client import BitwardenClient, BitwardenError

_NO_CREDENTIALS = (
    "Error: No Bitwarden credentials configured. Set BITWARDEN_CLIENT_ID/BITWARDEN_CLIENT_SECRET "
    "or use AUTH_MODE=gateway."
)


def register(mcp: FastMCP, client_factory: Callable[[], BitwardenClient | None]) -> None:
    @mcp.tool()
    async def bitwarden_list_groups() -> str:
        """List all vault groups in the Bitwarden organization."""
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            result = await client.get("/public/groups")
            return json.dumps(result, indent=2)
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_create_group(
        name: str,
        access_all: bool = False,
        external_id: str | None = None,
    ) -> str:
        """Create a new vault group in the Bitwarden organization.

        Use the returned group "id" with bitwarden_update_member_groups to invite
        members into it.

        Args:
            name: Name of the group to create.
            access_all: Whether the group gets access to all collections (default: False).
            external_id: Optional external identifier (e.g. from an HR/IdP system) for syncing.
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        body: dict = {"name": name, "accessAll": access_all}
        if external_id is not None:
            body["externalId"] = external_id
        try:
            result = await client.post("/public/groups", body)
            return json.dumps(result, indent=2)
        except BitwardenError as e:
            return f"Error: {e}"
