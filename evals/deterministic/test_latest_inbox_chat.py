"""Latest-N inbox requests must retain the grounded report delivery path."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from evals.deterministic.test_gmail import _api_message, _install_fake_gmail_modules, _token_file
from evals.deterministic.test_inbox_chat import build, seed
from pu.db import connect
from pu.orchestration.inbox_chat import (
    is_inbox_request,
    latest_attention_markdown,
    latest_inbox_limit,
    latest_inbox_table,
)
from pu.tools import gmail


@pytest.mark.parametrize('message,limit', [
    ('Kiểm tra 10 email gần nhất giúp anh, xem có gì cần chú ý không?', 10),
    ('Đọc 5 email mới nhất', 5),
    ('Check the latest 12 emails', 12),
    ('Review 3 recent emails', 3),
    ('Check my latest emails', 10),
    ('Kiểm tra 200 email gần nhất', 100),
])
def test_latest_request_routes_with_bounded_count(message, limit):
    assert is_inbox_request(message)
    assert latest_inbox_limit(message) == limit


@pytest.mark.parametrize('message', [
    'Đừng kiểm tra 10 email gần nhất', 'Gửi 10 email gần nhất cho Acme',
    'Hướng dẫn tạo prompt xem 10 email gần nhất', 'Delete my latest emails',
])
def test_latest_route_does_not_override_mutation_or_negation(message):
    assert not is_inbox_request(message)


def test_latest_scan_uses_current_gmail_membership_across_dates_not_old_local_rows(tmp_path, monkeypatch):
    conn = connect(tmp_path)
    _token_file(tmp_path)
    current = datetime.now(UTC)
    old = str(int((current - timedelta(days=20)).timestamp() * 1000))
    stale = gmail.normalize_message(_api_message(id='archived', date_ms=str(int(current.timestamp() * 1000))))
    gmail.upsert_messages(conn, [stale])
    captured = _install_fake_gmail_modules(monkeypatch, [
        _api_message(id='older-inbox', date_ms=old), _api_message(id='new-inbox'),
    ])
    scan = json.loads(gmail.make_recent_scan_tool(conn, tmp_path).fn(max_results=2))
    assert scan['fresh'] and [e['gmail_id'] for e in scan['messages']] == ['new-inbox', 'older-inbox']
    assert captured['list']['labelIds'] == ['INBOX']
    assert captured['list']['maxResults'] == 2 and 'q' not in captured['list']
    assert scan['start'] == scan['messages'][-1]['internal_date']


def test_empty_fresh_inbox_does_not_resurrect_local_mail_but_failure_is_explicit(tmp_path, monkeypatch):
    conn = connect(tmp_path)
    gmail.upsert_messages(conn, [gmail.normalize_message(_api_message(id='stale'))])

    def sync(*args, status, **kwargs):
        status.update(ok=True, message_ids=[])
        return 'empty inbox'

    monkeypatch.setattr(gmail, 'sync', sync)
    scan = json.loads(gmail.make_recent_scan_tool(conn, tmp_path).fn())
    assert scan['fresh'] and scan['messages'] == []

    def failure(*args, status, **kwargs):
        status.update(ok=False)
        return 'Gmail unavailable'

    monkeypatch.setattr(gmail, 'sync', failure)
    scan = json.loads(gmail.make_recent_scan_tool(conn, tmp_path).fn())
    assert not scan['fresh'] and scan['warning'] == 'Gmail unavailable'
    assert len(scan['messages']) == 1


def test_latest_ten_facade_researches_older_partner_and_attaches_report(tmp_path, monkeypatch):
    app, _, collected = build(tmp_path, monkeypatch)
    seed(app, old=True)
    current = datetime.now(UTC)
    for index in range(10):
        app.conn.execute(
            'INSERT INTO crm_emails(gmail_id,sender_name,sender_email,subject,body_text,internal_date) VALUES(?,?,?,?,?,?)',
            (f'promo-{index}', 'Newsletter', 'noreply@updates.example', 'Weekly newsletter', 'Unsubscribe', (current - timedelta(hours=index)).isoformat()),
        )
    app.conn.commit()
    expected = [f'promo-{i}' for i in range(9)] + ['acme.example-old']
    seen = {}

    def sync(*args, status, **kwargs):
        seen.update(kwargs)
        status.update(ok=True, limited=True, message_ids=expected)
        return 'synced latest 10'

    monkeypatch.setattr(gmail, 'sync', sync)
    result = app.respond('Kiểm tra 10 email gần nhất giúp anh, xem có gì cần chú ý không?', source='dashboard')
    assert seen['max_messages'] == 10 and 'start' not in seen and 'recent_days' not in seen
    assert result.tool_calls[0]['tool'] == 'scan_inbox_recent'
    assert '**10 email gần nhất trong Gmail INBOX**' in result.reply
    assert '| 10 | Acme' in result.reply and 'promo-9' not in result.reply
    assert len(collected) == 1 and len(result.reports) == 1 and result.reports[0]['rubric_version'] == 'report-quality-rubric-v8'
    assert '.pu/reports/' not in result.reply and 'quality gate hoàn toàn' not in result.reply
    assert len(result.inbox_validation) == 10


def test_latest_table_escapes_untrusted_subject_and_flags_only_subject_signals():
    messages = [{'subject':'Security alert | <img src=x> [click](https://evil.example)', 'sender_name':'A\nB', 'internal_date':'2026-10-17T23:00:00+00:00'}]
    table = latest_inbox_table(messages)
    assert '18/10/2026, 06:00' in table and '¦' in table and '<img' not in table
    assert table.splitlines()[-1].count('|') == 5
    assert '[click](https://evil.example)' not in table
    attention = latest_attention_markdown(messages)
    assert 'Email #1' in attention and 'dựa trên tiêu đề' in attention and 'xác minh' in attention
    assert 'evil.example' not in attention


def test_today_request_keeps_today_scan():
    assert is_inbox_request('Kiểm tra email mới nhất hôm nay')
    assert latest_inbox_limit('Kiểm tra email mới nhất hôm nay') is None
