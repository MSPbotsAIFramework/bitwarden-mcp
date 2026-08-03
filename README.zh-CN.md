# bitwarden-mcp

[English](./README.md) | 中文

面向 Claude 的 Bitwarden MCP 服务——将 Bitwarden **Public API** 的组织**成员与密码库群组管理**能力
封装为 MCP 工具，核心场景是**邀请成员并将其分配到密码库群组**（"密码库群组邀请"）。

**技术栈：** Python 3.12 + uv + FastMCP（Starlette/uvicorn）

关联需求：PRD-15544（[Self-built MCP] MSPbots Integration - Bitwarden）。完整调研见
`vendor-mcp-template/prd/Bitwarden.md`。

**不在范围内：** 本服务不实现 Bitwarden Send（临时安全凭证链接）。Public API 不支持管理单个密码库
条目，而 Send 需要一个已解锁的、有状态的本地 `bw` CLI 保管库——与本服务无状态、多租户的网关架构
冲突，因此有意排除。

## 快速开始

```bash
cd bitwarden-mcp
uv sync

# stdio 模式（供 Claude Desktop / CLI 使用），单一共享凭据从环境变量读取
BITWARDEN_CLIENT_ID=organization.xxxx BITWARDEN_CLIENT_SECRET=xxxx uv run bitwarden-mcp
```

## 认证

本服务**无状态**：不保存、不持久化任何 Bitwarden 凭据。凭据要么通过环境变量一次性配置（本地调试，
`AUTH_MODE=env`），要么按请求通过 HTTP Header 传入（生产环境，`AUTH_MODE=gateway`）。

Bitwarden Public API 使用 **OAuth2 Client Credentials**（`grant_type=client_credentials`，
`scope=api.organization`）。每次工具调用，本服务都会用调用方传入的 `client_id` + `client_secret`
换取一个短期 `access_token`（有效期约 1 小时）并立即使用——**不做跨请求缓存**，以完全遵循"不持久化
凭据"的硬性要求。代价是每次调用会多一次 Identity 往返请求。

### Gateway 模式 HTTP Header（`AUTH_MODE=gateway`）

| Header | 类型 | 是否必填 | 默认值 | 枚举值 | 字段描述 | Example |
|---|---|---|---|---|---|---|
| `x-bitwarden-client-id` | string | 必填 | 无 | 无 | 组织 API Key 的 Client ID（Admin Console → Settings → Organization info） | `organization.3b1f...` |
| `x-bitwarden-client-secret` | string | 必填 | 无 | 无 | 对应 Client Secret，仅用于本次请求内换取 access_token，不持久化、不写日志 | `AbCdEf123...` |
| `x-bitwarden-identity-url` | string | 可选 | `https://identity.bitwarden.com` | 无 | Identity Token Endpoint，EU Cloud 传 `https://identity.bitwarden.eu`，自托管传 `https://your.domain.com/identity` | `https://identity.bitwarden.eu` |
| `x-bitwarden-api-url` | string | 可选 | `https://api.bitwarden.com` | 无 | Public API Base URL，EU Cloud 传 `https://api.bitwarden.eu`，自托管传 `https://your.domain.com/api` | `https://api.bitwarden.eu` |

`/mcp` 请求缺少上述两个必填 Header 中的任一个，都会返回 `401`，并在 `required_headers` 字段中列出。

### Env 模式变量（`AUTH_MODE=env`，仅限本地调试）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `BITWARDEN_CLIENT_ID` | — | 组织 API Key 的 Client ID |
| `BITWARDEN_CLIENT_SECRET` | — | 组织 API Key 的 Client Secret |
| `BITWARDEN_API_URL` | `https://api.bitwarden.com` | Public API Base URL |
| `BITWARDEN_IDENTITY_URL` | `https://identity.bitwarden.com` | Identity Token Endpoint Base URL |
| `AUTH_MODE` | `gateway` | `env` 或 `gateway` |
| `MCP_TRANSPORT` | `stdio` | `stdio` 或 `http` |
| `MCP_HTTP_PORT` | `8080` | HTTP 服务端口 |
| `MCP_HTTP_HOST` | `0.0.0.0` | HTTP 服务监听地址 |

获取凭据：以组织 Owner 身份登录 Admin Console，进入 **Settings** → **Organization info** →
**API Key**。需要付费组织计划（Teams/Enterprise）——免费个人账号没有组织，无法使用 Public API。

