"""Login screen and OIDC session flow. LG-01..LG-06.

The identity provider is an in-process fake. No real client secret, mailbox,
or customer token is used.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sqlite3
import subprocess
import time
import urllib.parse
from pathlib import Path

import pytest

from pu.config import Settings
from pu.db import connect
from pu.identity.directory import provision_user
from pu.identity.oidc import OidcProvider, sign_hs256
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.session import SESSION_COOKIE, AuthStore, act_as
from pu.memory.semantic.store import SqliteFactStore
from pu.ops import dashboard
from pu.ops.dashboard import OIDC_REQUIRED_ENV

CLIENT_SECRET = "test-client-secret"
A_MARK = "lg-owner-marker-alpha"
B_MARK = "lg-owner-marker-beta"
STATIC = Path(__file__).resolve().parents[2] / "pu" / "ops" / "static"
JS = STATIC / "js"


def _open(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    other = provision_user(conn)
    conn.commit()
    conn.close()
    return home, other


def _bind(monkeypatch, home):
    settings = Settings(home=home)
    settings.ensure_home()
    monkeypatch.setattr("pu.config.load_settings", lambda: settings)
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: settings)
    return settings


def _clear_oidc_env(monkeypatch):
    for name in (
        *OIDC_REQUIRED_ENV,
        "PU_OIDC_JWKS_URI",
        "PU_OIDC_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


class _Handler:
    def __init__(self, method: str, path: str, headers: dict, body: bytes = b""):
        from pu.ops.dashboard import Handler

        self.statuses: list[int] = []
        self.sent: list[tuple[str, str]] = []
        handler = object.__new__(Handler)
        handler.path = path
        handler.headers = {"Host": "127.0.0.1:8765", **headers}
        handler.rfile = io.BytesIO(body)
        handler.wfile = io.BytesIO()
        handler.send_response = self.statuses.append
        handler.send_header = lambda key, value: self.sent.append((key, value))
        handler.end_headers = lambda: None
        if method == "GET":
            handler.do_GET()
        else:
            handler.do_POST()
        self.body = handler.wfile.getvalue()


def _set_cookie(sent: list[tuple[str, str]], name: str) -> str:
    for key, value in sent:
        if key == "Set-Cookie" and value.startswith(name + "="):
            return value
    raise AssertionError(name)


def _cookie_value(header: str) -> str:
    return header.split(";", 1)[0].split("=", 1)[1]


def _provider(http_post):
    return OidcProvider(
        authorization_endpoint="https://idp.test/authorize",
        token_endpoint="https://idp.test/token",
        client_id="pu-test",
        redirect_uri="https://app.test/api/auth/callback",
        client_secret=CLIENT_SECRET,
        issuer="https://idp.test",
        http_post=http_post,
    )


def _count(home: Path, sql: str) -> int:
    conn = sqlite3.connect(home / "state.db")
    try:
        return int(conn.execute(sql).fetchone()[0])
    finally:
        conn.close()


def _fact(home: Path, principal: Principal, content: str) -> None:
    with act_as(home, principal):
        conn = connect(home)
        try:
            SqliteFactStore(conn).add("login", content)
        finally:
            conn.close()


def _query(session_id: str, csrf: str, sql: str = "SELECT content FROM facts") -> _Handler:
    body = json.dumps({"sql": sql}).encode()
    return _Handler(
        "POST",
        "/api/query",
        {
            "Cookie": f"{SESSION_COOKIE}={session_id}",
            "X-CSRF-Token": csrf,
            "Content-Length": str(len(body)),
        },
        body,
    )


def test_lg01_logged_out_shell_has_login_and_no_user_payload(tmp_path, monkeypatch):
    home, other = _open(tmp_path)
    _bind(monkeypatch, home)
    _fact(home, other, A_MARK)
    page = _Handler("GET", "/", {})
    assert page.statuses == [200]
    html = page.body.decode()
    assert 'id="login-google"' in html
    assert "Đăng nhập với Google" in html
    assert "logged-out" in html
    assert A_MARK not in html
    data = _Handler("GET", "/api/data", {})
    assert data.statuses == [401]
    assert json.loads(data.body)["error"] == "no authenticated principal"
    assert A_MARK.encode() not in data.body
    blocked = _Handler("GET", "/", {"Host": "rebind.example"})
    assert blocked.statuses == [403]
    assert json.loads(blocked.body)["error"] == "loopback_host"
    assert "Đăng nhập với Google".encode() not in blocked.body

    issued = AuthStore(home).issue_session(other)
    AuthStore(home).revoke_session(issued.session_id)
    revoked_cookie = {"Cookie": f"{SESSION_COOKIE}={issued.session_id}"}
    shell = _Handler("GET", "/", revoked_cookie)
    assert shell.statuses == [200]
    assert "Đăng nhập với Google" in shell.body.decode()
    assert A_MARK.encode() not in shell.body
    api = _Handler("GET", "/api/data", revoked_cookie)
    assert api.statuses == [401]
    assert json.loads(api.body)["error"] == "session_revoked"
    assert A_MARK.encode() not in api.body
    metrics = _Handler("GET", "/metrics", revoked_cookie)
    assert metrics.statuses == [401]
    script = _Handler("GET", "/static/js/auth.js", revoked_cookie)
    assert script.statuses == [200]
    assert any(key == "Content-Type" and "javascript" in value for key, value in script.sent)
    assert A_MARK.encode() not in script.body
    traversal = _Handler("GET", "/static/../dashboard.py", revoked_cookie)
    assert traversal.statuses == [401]
    assert dashboard._is_login_shell("/static/../dashboard.py") is False
    assert dashboard._is_login_shell("/api/data") is False
    assert dashboard._is_login_shell("/metrics") is False

    index = (STATIC / "index.html").read_text()
    assert index.index('id="login-screen"') < index.index("<main>")
    assert index.index("/static/js/auth.js") < index.index("/static/js/main.js")
    css = (STATIC / "style.css").read_text()
    assert "body.logged-out nav" in css
    assert "body.logged-out main" in css
    assert "body.logged-out #dock" in css


def test_lg02_fake_oidc_lands_on_overview_for_that_owner(tmp_path, monkeypatch):
    home, other = _open(tmp_path)
    _bind(monkeypatch, home)
    seen: dict = {}

    def http_post(_url, form):
        seen["form"] = dict(form)
        claims = {
            "sub": "subject-lg-02",
            "iss": "https://idp.test",
            "aud": "pu-test",
            "exp": int(time.time()) + 600,
            "nonce": seen["nonce"],
        }
        token = sign_hs256(claims, CLIENT_SECRET)
        seen["token"] = token
        return {"id_token": token}

    monkeypatch.setattr("pu.ops.dashboard._oidc_provider_from_env", lambda: _provider(http_post))
    login = _Handler("GET", "/api/auth/login", {})
    assert login.statuses == [200]
    payload = json.loads(login.body)
    query = urllib.parse.parse_qs(urllib.parse.urlparse(payload["authorization_url"]).query)
    seen["nonce"] = query["nonce"][0]
    transaction = _cookie_value(_set_cookie(login.sent, "pu_oidc"))
    callback = _Handler(
        "GET",
        "/api/auth/callback?code=auth-code&state=" + query["state"][0],
        {"Cookie": f"pu_oidc={transaction}"},
    )
    assert callback.statuses == [302]
    locations = [value for key, value in callback.sent if key == "Location"]
    assert locations == ["/#overview"]
    assert callback.body == b""
    session_header = _set_cookie(callback.sent, SESSION_COOKIE)
    assert "HttpOnly" in session_header
    assert "Secure" in session_header
    assert "SameSite=Lax" in session_header
    session_id = _cookie_value(session_header)
    assert session_id not in locations[0]
    assert seen["token"] not in locations[0]
    assert seen["token"].encode() not in callback.body
    clear_oidc = [
        value for key, value in callback.sent
        if key == "Set-Cookie" and value.startswith("pu_oidc=")
    ]
    assert clear_oidc and "Max-Age=0" in clear_oidc[0]

    row = sqlite3.connect(home / "state.db").execute(
        "SELECT id, csrf_token, owner_user_id, workspace_id FROM auth_sessions"
    ).fetchone()
    assert row[0] == session_id
    assert row[1] not in session_header
    assert row[1] not in locations[0]
    assert row[1].encode() not in callback.body
    owner = Principal(PrincipalKind.USER, row[2], row[3])
    _fact(home, owner, A_MARK)
    _fact(home, other, B_MARK)

    csrf = _Handler("GET", "/api/auth/csrf", {"Cookie": f"{SESSION_COOKIE}={session_id}"})
    assert csrf.statuses == [200]
    csrf_body = json.loads(csrf.body)
    assert csrf_body["csrf_token"] == row[1]
    assert csrf_body["user_id"] == row[2]
    own = _query(session_id, csrf_body["csrf_token"])
    assert own.statuses == [200]
    own_body = own.body.decode()
    assert A_MARK in own_body
    assert B_MARK not in own_body

    other_session = AuthStore(home).issue_session(other)
    foreign = _query(other_session.session_id, other_session.csrf_token)
    assert foreign.statuses == [200]
    foreign_body = foreign.body.decode()
    assert B_MARK in foreign_body
    assert A_MARK not in foreign_body


def test_lg03_csrf_from_the_session_gates_posts_and_the_ui_sends_it(tmp_path, monkeypatch):
    home, other = _open(tmp_path)
    _bind(monkeypatch, home)
    issued = AuthStore(home).issue_session(other)
    csrf = _Handler(
        "GET", "/api/auth/csrf", {"Cookie": f"{SESSION_COOKIE}={issued.session_id}"}
    )
    token = json.loads(csrf.body)["csrf_token"]
    assert token == issued.csrf_token
    bare = {
        "Cookie": f"{SESSION_COOKIE}={issued.session_id}",
        "Content-Length": "2",
    }
    missing = _Handler("POST", "/api/chat/stop", bare, b"{}")
    assert missing.statuses == [403]
    assert json.loads(missing.body)["error"] == "csrf"
    wrong = {**bare, "X-CSRF-Token": "not-the-session-token"}
    mismatched = _Handler("POST", "/api/chat/stop", wrong, b"{}")
    assert mismatched.statuses == [403]
    assert json.loads(mismatched.body)["error"] == "csrf"
    allowed = _Handler("POST", "/api/chat/stop", {**bare, "X-CSRF-Token": token}, b"{}")
    assert allowed.statuses == [200]
    logout_missing = _Handler("POST", "/api/auth/logout", bare, b"{}")
    assert logout_missing.statuses == [403]
    assert json.loads(logout_missing.body)["error"] == "csrf"

    util = (JS / "util.js").read_text()
    assert 'headers["X-CSRF-Token"] = puCsrf' in util
    auth = (JS / "auth.js").read_text()
    assert "/api/auth/csrf" in auth
    assert "localStorage" not in auth
    assert "sessionStorage" not in auth
    assert "document.cookie" not in auth
    assert "id_token" not in auth
    for path in sorted(JS.glob("*.js")):
        text = path.read_text()
        for match in re.finditer(r"method\s*:\s*[\"']POST[\"']", text):
            window = text[max(0, match.start() - 220) : match.end() + 220]
            assert "puMutateHeaders()" in window, path.name


def test_lg04_logout_revokes_the_session_and_the_next_call_is_logged_out(tmp_path, monkeypatch):
    home, other = _open(tmp_path)
    _bind(monkeypatch, home)
    _fact(home, other, A_MARK)
    issued = AuthStore(home).issue_session(other)
    logout = _Handler(
        "POST",
        "/api/auth/logout",
        {
            "Cookie": f"{SESSION_COOKIE}={issued.session_id}",
            "X-CSRF-Token": issued.csrf_token,
            "Content-Length": "2",
        },
        b"{}",
    )
    assert logout.statuses == [200]
    assert json.loads(logout.body) == {"ok": True}
    cleared = _set_cookie(logout.sent, SESSION_COOKIE)
    assert "Max-Age=0" in cleared
    assert "HttpOnly" in cleared and "Secure" in cleared
    revoked = sqlite3.connect(home / "state.db").execute(
        "SELECT revoked_at FROM auth_sessions WHERE id=?", (issued.session_id,)
    ).fetchone()
    assert revoked[0]
    cookie = {"Cookie": f"{SESSION_COOKIE}={issued.session_id}"}
    nxt = _Handler("GET", "/api/auth/csrf", cookie)
    assert nxt.statuses == [401]
    assert json.loads(nxt.body)["error"] == "session_revoked"
    assert A_MARK.encode() not in nxt.body
    again = _query(issued.session_id, issued.csrf_token)
    assert again.statuses == [403]
    assert json.loads(again.body)["error"] == "session_revoked"
    assert A_MARK.encode() not in again.body
    page = _Handler("GET", "/", cookie)
    assert page.statuses == [200]
    assert "Đăng nhập với Google" in page.body.decode()
    assert A_MARK.encode() not in page.body


@pytest.mark.parametrize(
    ("mode", "phrase"),
    [
        ("state", "State không khớp"),
        ("nonce", "Nonce không khớp"),
        ("exp", "đã hết hạn"),
    ],
)
def test_lg05_callback_errors_show_html_and_create_no_session(
    tmp_path, monkeypatch, mode, phrase
):
    home, _other = _open(tmp_path)
    _bind(monkeypatch, home)
    seen: dict = {"called": False}

    def http_post(_url, _form):
        seen["called"] = True
        nonce = "wrong-nonce" if mode == "nonce" else seen["nonce"]
        exp = int(time.time()) - 180 if mode == "exp" else int(time.time()) + 600
        token = sign_hs256(
            {
                "sub": "subject-lg-05",
                "iss": "https://idp.test",
                "aud": "pu-test",
                "exp": exp,
                "nonce": nonce,
            },
            CLIENT_SECRET,
        )
        seen["token"] = token
        return {"id_token": token}

    monkeypatch.setattr("pu.ops.dashboard._oidc_provider_from_env", lambda: _provider(http_post))
    login = _Handler("GET", "/api/auth/login", {})
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(json.loads(login.body)["authorization_url"]).query
    )
    seen["nonce"] = query["nonce"][0]
    transaction = _cookie_value(_set_cookie(login.sent, "pu_oidc"))
    state = "not-the-state" if mode == "state" else query["state"][0]
    callback = _Handler(
        "GET",
        f"/api/auth/callback?code=lg05-secret-code&state={state}",
        {"Cookie": f"pu_oidc={transaction}"},
    )
    assert callback.statuses == [400]
    assert any(
        key == "Content-Type" and value.startswith("text/html") for key, value in callback.sent
    )
    page = callback.body.decode()
    assert "Không đăng nhập được" in page
    assert phrase in page
    assert "Không có phiên nào được tạo" in page
    assert "lg05-secret-code" not in page
    assert seen.get("token", "missing-token") not in page
    assert not any(
        key == "Set-Cookie" and value.startswith(f"{SESSION_COOKIE}=")
        for key, value in callback.sent
    )
    assert _count(home, "SELECT COUNT(*) FROM auth_sessions") == 0
    assert _count(home, "SELECT COUNT(*) FROM oidc_subjects") == 0
    if mode == "state":
        assert seen["called"] is False


def test_lg06_missing_oidc_config_lists_variables_without_crashing(tmp_path, monkeypatch):
    home, _other = _open(tmp_path)
    _bind(monkeypatch, home)
    _clear_oidc_env(monkeypatch)
    login = _Handler("GET", "/api/auth/login", {})
    assert login.statuses == [400]
    body = json.loads(login.body)
    assert body["error"] == "oidc_not_configured"
    assert body["required"] == list(OIDC_REQUIRED_ENV)
    assert body["missing"] == list(OIDC_REQUIRED_ENV)
    assert CLIENT_SECRET not in login.body.decode()
    callback = _Handler("GET", "/api/auth/callback?code=x&state=y", {})
    assert callback.statuses == [400]
    page = callback.body.decode()
    assert "Không đăng nhập được" in page
    for name in OIDC_REQUIRED_ENV:
        assert name in page
    assert not any(
        key == "Set-Cookie" and value.startswith(f"{SESSION_COOKIE}=")
        for key, value in callback.sent
    )
    assert _count(home, "SELECT COUNT(*) FROM auth_sessions") == 0
    auth = (JS / "auth.js").read_text()
    for name in OIDC_REQUIRED_ENV:
        assert name in auth

    monkeypatch.setenv("PU_OIDC_AUTHORIZATION_ENDPOINT", "https://idp.test/authorize")
    monkeypatch.setenv("PU_OIDC_TOKEN_ENDPOINT", "https://idp.test/token")
    monkeypatch.setenv("PU_OIDC_CLIENT_ID", "pu-test")
    monkeypatch.setenv("PU_OIDC_REDIRECT_URI", "https://app.test/api/auth/callback")
    partial = json.loads(_Handler("GET", "/api/auth/login", {}).body)
    assert partial["error"] == "oidc_not_configured"
    assert partial["required"] == list(OIDC_REQUIRED_ENV)
    assert partial["missing"] == ["PU_OIDC_ISSUER"]


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_lg_login_screen_runtime():
    result = subprocess.run(
        [shutil.which("node"), "--test", str(Path(__file__).with_name("test_dashboard_login.cjs"))],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
