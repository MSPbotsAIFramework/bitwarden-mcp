"""Bitwarden Send cryptography (PRD-22483). Pure functions, no I/O.

Follows the open-source Bitwarden clients: EncString type 2 (AES-256-CBC + HMAC-SHA256),
master key via PBKDF2-SHA256 or Argon2id, key stretching via HKDF-Expand, and the Send key
derived from a 16-byte seed with HKDF-SHA256 (salt "bitwarden-send", info "send").
"""

import base64
import hashlib
import hmac
import os
from urllib.parse import urlparse

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives import hashes, padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF, HKDFExpand

KDF_PBKDF2 = 0
KDF_ARGON2ID = 1
SEED_LENGTH = 16
DEFAULT_SEND_LINK_BASE = "https://send.bitwarden.com/#"


class UnlockError(Exception):
    """The key material could not be decrypted (wrong master password or bad data)."""


def derive_master_key(
    password: str,
    email: str,
    kdf: int,
    iterations: int,
    memory_mib: int | None = None,
    parallelism: int | None = None,
) -> bytes:
    salt = email.strip().lower().encode()
    pw = password.encode()
    if kdf == KDF_PBKDF2:
        return hashlib.pbkdf2_hmac("sha256", pw, salt, iterations, 32)
    if kdf == KDF_ARGON2ID:
        return hash_secret_raw(
            secret=pw,
            salt=hashlib.sha256(salt).digest(),
            time_cost=iterations,
            memory_cost=(memory_mib or 64) * 1024,
            parallelism=parallelism or 4,
            hash_len=32,
            type=Type.ID,
        )
    raise ValueError(f"unsupported KDF type {kdf}")


def stretch(master_key: bytes) -> bytes:
    """Return enc(32) || mac(32) from the master key (HKDF-Expand, info 'enc' / 'mac')."""
    enc = HKDFExpand(hashes.SHA256(), 32, b"enc").derive(master_key)
    mac = HKDFExpand(hashes.SHA256(), 32, b"mac").derive(master_key)
    return enc + mac


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def encrypt_enc_string(data: bytes, key: bytes, iv: bytes | None = None) -> str:
    iv = iv or os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    enc = Cipher(algorithms.AES(key[:32]), modes.CBC(iv)).encryptor()
    ct = enc.update(padded) + enc.finalize()
    mac = hmac.new(key[32:64], iv + ct, hashlib.sha256).digest()
    return f"2.{_b64(iv)}|{_b64(ct)}|{_b64(mac)}"


def decrypt_enc_string(enc_string: str, key: bytes) -> bytes:
    try:
        kind, rest = enc_string.split(".", 1)
        if kind != "2":
            raise UnlockError("unsupported EncString type")
        iv, ct, mac = (base64.b64decode(p) for p in rest.split("|"))
    except UnlockError:
        raise
    except Exception as exc:
        raise UnlockError("malformed EncString") from exc
    expected = hmac.new(key[32:64], iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, mac):
        raise UnlockError("MAC check failed")
    dec = Cipher(algorithms.AES(key[:32]), modes.CBC(iv)).decryptor()
    padded = dec.update(ct) + dec.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def unlock_user_key(protected_key: str, master_key: bytes) -> bytes:
    user_key = decrypt_enc_string(protected_key, stretch(master_key))
    if len(user_key) != 64:
        raise UnlockError("unsupported user key length")
    return user_key


def make_send_key(seed: bytes) -> bytes:
    return HKDF(hashes.SHA256(), 64, b"bitwarden-send", b"send").derive(seed)


def send_link(api_url: str | None, access_id: str, seed: bytes) -> str:
    """Build the share link for the region the account lives in."""
    fragment = base64.urlsafe_b64encode(seed).decode().rstrip("=")
    base = DEFAULT_SEND_LINK_BASE
    if api_url:
        parsed = urlparse(api_url.rstrip("/"))
        host = parsed.hostname or ""
        if host == "api.bitwarden.com":
            pass
        elif host == "api.bitwarden.eu":
            base = "https://vault.bitwarden.eu/#/send"
        else:
            path = parsed.path.removesuffix("/api")
            base = f"{parsed.scheme}://{parsed.netloc}{path}/#/send"
    return f"{base}/{access_id}/{fragment}"