## Claude Desktop 配置

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

## 传输模式

### stdio（Claude Desktop / CLI）
```bash
BITWARDEN_CLIENT_ID=organization.xxxx BITWARDEN_CLIENT_SECRET=xxxx uv run bitwarden-mcp
```

### HTTP —— 单租户（env 模式）
```bash
BITWARDEN_CLIENT_ID=organization.xxxx BITWARDEN_CLIENT_SECRET=xxxx \
MCP_TRANSPORT=http AUTH_MODE=env uv run bitwarden-mcp
curl http://localhost:8080/health
```

### HTTP —— gateway / 多租户（生产环境）
```bash
MCP_TRANSPORT=http AUTH_MODE=gateway uv run bitwarden-mcp
```

## Tool List

Base URL：`https://api.bitwarden.com`（默认值，可按请求覆盖，见"认证"一节）

| Tool | 说明 | 参数 |
|---|---|---|
| `bitwarden_list_members` | 列出组织下所有成员 | 无 |
| `bitwarden_get_member` | 获取指定成员详情 | `member_id`（string，必填） |
| `bitwarden_invite_member` | 邀请新成员加入组织 | `email`（string，必填）、`type`（int，可选，默认 2=User）、`access_all`（bool，可选，默认 false）、`external_id`（string，可选） |
| `bitwarden_reinvite_member` | 重新发送邀请邮件 | `member_id`（string，必填） |
| `bitwarden_remove_member` | 将成员从组织移除 | `member_id`（string，必填） |
| `bitwarden_list_groups` | 列出组织下所有密码库群组 | 无 |
| `bitwarden_create_group` | 创建新的密码库群组 | `name`（string，必填）、`access_all`（bool，可选，默认 false）、`external_id`（string，可选） |
| `bitwarden_list_member_groups` | 查看指定成员当前所属的群组 | `member_id`（string，必填） |
| `bitwarden_update_member_groups` | **核心操作**：将成员分配到指定的一组密码库群组（全量覆盖，非增量追加） | `member_id`（string，必填）、`group_ids`（string[]，必填） |

**成员 `type`（角色）枚举：** `0`=Owner，`1`=Admin，`2`=User（默认，即普通 Member），`3`=Manager，`4`=Custom。
**成员 `status` 枚举（只读）：** `0`=Invited，`1`=Accepted，`2`=Confirmed。

**限流：** Bitwarden 官方未公开 Public API 的具体限流数值（不同于部分其他厂商）。若触发限流，
本服务会原样透传 Bitwarden 返回的 `429`。

## 测试示例

### tools/list（gateway 模式）
```bash
curl -X POST http://localhost:8080/mcp \
  -H "x-bitwarden-client-id: organization.your_client_id" \
  -H "x-bitwarden-client-secret: your_client_secret" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

### tools/call —— 邀请一个成员
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

### tools/call —— 将成员分配到密码库群组
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

### 缺 Header → 401
```bash
curl -i -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
# HTTP/1.1 401 Unauthorized
# {"error":"Missing credentials","required_headers":["x-bitwarden-client-id","x-bitwarden-client-secret"]}
```

## API 参考

- [Bitwarden Public API 概览](https://bitwarden.com/help/public-api/)
- [Public API OpenAPI/Swagger 定义](https://github.com/bitwarden/docs/blob/master/api/specs/public/swagger.json)
- [成员角色 / 权限说明](https://bitwarden.com/help/user-types-access-control/)

## 已知限制

- **不支持 Bitwarden Send** —— 有意排除，原因见本文档开头。
- **`bitwarden_update_member_groups` 是全量覆盖，不是追加** —— 与底层
  `PUT /public/members/{id}/group-ids` 语义完全一致。如需在不清空现有群组的前提下新增一个群组，
  应先调用 `bitwarden_list_member_groups`，把新群组 ID 合并进去，再传完整列表。
- Bitwarden 未公开 Public API 的具体限流数值——错误会原样透传。
- 每次工具调用都会重新做一次 token 交换（不缓存），会增加一点延迟，但换来完全符合 SOP 的无状态
  要求。
- 需要付费组织计划（Teams/Enterprise）并已生成组织 API Key；免费个人账号无法使用本服务。
