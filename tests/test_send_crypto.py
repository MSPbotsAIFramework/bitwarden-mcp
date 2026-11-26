import base64
import hashlib

import pytest

from bitwarden_mcp import send_crypto as sc
from tests.conftest import b64url_seed, make_account


def _tool_run(bw_env, secret="Welcome#2026"):
    import asyncio

    from tests.conftest import send_client

    return asyncio.run(send_client().create_text_send(secret, "Credentials", 24, 1, True))


def test_link_seed_decrypts_text_and_user_key_decrypts_seed(bw):
    from tests.conftest import last_body

    result = _tool_run(bw, "Welcome#2026")
    body = last_body(bw.sends)
    seed = b64url_seed(result["link"])
    send_key = sc.make_send_key(seed)
    assert len(seed) == 16
    assert sc.decrypt_enc_string(body["text"]["text"], send_key) == b"Welcome#2026"
    assert sc.decrypt_enc_string(body["key"], bw.user_key) == seed


@pytest.mark.parametrize("kdf,iterations", [(0, 1000), (1, 2)])
def test_unlock_user_key_pbkdf2_and_argon2id(kdf, iterations):
    user_key, protected = make_account("pw-1", "A@B.com", kdf, iterations)
    master = sc.derive_master_key(
        "pw-1", "a@b.com", kdf, iterations, 16 if kdf else None, 2 if kdf else None
    )
    assert sc.unlock_user_key(protected, master) == user_key
    assert len(sc.stretch(master)) == 64
    wrong = sc.derive_master_key(
        "nope", "a@b.com", kdf, iterations, 16 if kdf else None, 2 if kdf else None
    )
    with pytest.raises(sc.UnlockError):
        sc.unlock_user_key(protected, wrong)


def test_known_vectors():
    # PBKDF2 vector (RFC-style, independently computed with hashlib) and HKDF expand sanity.
    assert (
        sc.derive_master_key("password", "ONE@x.com", 0, 1).hex()
        == hashlib.pbkdf2_hmac("sha256", b"password", b"one@x.com", 1, 32).hex()
    )
    iv = bytes(range(16))
    key = bytes(range(64))
    enc = sc.encrypt_enc_string(b"hello", key, iv)
    assert enc.startswith("2." + base64.b64encode(iv).decode() + "|")
    assert sc.decrypt_enc_string(enc, key) == b"hello"


@pytest.mark.parametrize(
    "api_url,base,sep",
    [
        (None, "https://send.bitwarden.com/#", ""),
        ("https://api.bitwarden.com", "https://send.bitwarden.com/#", ""),
        ("https://api.bitwarden.eu", "https://vault.bitwarden.eu/#/send", "/"),
        ("https://vault.example.com/api", "https://vault.example.com/#/send", "/"),
    ],
)
def test_send_link_base_per_region(api_url, base, sep):
    seed = bytes(range(16))
    frag = base64.urlsafe_b64encode(seed).decode().rstrip("=")
    assert sc.send_link(api_url, "abc123", seed) == f"{base}{sep}abc123/{frag}"
