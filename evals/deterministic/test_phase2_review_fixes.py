"""Fixes from the independent review of PR #10.

A and B are synthetic principals. The identity provider is an in-process fake.
No real client secret or customer token is used.
"""

from __future__ import annotations

import base64
import json
import sqlite3
import threading
import time
from datetime import UTC, datetime

import pytest

from pu.config import Settings
from pu.db import connect
from pu.identity.crypto import _encrypt_enc1, decrypt, encrypt, is_legacy_ciphertext
from pu.identity.oidc import AuthError, OidcProvider, sign_hs256, verify_id_token
from pu.identity.session import AuthStore
from pu.persistence.ownership import install_owner_match_triggers

TOKEN_KEY = "phase2-review-key-xxxx"
ISSUER = "https://idp.test"
CLIENT = "pu-test"
SECRET = "test-client-secret-xx"


def _claims(**overrides):
    payload = {
        "sub": "subject-a",
        "iss": ISSUER,
        "aud": CLIENT,
        "exp": int(time.time()) + 600,
        "nonce": "nonce-a",
    }
    payload.update(overrides)
    return payload


def _provider(**kwargs) -> OidcProvider:
    values = {
        "authorization_endpoint": "https://idp.test/authorize",
        "token_endpoint": "https://idp.test/token",
        "client_id": CLIENT,
        "redirect_uri": "https://app.test/callback",
        "client_secret": SECRET,
        "issuer": ISSUER,
    }
    values.update(kwargs)
    return OidcProvider(**values)


def test_concurrent_connect_does_not_race_trigger_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    first = connect(home)
    names = {
        row[0]
        for row in first.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger' AND name LIKE '%owner_match%'"
        )
    }
    first.close()
    assert "agent_events_owner_match_insert_v1" in names
    assert "tool_audit_events_owner_match_update_v1" in names
    assert "proposed_actions_owner_match_insert_v1" in names
    assert "agent_events_owner_match_insert" not in names

    errors: list[str] = []
    barrier = threading.Barrier(6)

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            conn = connect(home)
            try:
                install_owner_match_triggers(conn)
                conn.execute("SELECT COUNT(*) FROM schema_migrations WHERE version = 9006").fetchone()
            finally:
                conn.close()
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert errors == []
    assert all(not thread.is_alive() for thread in threads)


def test_episodes_update_refreshes_the_fts_index(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    conn.execute(
        "INSERT INTO episodes(happened_at, summary) VALUES('2026-10-21', 'alphafact')"
    )
    conn.commit()
    episode_id = conn.execute("SELECT id FROM episodes").fetchone()[0]
    conn.execute("UPDATE episodes SET summary = 'betafact' WHERE id = ?", (episode_id,))
    conn.commit()
    fresh = conn.execute(
        "SELECT summary FROM episodes_fts WHERE episodes_fts MATCH 'betafact'"
    ).fetchall()
    stale = conn.execute(
        "SELECT summary FROM episodes_fts WHERE episodes_fts MATCH 'alphafact'"
    ).fetchall()
    conn.close()
    assert [row[0] for row in fresh] == ["betafact"]
    assert list(stale) == []


def test_dashboard_briefing_service_reads_through_the_harness(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "gmail-token.json").write_text("{}", encoding="utf-8")
    settings = Settings(home=home)
    settings.ensure_home()
    connect(home).close()
    called: list[str] = []

    def sync(*_args, **_kwargs):
        from pu.harness.gateway import harness_execute_active

        assert harness_execute_active()
        called.append("sync")
        return "synced"

    def read_availability(*_args, **_kwargs):
        from pu.harness.gateway import harness_execute_active

        assert harness_execute_active()
        called.append("calendar")
        return {
            "status": "unknown",
            "slots": [],
            "events": [],
            "checked_sources": [],
            "warnings": [],
            "timezone": "Asia/Ho_Chi_Minh",
        }

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            base = datetime(2026, 10, 21, 8, 30, tzinfo=UTC)
            return base if tz is None else base.astimezone(tz)

    from pu.ops.briefing import BriefingService, briefing_service

    monkeypatch.setattr("pu.tools.gmail.sync", sync)
    monkeypatch.setattr("pu.reporting.availability.read_availability", read_availability)
    monkeypatch.setattr("pu.ops.briefing.datetime", _Frozen)
    monkeypatch.setattr(BriefingService, "model_configured", lambda self: True)
    monkeypatch.setattr("pu.config.load_settings", lambda: settings)
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: settings)

    from pu.ops.dashboard import load_settings

    worker = briefing_service(load_settings().home, start=True)
    try:
        assert worker.app_factory is None
        worker.cycle()
    finally:
        worker.close()
        if worker.thread is not None:
            worker.thread.join(timeout=5)
    assert worker.thread is not None and not worker.thread.is_alive()
    assert "sync" in called
    assert "calendar" in called


