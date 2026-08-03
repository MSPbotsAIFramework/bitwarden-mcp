"""Bitwarden organization member tools — invite, list, reinvite, remove, and group assignment.

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
    async def bitwarden_list_members() -> str:
        """List all members of the Bitwarden organization.

        Each member's "status" field is 0=Invited, 1=Accepted, 2=Confirmed.
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            result = await client.get("/public/members")
            return json.dumps(result, indent=2)
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_get_member(member_id: str) -> str:
        """Get a single organization member's details.

        Args:
            member_id: The member's UUID (see bitwarden_list_members).
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            result = await client.get(f"/public/members/{member_id}")
            return json.dumps(result, indent=2)
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_invite_member(
        email: str,
        type: int = 2,
        access_all: bool = False,
        external_id: str | None = None,
    ) -> str:
        """Invite a new member to the Bitwarden organization by email.

        The invited member receives an email invitation; their "status" starts
        at 0 (Invited) until they accept it. To grant access to specific vault
        groups, follow up with bitwarden_update_member_groups once the invite
        succeeds (the returned member "id" is needed for that call).

        Args:
            email: Email address to invite.
            type: Organization role — 0=Owner, 1=Admin, 2=User (default, i.e. regular
                Member), 3=Manager, 4=Custom (requires the organization to have
                custom permissions enabled).
            access_all: Whether the member gets access to all collections (default: False).
            external_id: Optional external identifier (e.g. from an HR/IdP system) for syncing.
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        body: dict = {"email": email, "type": type, "accessAll": access_all}
        if external_id is not None:
            body["externalId"] = external_id
        try:
            result = await client.post("/public/members", body)
            return json.dumps(result, indent=2)
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_reinvite_member(member_id: str) -> str:
        """Resend the invitation email to a member who hasn't accepted it yet.

        Args:
            member_id: The member's UUID (see bitwarden_list_members).
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            await client.post(f"/public/members/{member_id}/reinvite")
            return f"Reinvite sent to member {member_id}."
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_remove_member(member_id: str) -> str:
        """Remove a member from the Bitwarden organization.

        Args:
            member_id: The member's UUID (see bitwarden_list_members).
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            await client.delete(f"/public/members/{member_id}")
            return f"Member {member_id} removed from the organization."
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_list_member_groups(member_id: str) -> str:
        """List the vault group IDs a member currently belongs to.

        Args:
            member_id: The member's UUID (see bitwarden_list_members).
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            result = await client.get(f"/public/members/{member_id}/group-ids")
            return json.dumps(result, indent=2)
        except BitwardenError as e:
            return f"Error: {e}"

    @mcp.tool()
    async def bitwarden_update_member_groups(member_id: str, group_ids: list[str]) -> str:
        """Set which vault groups a member belongs to — this is the "group invitation" action.

        IMPORTANT: this REPLACES the member's entire group list, it does not append.
        To add the member to a group without losing existing memberships, first call
        bitwarden_list_member_groups, merge the new group id(s) into that list, then
        pass the full merged list here.

        Args:
            member_id: The member's UUID (see bitwarden_list_members).
            group_ids: Full list of vault group UUIDs the member should belong to
                after this call (see bitwarden_list_groups for available group IDs).
        """
        client = client_factory()
        if client is None:
            return _NO_CREDENTIALS
        try:
            await client.put(f"/public/members/{member_id}/group-ids", {"groupIds": group_ids})
            return f"Member {member_id} is now in groups: {group_ids}"
        except BitwardenError as e:
            return f"Error: {e}"
