"""Shared helpers: a fake Bitwarden (identity, profile, sends) built on respx."""

import base64
import json
import os

import pytest
import respx

from bitwarden_mcp import send_crypto as sc
from bitwarden_mcp.config import Settings
from bitwarden_mcp.send_client import BitwardenSendClient, SendCredentials

API = "https://api.bitwarden.com"
IDENTITY = "https://identity.bitwarden.com"
EMAIL = "Sender@Example.com"
PASSWORD = "right-pass"
FAST_ITERATIONS = 1000


def make_account(password=PASSWORD, email=EMAIL, kdf=0, iterations=FAST_ITERATIONS):
    user_key = os.urandom(64)
    master = sc.derive_master_key(
        password, email, kdf, iterations, 16 if kdf else None, 2 if kdf else None
    )
    protected = sc.encrypt_enc_string(user_key, sc.stretch(master))
    return user_key, protected


@pytest.fixture
def bw():
    """Mocked Bitwarden for one account; yields an object with the routes and user key."""
    user_key, protected = make_account()
    with respx.mock(assert_all_called=False) as router:
        token = router.post(f"{IDENTITY}/connect/token").respond(
            200,
            json={
                "access_token": "tok-1",
                "Key": protected,
                "Kdf": 0,
                "KdfIterations": FAST_ITERATIONS,
            },
        )
        profile = router.get(f"{API}/accounts/profile").respond(200, json={"email": EMAIL})
        sends = router.post(f"{API}/sends").respond(
            200, json={"id": "send-uuid", "accessId": "AcC3ssId"}
        )

        class Env:
            pass

        env = Env()
        env.router, env.token, env.profile, env.sends = router, token, profile, sends
        env.user_key, env.protected = user_key, protected
        yield env


def send_client(password=PASSWORD, api_url=API):
    return BitwardenSendClient(SendCredentials("user.abc", "csecret", password, api_url, IDENTITY))


def last_body(route) -> dict:
    return json.loads(route.calls.last.request.content)


def b64url_seed(link: str) -> bytes:
    frag = link.rsplit("/", 1)[1]
    return base64.urlsafe_b64decode(frag + "=" * (-len(frag) % 4))


def gateway_settings() -> Settings:
    return Settings(auth_mode="gateway", mcp_transport="http")
