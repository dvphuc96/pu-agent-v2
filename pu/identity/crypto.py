"""Encrypt provider OAuth tokens. The key never enters the database.

``PU_TOKEN_KEY`` is read from the environment at call time. New ciphertext is
AES-GCM (``enc2``). The key is derived with HKDF and a random salt, and the
AEAD binds ``owner_user_id`` and the connection id as additional data.
``enc1`` blobs (the previous HMAC keystream) still decrypt, so a caller can
rewrite them with ``encrypt``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_PREFIX_V1 = b"enc1"
_PREFIX_V2 = b"enc2"
_V1_NONCE = 16
_V1_MAC = 32
_SALT = 16
_NONCE = 12
_INFO = b"pu-oauth-token-v2"


class TokenKeyError(RuntimeError):
    """The process has no encryption key outside the database."""


def token_key_material() -> str:
    """Return the configured key. Empty when the operator has not set one."""
    return os.environ.get("PU_TOKEN_KEY", "")


def _key_bytes() -> bytes:
    raw = token_key_material()
    if len(raw) < 16:
        raise TokenKeyError("PU_TOKEN_KEY must be set outside the database")
    return raw.encode("utf-8")


def _aad(owner_user_id: str, connection_id: str) -> bytes:
    if not owner_user_id or not connection_id:
        raise ValueError("ciphertext")
    return owner_user_id.encode("utf-8") + b"\0" + connection_id.encode("utf-8")


def _derive(salt: bytes) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=_INFO,
    ).derive(_key_bytes())


def _v1_key() -> bytes:
    return hashlib.sha256(_key_bytes()).digest()


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < size:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:size])


def _encrypt_enc1(plaintext: bytes) -> str:
    """Write a legacy blob. Kept so migration tests can build an old row."""
    key = _v1_key()
    nonce = secrets.token_bytes(_V1_NONCE)
    body = bytes(left ^ right for left, right in zip(plaintext, _stream(key, nonce, len(plaintext)), strict=True))
    mac = hmac.new(key, _PREFIX_V1 + nonce + body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(_PREFIX_V1 + nonce + mac + body).decode("ascii")


def _decrypt_enc1(raw: bytes) -> bytes:
    if len(raw) < len(_PREFIX_V1) + _V1_NONCE + _V1_MAC:
        raise ValueError("ciphertext")
    nonce = raw[len(_PREFIX_V1) : len(_PREFIX_V1) + _V1_NONCE]
    mac = raw[len(_PREFIX_V1) + _V1_NONCE : len(_PREFIX_V1) + _V1_NONCE + _V1_MAC]
    body = raw[len(_PREFIX_V1) + _V1_NONCE + _V1_MAC :]
    key = _v1_key()
    expected = hmac.new(key, _PREFIX_V1 + nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("ciphertext")
    return bytes(left ^ right for left, right in zip(body, _stream(key, nonce, len(body)), strict=True))


def encrypt(plaintext: bytes, *, owner_user_id: str, connection_id: str) -> str:
    salt = secrets.token_bytes(_SALT)
    nonce = secrets.token_bytes(_NONCE)
    body = AESGCM(_derive(salt)).encrypt(nonce, plaintext, _aad(owner_user_id, connection_id))
    return base64.urlsafe_b64encode(_PREFIX_V2 + salt + nonce + body).decode("ascii")


def is_legacy_ciphertext(ciphertext: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    except (ValueError, TypeError):
        return False
    return raw.startswith(_PREFIX_V1)


def decrypt(ciphertext: str, *, owner_user_id: str, connection_id: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise ValueError("ciphertext") from exc
    if raw.startswith(_PREFIX_V1):
        _aad(owner_user_id, connection_id)
        return _decrypt_enc1(raw)
    if not raw.startswith(_PREFIX_V2) or len(raw) < len(_PREFIX_V2) + _SALT + _NONCE + 16:
        raise ValueError("ciphertext")
    offset = len(_PREFIX_V2)
    salt = raw[offset : offset + _SALT]
    offset += _SALT
    nonce = raw[offset : offset + _NONCE]
    body = raw[offset + _NONCE :]
    try:
        return AESGCM(_derive(salt)).decrypt(nonce, body, _aad(owner_user_id, connection_id))
    except Exception as exc:
        raise ValueError("ciphertext") from exc
