"""Stop crosses the real HTTP handler and does not become a model retry."""

import io
import json
import threading
from types import SimpleNamespace

import pytest

from pu.config import Settings
from pu.core.cancellation import RunCancelled
from pu.db import connect
from pu.identity.directory import provision_user
from pu.identity.session import SESSION_COOKIE, AuthStore
from pu.ops import dashboard
from pu.ops.chat_runs import active_chat, chat_lock, check_cancelled, stop_chat


def _session(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    user = provision_user(conn)
    conn.commit()
    conn.close()
    settings = Settings(home=home)
    settings.ensure_home()
    monkeypatch.setattr("pu.config.load_settings", lambda: settings)
    monkeypatch.setattr("pu.ops.dashboard.load_settings", lambda: settings)
    issued = AuthStore(home).issue_session(user)
    return user, issued


def post(path, payload, issued):
    handler = object.__new__(dashboard.Handler)
    body = json.dumps(payload).encode()
    handler.path = path
    handler.headers = {
        "Host": "127.0.0.1:8765",
        "Content-Length": str(len(body)),
        "Cookie": f"{SESSION_COOKIE}={issued.session_id}",
        "X-CSRF-Token": issued.csrf_token,
    }
    handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
    handler.send_response = lambda status: None
    handler.send_header = lambda *args: None
    handler.end_headers = lambda: None
    handler.do_POST()
    return handler.wfile.getvalue().decode()


def test_stop_is_scoped_and_cleans_up_after_completion(tmp_path, monkeypatch):
    user, issued = _session(tmp_path, monkeypatch)
    with active_chat('run-a', user.user_id) as first, active_chat('run-b', user.user_id) as second:
        assert json.loads(post('/api/chat/stop', {'request_id': 'run-a'}, issued))['accepted']
        assert first.is_set() and not second.is_set()
        with pytest.raises(RunCancelled):
            check_cancelled(first)
        with pytest.raises(ValueError), active_chat('run-a', user.user_id):
            pass
    assert not stop_chat('run-a', user.user_id)
    assert not stop_chat({'invalid': 'input'}, user.user_id)
    with pytest.raises(PermissionError, match="no authenticated principal"):
        stop_chat('run-b', '')


def test_cancelled_waiter_never_runs_when_another_chat_owns_the_lock():
    lock = threading.Lock()
    lock.acquire()
    signal = threading.Event()
    signal.set()
    try:
        with pytest.raises(RunCancelled), chat_lock(lock, signal):
            pytest.fail('A queued cancelled chat started')
        assert lock.locked()
    finally:
        lock.release()


def test_stream_acknowledges_before_work_and_cancel_is_terminal(tmp_path, monkeypatch):
    user, issued = _session(tmp_path, monkeypatch)
    stages = []

    def work(message, emit, *, cancel_event):
        stages.append('started')
        emit('text', {'delta': 'Partial reply'})
        assert stop_chat('test-stream', user.user_id)
        emit('text', {'delta': 'Must not appear'})
        stages.append('must-not-run')

    monkeypatch.setattr(dashboard, 'chat_stream', work)
    data = post('/api/chat/stream', {'message': 'hello', 'request_id': 'test-stream'}, issued)
    events = [json.loads(line[6:]) for line in data.splitlines() if line.startswith('data: ')]
    assert events[0] == {'kind': 'chat_started', 'request_id': 'test-stream'}
    assert events[-1]['kind'] == 'done' and events[-1]['cancelled']
    assert 'Must not appear' not in data and stages == ['started']
    assert not stop_chat('test-stream', user.user_id)


def test_cancelled_agent_releases_lock_and_records_interrupted_turn(monkeypatch):
    calls, exchanges = [], []

    def respond(message, *, observer, **kwargs):
        observer('text', {'delta': 'Partial'})
        signal.set()
        observer('text', {'delta': 'ignored'})
        calls.append('retry-or-complete')

    signal = threading.Event()
    agent = SimpleNamespace(respond=respond, session=SimpleNamespace(add_exchange=lambda *a, **kw: exchanges.append((a, kw))))
    monkeypatch.setattr(dashboard, 'get_agent', lambda: agent)
    monkeypatch.setattr(dashboard, 'maybe_rotate_session', lambda a: None)
    with pytest.raises(RunCancelled):
        dashboard.chat_stream('hello', lambda *a: None, cancel_event=signal)
    assert not calls and len(exchanges) == 1
    assert exchanges[0][1]['meta']['cancelled']
    acquired = []

    def next_turn():
        got_lock = dashboard.agent_lock.acquire(timeout=.5)
        acquired.append(got_lock)
        if got_lock:
            dashboard.agent_lock.release()

    next_thread = threading.Thread(target=next_turn)
    next_thread.start()
    next_thread.join(timeout=1)
    assert acquired == [True]


def test_cancelling_at_research_start_does_not_leave_a_running_workflow(tmp_path, monkeypatch):
    from evals.deterministic.test_inbox_chat import build

    app, _, _ = build(tmp_path, monkeypatch)

    def observer(kind, event):
        if kind == 'workflow_started':
            raise RunCancelled()

    with pytest.raises(RunCancelled):
        app.run_research_workflow(observer=observer)
    rows = app.conn.execute('SELECT status,error FROM workflow_runs').fetchall()
    assert len(rows) == 1 and rows[0]['status'] == 'failed'
    assert rows[0]['error'] == 'Cancelled by user'
    assert app.conn.execute('SELECT COUNT(*) FROM workspace_reports').fetchone()[0] == 0
