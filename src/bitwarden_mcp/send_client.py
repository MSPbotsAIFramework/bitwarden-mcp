"""Stateless Bitwarden Send client (PRD-22483).

Per call: log in with a *user* API key, unlock the account key with the master password
in memory, build the end-to-end encrypted text Send and POST it. Nothing is cached or
logged; error text is built from the HTTP status and Bitwarden's `message` field only.
"""

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from . import send_crypto as sc
from .api_client import DEFAULT_API_URL, DEFAULT_IDENTITY_URL

USER_TOKEN_SCOPE = "api"
DEVICE_TYPE_SDK = "21"
DEVICE_NAMESPACE = uuid.UUID("6f1a6c1e-4d57-4c5c-9f67-2f3a5b3c9d10")
TIMEOUT = httpx.Timeout(30.0)
DELETION_DAYS = 30


class SendError(Exception):
    """Structured, secret-free failure. `payload` is returned to the agent as JSON."""

    def __init__(self, error: str, **fields: Any):
        self.payload = {"error": error, **fields}
        super().__init__(error)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pick(data: dict, *names: str) -> Any:
    for name in names:
        if name in data:
            return data[name]
    return None


def _bitwarden_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        msg = _pick(body, "message", "Message", "error_description")
        if isinstance(msg, str) and msg:
            return msg
    except Exception:
        pass
    return f"HTTP {resp.status_code}"


@dataclass(frozen=True)
class SendCredentials:
    client_id: str
    client_secret: str
    master_password: str
    api_url: str = DEFAULT_API_URL
    identity_url: str = DEFAULT_IDENTITY_URL


class BitwardenSendClient:
    def __init__(self, creds: SendCredentials):
        self._c = creds
        self._api = creds.api_url.rstrip("/")
        self._identity = creds.identity_url.rstrip("/")

    async def create_text_send(
        self,
        secret: str,
        name: str,
        expiration_hours: int,
        max_access_count: int,
        hide_text: bool,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as http:
                token = await self._login(http)
                user_key = await self._unlock(http, token)
                body, seed = self._build_send(
                    user_key, secret, name, expiration_hours, max_access_count, hide_text
                )
                resp = await http.post(
                    f"{self._api}/sends",
                    json=body,
                    headers={"Authorization": f"Bearer {token['access_token']}"},
                )
        except httpx.TimeoutException:
            raise SendError("bitwarden_error", status=None, message="timeout") from None
        except httpx.HTTPError:
            raise SendError("bitwarden_error", status=None, message="network error") from None
        if resp.status_code >= 400:
            raise SendError(
                "bitwarden_error", status=resp.status_code, message=_bitwarden_message(resp)
            )
        sent = resp.json()
        access_id = _pick(sent, "accessId", "AccessId")
        return {
            "send_id": _pick(sent, "id", "Id"),
            "access_id": access_id,
            "link": sc.send_link(self._c.api_url, access_id, seed),
            "expiration_date": body["expirationDate"],
            "deletion_date": body["deletionDate"],
            "max_access_count": max_access_count,
            "name": name,
        }

    async def _login(self, http: httpx.AsyncClient) -> dict:
        device_id = uuid.uuid5(DEVICE_NAMESPACE, self._c.client_id)
        resp = await http.post(
            f"{self._identity}/connect/token",
            data={
                "grant_type": "client_credentials",
                "scope": USER_TOKEN_SCOPE,
                "client_id": self._c.client_id,
                "client_secret": self._c.client_secret,
                "deviceType": DEVICE_TYPE_SDK,
                "deviceIdentifier": str(device_id),
                "deviceName": "mspbots-bitwarden-mcp",
            },
        )
        if resp.status_code >= 400:
            raise SendError(
                "authentication_failed",
                message=f"Bitwarden rejected the user API key (HTTP {resp.status_code})",
            )
        return resp.json()

    async def _unlock(self, http: httpx.AsyncClient, token: dict) -> bytes:
        protected_key = _pick(token, "Key", "key")
        if not protected_key:
            raise SendError(
                "unsupported_account",
                message="Account has no master password (SSO / Key Connector)",
            )
        kdf = _pick(token, "Kdf", "kdf")
        iterations = _pick(token, "KdfIterations", "kdfIterations")
        if kdf is None or not iterations:
            raise SendError("unsupported_account", message="Account KDF settings were not returned")
        email = await self._email(http, token["access_token"])
        try:
            master_key = sc.derive_master_key(
                self._c.master_password,
                email,
                int(kdf),
                int(iterations),
                _pick(token, "KdfMemory", "kdfMemory"),
                _pick(token, "KdfParallelism", "kdfParallelism"),
            )
            return sc.unlock_user_key(protected_key, master_key)
        except (sc.UnlockError, ValueError):
            raise SendError(
                "unlock_failed", message="The master password could not unlock the account key"
            ) from None

    async def _email(self, http: httpx.AsyncClient, access_token: str) -> str:
        resp = await http.get(
            f"{self._api}/accounts/profile",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code >= 400:
            raise SendError(
                "bitwarden_error", status=resp.status_code, message=_bitwarden_message(resp)
            )
        email = _pick(resp.json(), "email", "Email")
        if not email:
            raise SendError("bitwarden_error", status=None, message="profile has no email")
        return email

    @staticmethod
    def _build_send(
        user_key: bytes,
        secret: str,
        name: str,
        expiration_hours: int,
        max_access_count: int,
        hide_text: bool,
    ) -> tuple[dict, bytes]:
        seed = os.urandom(sc.SEED_LENGTH)
        send_key = sc.make_send_key(seed)
        now = datetime.now(UTC)
        expires = now + timedelta(hours=expiration_hours)
        deletion = max(now + timedelta(days=DELETION_DAYS), expires + timedelta(hours=1))
        body = {
            "type": 0,
            "key": sc.encrypt_enc_string(seed, user_key),
            "name": sc.encrypt_enc_string(name.encode(), send_key),
            "notes": None,
            "text": {
                "text": sc.encrypt_enc_string(secret.encode(), send_key),
                "hidden": hide_text,
            },
            "maxAccessCount": max_access_count,
            "expirationDate": _iso(expires),
            "deletionDate": _iso(deletion),
            "password": None,
            "disabled": False,
            "hideEmail": False,
        }
        return body, seed
