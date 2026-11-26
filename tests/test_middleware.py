import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import respx
from starlette.testclient import TestClient

from bitwarden_mcp.__main__ import _build_http_app
from bitwarden_mcp.server import create_mcp_server
from tests.conftest import API, EMAIL, IDENTITY, gateway_settings, make_account

ORG = {"x-bitwarden-client-id": "organization.1", "x-bitwarden-client-secret": "os"}
USER = {
    "x-bitwarden-user-client-id": "user.1",
    "x-bitwarden-user-client-secret": "us",
    "x-bitwarden-master-password": "right-pass",
}
BASE = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _app():
    settings = gateway_settings()
    return _build_http_app(create_mcp_server(settings), settings)


def _rpc(client, headers, method, params=None, session=None, id_=1):
    h = BASE | headers | ({"mcp-session-id": session} if session else {})
    r = client.post(
        "/mcp/",
        headers=h,
        json={"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}},
    )
    return r


def _data(resp):
    for line in resp.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return resp.json()


def _session(client, headers):
    r = _rpc(
        client,
        headers,
        "initialize",
        {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "1"},
        },
    )
    assert r.status_code == 200, r.text
    sid = r.headers["mcp-session-id"]
    client.post(
        "/mcp/",
        headers=BASE | headers | {"mcp-session-id": sid},
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    return sid


@pytest.mark.parametrize(
    "headers,status",
    [
        (ORG, 200),
        (USER, 200),
        ({}, 401),
        ({"x-bitwarden-client-id": "organization.1"}, 401),
        ({"x-bitwarden-user-client-id": "user.1", "x-bitwarden-master-password": "p"}, 401),
    ],
)
def test_header_set_matrix(headers, status):
    with TestClient(_app()) as client:
        if status == 401:
            r = _rpc(client, headers, "tools/list")
            assert r.status_code == 401
            req = r.json()["required_headers"]
            assert "x-bitwarden-client-id" in req["organization"]
            assert "x-bitwarden-master-password" in req["send"]
            return
        sid = _session(client, headers)
        r = _rpc(client, headers, "tools/list", session=sid, id_=2)
        assert r.status_code == 200
        names = {t["name"] for t in _data(r)["result"]["tools"]}
        assert "bitwarden_create_text_send" in names and "bitwarden_list_members" in names
        assert len(names) == 10


def test_existing_member_tool_unchanged_with_org_headers():
    with respx.mock(assert_all_called=False, assert_all_mocked=False) as r:
        r.route(host="testserver").pass_through()
        tok = r.post(f"{IDENTITY}/connect/token").respond(200, json={"access_token": "orgtok"})
        members = r.get(f"{API}/public/members").respond(200, json={"data": []})
        with TestClient(_app()) as client:
            sid = _session(client, ORG)
            _rpc(
                client,
                ORG,
                "tools/call",
                {"name": "bitwarden_list_members", "arguments": {}},
                sid,
                3,
            )
        form = tok.calls.last.request.content.decode()
        assert "scope=api.organization" in form and "client_id=organization.1" in form
        assert members.calls.last.request.headers["authorization"] == "Bearer orgtok"


def test_org_only_tenant_gets_clear_send_error():
    with TestClient(_app()) as client:
        sid = _session(client, ORG)
        r = _rpc(
            client,
            ORG,
            "tools/call",
            {"name": "bitwarden_create_text_send", "arguments": {"secret": "s"}},
            sid,
            4,
        )
        text = _data(r)["result"]["content"][0]["text"]
        assert json.loads(text)["error"] == "missing_credentials"


def test_concurrent_requests_isolated():
    _, protected = make_account()
    with respx.mock(assert_all_called=False) as r:
        r.route(host="testserver").pass_through()

        def token(request):
            from urllib.parse import parse_qs

            import httpx

            cid = parse_qs(request.content.decode())["client_id"][0]
            return httpx.Response(
                200,
                json={
                    "access_token": f"tok-{cid}",
                    "Key": protected,
                    "Kdf": 0,
                    "KdfIterations": 1000,
                },
            )

        def send(request):
            import httpx

            who = request.headers["authorization"].removeprefix("Bearer tok-")
            return httpx.Response(200, json={"id": f"id-{who}", "accessId": f"acc-{who}"})

        tok = r.post(f"{IDENTITY}/connect/token").mock(side_effect=token)
        r.get(f"{API}/accounts/profile").respond(200, json={"email": EMAIL})
        snd = r.post(f"{API}/sends").mock(side_effect=send)

        app = _app()

        def run(client, cid):
            headers = USER | {"x-bitwarden-user-client-id": cid}
            sid = _session(client, headers)
            resp = _rpc(
                client,
                headers,
                "tools/call",
                {"name": "bitwarden_create_text_send", "arguments": {"secret": "s"}},
                sid,
                5,
            )
            return json.loads(_data(resp)["result"]["content"][0]["text"])

        with TestClient(app) as client:
            with ThreadPoolExecutor(2) as pool:
                fa, fb = pool.submit(run, client, "user.A"), pool.submit(run, client, "user.B")
                a, b = fa.result(), fb.result()
        assert a["access_id"] == "acc-user.A" and b["access_id"] == "acc-user.B"
        assert "acc-user.B" not in a["link"] and "acc-user.A" not in b["link"]
        assert sorted(c.request.headers["authorization"] for c in snd.calls) == [
            "Bearer tok-user.A",
            "Bearer tok-user.B",
        ]
        assert len(tok.calls) == 2
