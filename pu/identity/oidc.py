"""OIDC Authorization Code with PKCE (S256).

The authorization redirect carries the code challenge. The token request
carries the verifier. Tests supply ``http_post`` so no real identity
provider and no real client secret are required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class AuthError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OidcProvider:
    authorization_endpoint: str
    token_endpoint: str
    client_id: str
    redirect_uri: str
    client_secret: str = ""
    http_post: Callable[[str, dict[str, str]], dict[str, Any]] | None = None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(provider: OidcProvider, *, state: str, challenge: str) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "scope": "openid",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in provider.authorization_endpoint else "?"
    return f"{provider.authorization_endpoint}{separator}{query}"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64_json(value: dict) -> str:
    return _b64(json.dumps(value, separators=(",", ":")).encode("utf-8"))


def sign_hs256(payload: dict, secret: str) -> str:
    """Sign a test identity token. Production verifiers use the same check."""
    header = _b64_json({"alg": "HS256", "typ": "JWT"})
    body = _b64_json(payload)
    signature = hmac.new(secret.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256)
    return f"{header}.{body}.{_b64(signature.digest())}"


def verify_hs256(token: str, secret: str) -> dict:
    try:
        header, body, signature = token.split(".")
    except ValueError as exc:
        raise AuthError("id_token") from exc
    expected = hmac.new(
        secret.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256
    ).digest()
    padded = signature + "=" * (-len(signature) % 4)
    try:
        actual = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise AuthError("id_token") from exc
    if not hmac.compare_digest(expected, actual):
        raise AuthError("id_token")
    padded_body = body + "=" * (-len(body) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(padded_body.encode("ascii")))
    except (ValueError, TypeError) as exc:
        raise AuthError("id_token") from exc
    if not isinstance(claims, dict) or not claims.get("sub"):
        raise AuthError("missing_sub")
    return claims


def exchange_code(provider: OidcProvider, *, code: str, verifier: str) -> str:
    """Exchange an authorization code. Returns the subject and drops the tokens."""
    if provider.http_post is None:
        raise AuthError("idp_transport")
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": provider.redirect_uri,
        "client_id": provider.client_id,
        "code_verifier": verifier,
    }
    if provider.client_secret:
        form["client_secret"] = provider.client_secret
    payload = provider.http_post(provider.token_endpoint, form)
    if not isinstance(payload, dict):
        raise AuthError("token_response")
    subject = payload.get("sub")
    if not subject and payload.get("id_token"):
        claims = verify_hs256(str(payload["id_token"]), provider.client_secret)
        subject = claims.get("sub")
    if not subject:
        raise AuthError("missing_sub")
    return str(subject)
