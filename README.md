# bitwarden-mcp

Bitwarden MCP server for Claude — exposes the Bitwarden **Public API**'s organization
**member and vault group management** as MCP tools, focused on **inviting members and
assigning them to vault groups** ("vault group invitation").

**Tech stack:** Python 3.12 + uv + FastMCP (Starlette/uvicorn)

Related requirement: PRD-15544 ([Self-built MCP] MSPbots Integration - Bitwarden). See the full research in
`vendor-mcp-template/prd/Bitwarden.md`.

**Out of scope:** Bitwarden Send (temporary secure credential links) is intentionally not
implemented. The Public API does not allow management of individual vault items, and Send
requires a stateful, unlocked local `bw` CLI vault — incompatible with this service's
stateless, multi-tenant gateway model.

<div align="center">

## MSPbots Connector

**The MCP Gateway built for MSPs: visible, controlled, and your data stays where it belongs.**

[**Get started at connect.mspbots.ai →**](https://connect.mspbots.ai)

</div>

---

MSPbots Connector gives your AI clients one MCP URL to reach your entire MSP stack (RMM, PSA, documentation, security, finance), and gives you control over who can call which tool and a record of everything that was called.

**Hosted service: [connect.mspbots.ai](https://connect.mspbots.ai)** · Free to use.

### Why Connector

![MSPbots Connector](https://stgoss.mspbots.ai/files/mcp/mspbots-mcp.png)

| | |
|---|---|
| **Visible** | Every tool call is logged: who, which vendor, when. Usage dashboard, CSV export, SIEM streaming. |
| **Controlled** | Role-based, per-tool allowlist. Deny by default. |
| **Protected** | Credentials encrypted per record. AI clients never see your vendor passwords or tokens. |
| **MSP-native** | Built for the MSP stack only: RMM, PSA, documentation, security, finance. |

### Quick start

1. **Sign up** at [connect.mspbots.ai](https://connect.mspbots.ai).
2. **Connect your vendors.** Pick from 150+ connectors and authorize each one on the vendor's own page, or bring your own API keys. No extra vendor accounts needed.
3. **Set access.** Create roles and decide which tools each role may call. Nothing is allowed until you allow it.
4. **Add your MCP URL to your AI client.** Copy the URL from your Connector dashboard into Claude, ChatGPT, Cursor, VS Code, Gemini, Codex, or any MCP-capable client.
5. **Ask your AI to do real work**, and watch every call appear in the audit log.

### Features

**Unified gateway**
- One MCP URL for all your AI clients
- 150+ connectors across the MSP stack
- Custom MCP servers supported, free
- Authorization happens on each vendor's own page; the AI never sees passwords or tokens
- Bring your own credentials: use the vendor API keys you already have
- Multiple accounts per app; connect once, reuse across AI clients
- Tool search: finds the right action for the task
- One sign-in; vendor credentials are injected behind the scenes and OAuth tokens refresh automatically

**Visibility**
- Audit log for every tool call (who, which vendor, when)
- Usage dashboard: call volume, top vendors, error rate, per-user activity
- Export audit logs to CSV, or stream to Loki, Graylog, or LogScale (SIEM)
- Optional recording of tool arguments and result summaries (off by default, enabled per organization)

**Control**
- Per-role, per-tool allowlist, deny by default
- owner / admin / member roles
- SCIM provisioning with Entra ID, Okta, JumpCloud, and Google Workspace

**Security**
- Credentials encrypted one record at a time (AES-256-GCM, per-record key)
- AI clients authenticate with OAuth 2.1 + PKCE
- Vendor responses are scanned for prompt-injection patterns and returned as structured data. This is one layer of defense, not a guarantee against every attack.
- Static egress IP for customer firewall and API allowlisting

### Pricing

**Free.**

Links: [connect.mspbots.ai](https://connect.mspbots.ai) · [mspbots.ai](https://mspbots.ai)

---

## Quick Start

```bash
cd bitwarden-mcp
uv sync

# stdio mode (for Claude Desktop / CLI), single shared credential set from env
BITWARDEN_CLIENT_ID=organization.xxxx BITWARDEN_CLIENT_SECRET=xxxx uv run bitwarden-mcp
```

## Authentication

This service is **stateless**: it never stores or persists Bitwarden credentials.
Credentials are either supplied once via environment variables (local dev, `AUTH_MODE=env`),
or per-request via HTTP headers (`AUTH_MODE=gateway`, production).

Bitwarden's Public API uses **OAuth2 Client Credentials** (`grant_type=client_credentials`,
`scope=api.organization`). On every tool call, this service exchanges the caller's
`client_id` + `client_secret` for a short-lived `access_token` (~1h TTL) and uses it
immediately — the token is **not cached** across requests, in order to fully comply with the
"no persisted credentials" requirement. This adds one extra Identity round trip per call.

### Gateway mode HTTP headers (`AUTH_MODE=gateway`)

| Header | Type | Required | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `x-bitwarden-client-id` | string | Yes | None | None | Client ID of the organization API Key (Admin Console → Settings → Organization info) | `organization.3b1f...` |
| `x-bitwarden-client-secret` | string | Yes | None | None | The corresponding Client Secret, used only within this request to exchange for an access_token; not persisted and not logged | `AbCdEf123...` |
| `x-bitwarden-identity-url` | string | Optional | `https://identity.bitwarden.com` | None | Identity Token Endpoint; for EU Cloud pass `https://identity.bitwarden.eu`, for self-hosted pass `https://your.domain.com/identity` | `https://identity.bitwarden.eu` |
| `x-bitwarden-api-url` | string | Optional | `https://api.bitwarden.com` | None | Public API Base URL; for EU Cloud pass `https://api.bitwarden.eu`, for self-hosted pass `https://your.domain.com/api` | `https://api.bitwarden.eu` |

Missing either of the two required headers on a `/mcp` request returns `401` with a
`required_headers` list.

### Env mode variables (`AUTH_MODE=env`, local dev only)

| Variable | Default | Description |
|---|---|---|
| `BITWARDEN_CLIENT_ID` | — | Organization API Key Client ID |
| `BITWARDEN_CLIENT_SECRET` | — | Organization API Key Client Secret |
| `BITWARDEN_API_URL` | `https://api.bitwarden.com` | Public API base URL |
| `BITWARDEN_IDENTITY_URL` | `https://identity.bitwarden.com` | Identity token endpoint base URL |
| `AUTH_MODE` | `gateway` | `env` or `gateway` |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `http` |
| `MCP_HTTP_PORT` | `8080` | HTTP server port |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP server bind address |

Get credentials: as an organization Owner, go to Admin Console → **Settings** →
**Organization info** → **API Key**. Requires a paid organization plan (Teams/Enterprise) —
free personal Bitwarden accounts have no organization and cannot use the Public API.

## Claude Desktop Setup

```json
{
  "mcpServers": {
    "bitwarden": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/bitwarden-mcp", "bitwarden-mcp"],
      "env": {
        "BITWARDEN_CLIENT_ID": "organization.xxxx",
        "BITWARDEN_CLIENT_SECRET": "xxxx"
      }
    }
  }
}
```

## Transport Modes

### stdio (Claude Desktop / CLI)
```bash
BITWARDEN_CLIENT_ID=organization.xxxx BITWARDEN_CLIENT_SECRET=xxxx uv run bitwarden-mcp
```

### HTTP — single-tenant (env mode)
```bash
BITWARDEN_CLIENT_ID=organization.xxxx BITWARDEN_CLIENT_SECRET=xxxx \
MCP_TRANSPORT=http AUTH_MODE=env uv run bitwarden-mcp
curl http://localhost:8080/health
```

### HTTP — gateway / multi-tenant (production)
```bash
MCP_TRANSPORT=http AUTH_MODE=gateway uv run bitwarden-mcp
```

## Tool List

Base URL: `https://api.bitwarden.com` (default; overridable per-request, see Authentication).

| Tool | Description | Parameters |
|---|---|---|
| `bitwarden_list_members` | List all members of the organization | None |
| `bitwarden_get_member` | Get details of the specified member | `member_id` (string, required) |
| `bitwarden_invite_member` | Invite a new member to join the organization | `email` (string, required), `type` (int, optional, default 2=User), `access_all` (bool, optional, default false), `external_id` (string, optional) |
| `bitwarden_reinvite_member` | Resend the invitation email | `member_id` (string, required) |
| `bitwarden_remove_member` | Remove a member from the organization | `member_id` (string, required) |
| `bitwarden_list_groups` | List all vault groups of the organization | None |
| `bitwarden_create_group` | Create a new vault group | `name` (string, required), `access_all` (bool, optional, default false), `external_id` (string, optional) |
| `bitwarden_list_member_groups` | View the groups the specified member currently belongs to | `member_id` (string, required) |
| `bitwarden_update_member_groups` | **Core operation**: assign the member to the specified set of vault groups (full overwrite, not incremental append) | `member_id` (string, required), `group_ids` (string[], required) |

**Member `type` (role) enum:** `0`=Owner, `1`=Admin, `2`=User (default/regular Member), `3`=Manager, `4`=Custom.
**Member `status` enum (read-only):** `0`=Invited, `1`=Accepted, `2`=Confirmed.

**Rate limits:** Bitwarden does not publish specific Public API rate-limit numbers (unlike
some other vendors). This service passes through `429` responses as-is if Bitwarden throttles
a request.

## Test Examples

### tools/list (gateway mode)
```bash
curl -X POST http://localhost:8080/mcp \
  -H "x-bitwarden-client-id: organization.your_client_id" \
  -H "x-bitwarden-client-secret: your_client_secret" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### tools/call — invite a member
```bash
curl -X POST http://localhost:8080/mcp \
  -H "x-bitwarden-client-id: organization.your_client_id" \
  -H "x-bitwarden-client-secret: your_client_secret" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 2,
    "params": {
      "name": "bitwarden_invite_member",
      "arguments": {"email": "user@example.com", "type": 2}
    }
  }'
```

### tools/call — assign a member to vault groups
```bash
curl -X POST http://localhost:8080/mcp \
  -H "x-bitwarden-client-id: organization.your_client_id" \
  -H "x-bitwarden-client-secret: your_client_secret" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "id": 3,
    "params": {
      "name": "bitwarden_update_member_groups",
      "arguments": {"member_id": "<member-uuid>", "group_ids": ["<group-uuid>"]}
    }
  }'
```

### Missing headers → 401
```bash
curl -i -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
# HTTP/1.1 401 Unauthorized
# {"error":"Missing credentials","required_headers":["x-bitwarden-client-id","x-bitwarden-client-secret"]}
```

## API Reference

- [Bitwarden Public API overview](https://bitwarden.com/help/public-api/)
- [Public API OpenAPI/Swagger definition](https://github.com/bitwarden/docs/blob/master/api/specs/public/swagger.json)
- [Member roles / access control](https://bitwarden.com/help/user-types-access-control/)

## Known Limitations

- **No Bitwarden Send support** — out of scope by design (see top of this README).
- **`bitwarden_update_member_groups` is a full replace, not an append** — it mirrors the
  underlying `PUT /public/members/{id}/group-ids` semantics exactly. To add a member to one
  more group without removing existing ones, call `bitwarden_list_member_groups` first, merge
  in the new group id, then pass the full list.
- **No documented Public API rate limits** from Bitwarden — errors are passed through as-is.
- Token exchange happens on every tool call (no caching), which adds latency but keeps the
  service fully stateless per the SOP requirement.
- Requires a paid organization plan (Teams/Enterprise) with an organization API key generated;
  free personal accounts cannot use this service.
