"""OIDC Authorization Code with PKCE (S256).

The authorization redirect carries the code challenge and a nonce. The token
request carries the verifier. Identity tokens are checked for issuer,
audience, expiry, and that nonce. HS256 uses the client secret. RS256 uses
the provider's JWKS. Tests supply ``http_post`` and ``jwks`` so no real
identity provider is required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
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
    issuer: str = ""
    jwks_uri: str = ""
    jwks: dict[str, Any] | None = None
    http_post: Callable[[str, dict[str, str]], dict[str, Any]] | None = None
    http_get: Callable[[str], dict[str, Any]] | None = None


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(
    provider: OidcProvider, *, state: str, challenge: str, nonce: str
) -> str:
    query = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": provider.client_id,
            "redirect_uri": provider.redirect_uri,
            "scope": "openid",
            "state": state,
            "nonce": nonce,
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


def _b64_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _equal(left: str, right: str) -> bool:
    left_b, right_b = left.encode("utf-8"), right.encode("utf-8")
    if len(left_b) != len(right_b):
        return False
    return hmac.compare_digest(left_b, right_b)


def sign_hs256(payload: dict, secret: str) -> str:
    """Sign a test identity token. Production verifiers use the same check."""
    header = _b64_json({"alg": "HS256", "typ": "JWT"})
    body = _b64_json(payload)
    signature = hmac.new(secret.encode("utf-8"), f"{header}.{body}".encode("ascii"), hashlib.sha256)
    return f"{header}.{body}.{_b64(signature.digest())}"


def _header_and_claims(token: str) -> tuple[dict, dict, bytes, bytes]:
    try:
        header_seg, body_seg, signature_seg = token.split(".")
    except ValueError as exc:
        raise AuthError("id_token") from exc
    try:
        header = json.loads(_b64_decode(header_seg))
        claims = json.loads(_b64_decode(body_seg))
        signature = _b64_decode(signature_seg)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise AuthError("id_token") from exc
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise AuthError("id_token")
    signing_input = f"{header_seg}.{body_seg}".encode("ascii")
    return header, claims, signing_input, signature


def _verify_hs256(signing_input: bytes, signature: bytes, secret: str) -> None:
    if not secret:
        raise AuthError("id_token")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if len(signature) != len(expected) or not hmac.compare_digest(expected, signature):
        raise AuthError("id_token")


def _b64_int(value: str) -> int:
    raw = _b64_decode(value)
    return int.from_bytes(raw, "big")


def _rsa_key(jwk: dict):
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers

    if jwk.get("kty") != "RSA" or "n" not in jwk or "e" not in jwk:
        raise AuthError("jwks")
    return RSAPublicNumbers(_b64_int(str(jwk["e"])), _b64_int(str(jwk["n"]))).public_key()


def _jwks(provider: OidcProvider) -> dict:
    if provider.jwks:
        return provider.jwks
    if not provider.jwks_uri or provider.http_get is None:
        raise AuthError("jwks")
    payload = provider.http_get(provider.jwks_uri)
    if not isinstance(payload, dict):
        raise AuthError("jwks")
    return payload


def _verify_rs256(signing_input: bytes, signature: bytes, provider: OidcProvider, kid: str) -> None:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    document = _jwks(provider)
    keys = document.get("keys")
    if not isinstance(keys, list) or not keys:
        raise AuthError("jwks")
    matched = False
    for jwk in keys:
        if not isinstance(jwk, dict):
            continue
        if jwk.get("use") not in (None, "sig"):
            continue
        if jwk.get("alg") not in (None, "RS256"):
            continue
        if kid and jwk.get("kid") != kid:
            continue
        matched = True
        key = _rsa_key(jwk)
        try:
            key.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
        except InvalidSignature:
            continue
        return
    if not matched:
        raise AuthError("jwks")
    raise AuthError("id_token")


def verify_id_token(
    token: str,
    provider: OidcProvider,
    *,
    nonce: str,
    now: float | None = None,
) -> dict:
    """Validate signature plus iss, aud, azp, exp, and nonce. Returns the claims."""
    header, claims, signing_input, signature = _header_and_claims(token)
    algorithm = header.get("alg")
    if algorithm == "HS256":
        _verify_hs256(signing_input, signature, provider.client_secret)
    elif algorithm == "RS256":
        _verify_rs256(signing_input, signature, provider, str(header.get("kid") or ""))
    else:
        raise AuthError("id_token")
    if not provider.issuer or claims.get("iss") != provider.issuer:
        raise AuthError("iss")
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience_ok = audience == provider.client_id
    elif isinstance(audience, list):
        audience_ok = provider.client_id in audience
    else:
        audience_ok = False
    if not audience_ok:
        raise AuthError("aud")
    # Several audiences require azp. A single audience rejects azp only when
    # the claim is present and names a different client.
    azp = claims.get("azp")
    several = isinstance(audience, list) and len(audience) > 1
    if several and azp != provider.client_id:
        raise AuthError("azp")
    if not several and azp is not None and azp != provider.client_id:
        raise AuthError("azp")
    current = time.time() if now is None else now
    try:
        expires = int(claims["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("exp") from exc
    if expires + 60 < current:
        raise AuthError("exp")
    if "nbf" in claims:
        try:
            not_before = int(claims["nbf"])
        except (TypeError, ValueError) as exc:
            raise AuthError("exp") from exc
        if not_before > current + 60:
            raise AuthError("exp")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not nonce or not _equal(token_nonce, nonce):
        raise AuthError("nonce")
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject:
        raise AuthError("missing_sub")
    return claims


def exchange_code(
    provider: OidcProvider, *, code: str, verifier: str, nonce: str
) -> str:
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
    if not isinstance(payload, dict) or not payload.get("id_token"):
        raise AuthError("id_token")
    claims = verify_id_token(str(payload["id_token"]), provider, nonce=nonce)
    return str(claims["sub"])