def test_id_token_checks_iss_aud_exp_nonce_and_rs256():
    provider = _provider()
    now = time.time()
    good = verify_id_token(
        sign_hs256(_claims(), SECRET), provider, nonce="nonce-a", now=now
    )
    assert good["sub"] == "subject-a"
    listed = verify_id_token(
        sign_hs256(_claims(aud=["other", CLIENT]), SECRET),
        provider,
        nonce="nonce-a",
        now=now,
    )
    assert listed["aud"] == ["other", CLIENT]
    with pytest.raises(AuthError) as iss:
        verify_id_token(
            sign_hs256(_claims(iss="https://evil.test"), SECRET),
            provider,
            nonce="nonce-a",
            now=now,
        )
    assert iss.value.code == "iss"
    with pytest.raises(AuthError) as aud:
        verify_id_token(
            sign_hs256(_claims(aud="other-client"), SECRET),
            provider,
            nonce="nonce-a",
            now=now,
        )
    assert aud.value.code == "aud"
    with pytest.raises(AuthError) as expired:
        verify_id_token(
            sign_hs256(_claims(exp=int(now) - 120), SECRET),
            provider,
            nonce="nonce-a",
            now=now,
        )
    assert expired.value.code == "exp"
    with pytest.raises(AuthError) as nonce:
        verify_id_token(sign_hs256(_claims(), SECRET), provider, nonce="other", now=now)
    assert nonce.value.code == "nonce"
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode().rstrip("=")
    body = base64.urlsafe_b64encode(json.dumps(_claims()).encode()).decode().rstrip("=")
    with pytest.raises(AuthError) as none_alg:
        verify_id_token(f"{header}.{body}.", provider, nonce="nonce-a", now=now)
    assert none_alg.value.code == "id_token"

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()

    def b64_int(value: int) -> str:
        length = max((value.bit_length() + 7) // 8, 1)
        return base64.urlsafe_b64encode(value.to_bytes(length, "big")).decode().rstrip("=")

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "alg": "RS256",
                "use": "sig",
                "kid": "k1",
                "n": b64_int(numbers.n),
                "e": b64_int(numbers.e),
            }
        ]
    }
    rsa_provider = _provider(jwks=jwks, client_secret="")
    rsa_header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "typ": "JWT", "kid": "k1"}).encode()
    ).decode().rstrip("=")
    rsa_body = base64.urlsafe_b64encode(json.dumps(_claims()).encode()).decode().rstrip("=")
    signing = f"{rsa_header}.{rsa_body}".encode()
    signature = key.sign(signing, padding.PKCS1v15(), hashes.SHA256())
    rsa_sig = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    token = f"{rsa_header}.{rsa_body}.{rsa_sig}"
    assert verify_id_token(token, rsa_provider, nonce="nonce-a", now=now)["sub"] == "subject-a"
    tampered = token[:-2] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(AuthError) as bad_sig:
        verify_id_token(tampered, rsa_provider, nonce="nonce-a", now=now)
    assert bad_sig.value.code == "id_token"


def test_enc2_binds_aad_and_migrates_enc1(tmp_path, monkeypatch):
    monkeypatch.setenv("PU_TOKEN_KEY", TOKEN_KEY)
    blob = encrypt(b"secret-token", owner_user_id="owner-a", connection_id="conn-a")
    assert not is_legacy_ciphertext(blob)
    assert decrypt(blob, owner_user_id="owner-a", connection_id="conn-a") == b"secret-token"
    with pytest.raises(ValueError, match="ciphertext"):
        decrypt(blob, owner_user_id="owner-a", connection_id="conn-b")
    assert b"secret-token" not in base64.urlsafe_b64decode(blob.encode())

    home = tmp_path / "home"
    home.mkdir()
    opened = connect(home)
    owner = opened.execute("SELECT user_id FROM identity_local WHERE singleton = 1").fetchone()[0]
    opened.close()
    store = AuthStore(home)
    legacy = _encrypt_enc1(json.dumps({"access_token": "legacy-token"}).encode())
    connection_id = "legacy-conn"
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute(
            """INSERT INTO oauth_connections(id, owner_user_id, provider, token_ciphertext)
               VALUES(?,?,?,?)""",
            (connection_id, owner, "gmail", legacy),
        )
    seen: list[str] = []
    assert (
        store.use_oauth_connection(
            connection_id,
            owner_user_id=owner,
            provider_call=lambda token: seen.append(token["access_token"]) or token["access_token"],
        )
        == "legacy-token"
    )
    assert seen == ["legacy-token"]
    row = sqlite3.connect(home / "state.db").execute(
        "SELECT token_ciphertext FROM oauth_connections WHERE id=?", (connection_id,)
    ).fetchone()
    assert not is_legacy_ciphertext(row[0])
    assert (
        decrypt(row[0], owner_user_id=owner, connection_id=connection_id).decode().find("legacy-token")
        >= 0
    )


def test_reveal_not_found_and_sqlite_schema_stay_hidden(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    connect(home).close()
    settings = Settings(home=home)
    settings.ensure_home()
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: settings)
    monkeypatch.setattr("pu.config.load_settings", lambda: settings)
    from pu.ops.dashboard import reveal_path, run_query

    missing = reveal_path("notes/missing.txt")
    assert missing == {"error": "not found"}
    assert str(home) not in json.dumps(missing)
    blocked = run_query({"sql": "SELECT name FROM sqlite_schema"})
    assert blocked.get("rows") in (None, [])
    assert "error" in blocked
    assert "sqlite_schema" not in json.dumps(blocked.get("rows"))


def test_no_cookie_request_rejects_a_rebound_host():
    import io

    from pu.ops.dashboard import Handler

    handler = object.__new__(Handler)
    body = b"{}"
    handler.path = "/api/chat/stop"
    handler.headers = {"Host": "rebind.example", "Content-Length": "2"}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    statuses: list[int] = []
    handler.send_response = statuses.append
    handler.send_header = lambda *_args: None
    handler.end_headers = lambda: None
    handler.do_POST()
    assert statuses == [403]
    assert json.loads(handler.wfile.getvalue())["error"] == "loopback_host"
