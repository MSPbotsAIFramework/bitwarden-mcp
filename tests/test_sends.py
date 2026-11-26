import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from bitwarden_mcp.tools import sends
from tests.conftest import API, EMAIL, IDENTITY, PASSWORD, last_body, send_client

HEADERS = [
    "x-bitwarden-user-client-id",
    "x-bitwarden-user-client-secret",
    "x-bitwarden-master-password",
]


class FakeMCP:
    def __init__(self):
        self.tools = {}

    def tool(self):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn

        return deco


def tool(client_factory):
    mcp = FakeMCP()
    sends.register(mcp, client_factory, HEADERS)
    return mcp.tools["bitwarden_create_text_send"]


def parse(s: str) -> dict:
    return json.loads(s)


def _parse_dt(v: str) -> datetime:
    return datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


async def test_create_text_send_builds_encrypted_request_and_returns_link(bw):
    fn = tool(send_client)
    res = parse(await fn(secret="Welcome#2026", expiration_hours=24, max_access_count=1))
    assert len(bw.sends.calls) == 1
    body = last_body(bw.sends)
    assert body["type"] == 0 and body["maxAccessCount"] == 1
    exp = _parse_dt(body["expirationDate"])
    assert abs((exp - (datetime.now(UTC) + timedelta(hours=24))).total_seconds()) < 60
    assert _parse_dt(body["deletionDate"]) >= exp
    assert body["text"]["hidden"] is True
    for enc in (body["text"]["text"], body["name"], body["key"]):
        assert enc.startswith("2.") and enc.count("|") == 2 and "Welcome#2026" not in enc
    for k in ("send_id", "access_id", "link", "expiration_date", "deletion_date"):
        assert res[k]
    assert res["max_access_count"] == 1
    assert bw.sends.calls.last.request.headers["authorization"] == "Bearer tok-1"


@pytest.mark.parametrize(
    "kwargs,field",
    [
        ({"expiration_hours": 0}, "expiration_hours"),
        ({"expiration_hours": 721}, "expiration_hours"),
        ({"max_access_count": 0}, "max_access_count"),
        ({"max_access_count": 101}, "max_access_count"),
        ({"secret": ""}, "secret"),
        ({"secret": "x" * 1001}, "secret"),
        ({"name": "n" * 101}, "name"),
    ],
)
async def test_out_of_range_arguments_rejected_without_http(bw, kwargs, field):
    args = {"secret": "s"} | kwargs
    res = parse(await tool(send_client)(**args))
    assert res["error"] == "invalid_argument" and res["field"] == field
    assert not bw.token.calls and not bw.sends.calls


@pytest.mark.parametrize(
    "kwargs",
    [
        {"expiration_hours": 1},
        {"expiration_hours": 720},
        {"max_access_count": 1},
        {"max_access_count": 100},
        {"secret": "x" * 1000},
    ],
)
async def test_boundary_values_accepted(bw, kwargs):
    res = parse(await tool(send_client)(**({"secret": "s"} | kwargs)))
    assert "link" in res
    body = last_body(bw.sends)
    assert _parse_dt(body["deletionDate"]) >= _parse_dt(body["expirationDate"])


async def test_missing_user_headers_returns_missing_credentials(bw):
    res = parse(await tool(lambda: None)(secret="s"))
    assert res == {"error": "missing_credentials", "required_headers": HEADERS}
    assert not bw.token.calls and not bw.sends.calls


async def test_wrong_master_password_returns_unlock_failed_and_creates_nothing(bw):
    res = parse(await tool(lambda: send_client("wrong-pass"))(secret="s"))
    assert res["error"] == "unlock_failed"
    assert not bw.sends.calls


async def test_downstream_failures_return_structured_errors(bw):
    fn = tool(send_client)

    bw.token.respond(400, json={"error": "invalid_client"})
    res = parse(await fn(secret="s"))
    assert res["error"] == "authentication_failed"

    bw.token.respond(
        200, json={"access_token": "t", "Key": bw.protected, "Kdf": 0, "KdfIterations": 1000}
    )
    msg = "Due to an Enterprise Policy, you are only able to delete an existing Send."
    bw.sends.respond(400, json={"message": msg})
    res = parse(await fn(secret="s"))
    assert res == {"error": "bitwarden_error", "status": 400, "message": msg}

    for status in (429, 500):
        bw.sends.respond(status, text="boom")
        res = parse(await fn(secret="s"))
        assert res["error"] == "bitwarden_error" and res["status"] == status

    bw.sends.mock(side_effect=httpx.ReadTimeout("t"))
    res = parse(await fn(secret="s"))
    assert res["error"] == "bitwarden_error" and res["message"] == "timeout"

    bw.token.respond(200, json={"access_token": "t"})
    res = parse(await fn(secret="s"))
    assert res["error"] == "unsupported_account"
    assert "link" not in res


async def test_secret_and_master_password_never_in_result_errors_or_logs(bw, caplog):
    secret, mp = "S3cr3t-Unique-7781", "MP-Unique-5520"
    caplog.set_level(logging.DEBUG)
    outputs = [parse(await tool(lambda: send_client(PASSWORD))(secret=secret))]
    outputs.append(parse(await tool(lambda: send_client(mp))(secret=secret)))
    bw.sends.respond(400, json={"message": "policy"})
    outputs.append(parse(await tool(lambda: send_client(PASSWORD))(secret=secret)))
    bw.token.respond(400, json={"error": "invalid_client"})
    outputs.append(parse(await tool(lambda: send_client(PASSWORD))(secret=secret)))
    blob = json.dumps(outputs) + caplog.text
    assert secret not in blob and mp not in blob
    assert set(outputs[0]) == {
        "send_id",
        "access_id",
        "link",
        "expiration_date",
        "deletion_date",
        "max_access_count",
        "name",
    }


async def test_kdf_cost_baseline():
    import respx

    from bitwarden_mcp import send_crypto as sc
    from tests.conftest import make_account

    user_key, protected = make_account(iterations=600000)
    with respx.mock() as r:
        r.post(f"{IDENTITY}/connect/token").respond(
            200, json={"access_token": "t", "Key": protected, "Kdf": 0, "KdfIterations": 600000}
        )
        r.get(f"{API}/accounts/profile").respond(200, json={"email": EMAIL})
        r.post(f"{API}/sends").respond(200, json={"id": "i", "accessId": "a"})
        times = []
        for _ in range(10):
            t = time.perf_counter()
            res = parse(await tool(send_client)(secret="s"))
            times.append(time.perf_counter() - t)
            assert "link" in res
    assert sorted(times)[-1] <= 2.0
    assert sc  # keep import used
