"""Encrypt provider OAuth tokens. The key never enters the database.

``PU_TOKEN_KEY`` is read from the environment at call time. Ciphertext is an
HMAC-SHA256 keystream (encrypt-then-MAC). Callers persist only that blob.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

_PREFIX = b"enc1"
_NONCE = 16
_MAC = 32


class TokenKeyError(RuntimeError):
    """The process has no encryption key outside the database."""


def token_key_material() -> str:
    """Return the configured key. Empty when the operator has not set one."""
    return os.environ.get("PU_TOKEN_KEY", "")


def _key() -> bytes:
    raw = token_key_material()
    if len(raw) < 16:
        raise TokenKeyError("PU_TOKEN_KEY must be set outside the database")
    return hashlib.sha256(raw.encode("utf-8")).digest()


def _stream(key: bytes, nonce: bytes, size: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < size:
        block = hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:size])


def encrypt(plaintext: bytes) -> str:
    key = _key()
    nonce = secrets.token_bytes(_NONCE)
    body = bytes(left ^ right for left, right in zip(plaintext, _stream(key, nonce, len(plaintext))))
    mac = hmac.new(key, _PREFIX + nonce + body, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(_PREFIX + nonce + mac + body).decode("ascii")


def decrypt(ciphertext: str) -> bytes:
    raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    if not raw.startswith(_PREFIX) or len(raw) < len(_PREFIX) + _NONCE + _MAC:
        raise ValueError("ciphertext")
    nonce = raw[len(_PREFIX) : len(_PREFIX) + _NONCE]
    mac = raw[len(_PREFIX) + _NONCE : len(_PREFIX) + _NONCE + _MAC]
    body = raw[len(_PREFIX) + _NONCE + _MAC :]
    key = _key()
    expected = hmac.new(key, _PREFIX + nonce + body, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("ciphertext")
    return bytes(left ^ right for left, right in zip(body, _stream(key, nonce, len(body))))
