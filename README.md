# bitwarden-mcp

English | [中文](./README.zh-CN.md)

Bitwarden MCP server for Claude — exposes the Bitwarden **Public API**'s organization
**member and vault group management** as MCP tools, focused on **inviting members and
assigning them to vault groups** ("密码库群组邀请").

**Tech stack:** Python 3.12 + uv + FastMCP (Starlette/uvicorn)

关联需求：PRD-15544（[Self-built MCP] MSPbots Integration - Bitwarden）。完整调研见
`vendor-mcp-template/prd/Bitwarden.md`。

**Out of scope:** Bitwarden Send (temporary secure credential links) is intentionally not
implemented. The Public API does not allow management of individual vault items, and Send
requires a stateful, unlocked local `bw` CLI vault — incompatible with this service's
stateless, multi-tenant gateway model.

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

| Header | 类型 | 是否必填 | 默认值 | 枚举值 | 字段描述 | Example |
|---|---|---|---|---|---|---|
| `x-bitwarden-client-id` | string | 必填 | 无 | 无 | 组织 API Key 的 Client ID（Admin Console → Settings → Organization info） | `organization.3b1f...` |
| `x-bitwarden-client-secret` | string | 必填 | 无 | 无 | 对应 Client Secret，仅用于本次请求内换取 access_token，不持久化、不写日志 | `AbCdEf123...` |
| `x-bitwarden-identity-url` | string | 可选 | `https://identity.bitwarden.com` | 无 | Identity Token Endpoint，EU Cloud 传 `https://identity.bitwarden.eu`，自托管传 `https://your.domain.com/identity` | `https://identity.bitwarden.eu` |
| `x-bitwarden-api-url` | string | 可选 | `https://api.bitwarden.com` | 无 | Public API Base URL，EU Cloud 传 `https://api.bitwarden.eu`，自托管传 `https://your.domain.com/api` | `https://api.bitwarden.eu` |

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
| `bitwarden_list_members` | 列出组织下所有成员 | 无 |
| `bitwarden_get_member` | 获取指定成员详情 | `member_id` (string, 必填) |
| `bitwarden_invite_member` | 邀请新成员加入组织 | `email` (string, 必填), `type` (int, 可选, 默认 2=User), `access_all` (bool, 可选, 默认 false), `external_id` (string, 可选) |
| `bitwarden_reinvite_member` | 重新发送邀请邮件 | `member_id` (string, 必填) |
| `bitwarden_remove_member` | 将成员从组织移除 | `member_id` (string, 必填) |
| `bitwarden_list_groups` | 列出组织下所有密码库群组 | 无 |
| `bitwarden_create_group` | 创建新的密码库群组 | `name` (string, 必填), `access_all` (bool, 可选, 默认 false), `external_id` (string, 可选) |
| `bitwarden_list_member_groups` | 查看指定成员当前所属的群组 | `member_id` (string, 必填) |
| `bitwarden_update_member_groups` | **核心操作**：将成员分配到指定的一组密码库群组（全量覆盖，非增量追加） | `member_id` (string, 必填), `group_ids` (string[], 必填) |

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
