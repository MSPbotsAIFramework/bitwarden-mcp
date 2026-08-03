from typing import Any

import httpx

DEFAULT_API_URL = "https://api.bitwarden.com"
DEFAULT_IDENTITY_URL = "https://identity.bitwarden.com"

# OAuth2 client_credentials scope for organization management via the Public API.
# https://bitwarden.com/help/public-api/
TOKEN_SCOPE = "api.organization"


class BitwardenError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Bitwarden API error {status_code}: {message}")


class BitwardenClient:
    """Async httpx client wrapping the Bitwarden Public API.

    Per request, exchanges client_id/client_secret for a short-lived OAuth2
    access_token (~1h TTL) and uses it immediately — the token is never cached
    or reused across requests, in line with the "no persisted credentials"
    requirement. This adds one extra Identity round trip per call, which is
    acceptable given member/group management is not a high-frequency operation.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        api_url: str = DEFAULT_API_URL,
        identity_url: str = DEFAULT_IDENTITY_URL,
    ):
        self._client_id = client_id
        self._client_secret = client_secret
        self._api_url = api_url.rstrip("/")
        self._identity_url = identity_url.rstrip("/")

    async def _fetch_access_token(self) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._identity_url}/connect/token",
                data={
                    "grant_type": "client_credentials",
                    "scope": TOKEN_SCOPE,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if resp.status_code >= 400:
                try:
                    detail = resp.json()
                except Exception:
                    detail = resp.text
                raise BitwardenError(resp.status_code, f"Token exchange failed: {detail}")
            return resp.json()["access_token"]

    async def _headers(self) -> dict[str, str]:
        token = await self._fetch_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _clean_params(self, params: dict | None) -> dict:
        if not params:
            return {}
        return {k: v for k, v in params.items() if v is not None}

    async def get(self, path: str, params: dict | None = None) -> Any:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self._api_url}{path}",
                headers=headers,
                params=self._clean_params(params),
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 and resp.content else None

    async def post(self, path: str, body: Any = None) -> Any:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self._api_url}{path}",
                headers=headers,
                json=body,
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 and resp.content else None

    async def put(self, path: str, body: Any = None) -> Any:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self._api_url}{path}",
                headers=headers,
                json=body,
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 and resp.content else None

    async def delete(self, path: str) -> Any:
        headers = await self._headers()
        async with httpx.AsyncClient() as client:
            resp = await client.delete(
                f"{self._api_url}{path}",
                headers=headers,
            )
            self._raise_for_status(resp)
            return resp.json() if resp.status_code != 204 and resp.content else None

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code >= 400:
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text
            raise BitwardenError(resp.status_code, str(detail))
