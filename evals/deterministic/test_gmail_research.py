"""Remote read contract, pagination and MIME bodies with an in-memory API."""

import json

import pytest

from evals.deterministic.test_gmail import _api_message, _b64url
from pu.db import connect
from pu.tools.gmail import _plain_text, normalize_message, upsert_messages
from pu.tools.gmail_research import GmailResearchReader, html_body_text, make_tools


class FakeGmail:
    def __init__(self, pages, messages, thread=None):
        self.pages, self.messages_by_id, self.thread = pages, messages, thread
        self.calls = []

    def users(self):
        return self

    def messages(self):
        return self

    def threads(self):
        return self

    def list(self, **options):
        self.calls.append(("list", options))
        data = self.pages[options.get("pageToken", "")]
        return type("Response", (), {"execute": lambda _: data})()

    def get(self, **options):
        self.calls.append(("get", options))
        data = self.thread if self.thread is not None else self.messages_by_id[options["id"]]
        return type("Response", (), {"execute": lambda _: data})()


def reader(tmp_path, monkeypatch, service):
    instance = GmailResearchReader(connect(tmp_path), tmp_path)
    monkeypatch.setattr(instance, "service", lambda: service)
    return instance


def test_search_pages_remote_results_and_does_not_mix_stale_local_rows(tmp_path, monkeypatch):
    old = _api_message(id="old", body="Old invitation", date_ms="1700000000000")
    old["payload"]["mimeType"] = "text/plain"
    service = FakeGmail({"": {"messages": [{"id": "old"}], "nextPageToken": "p2"}, "p2": {"messages": [{"id": "new"}]}},
                        {"old": old, "new": _api_message(id="new")})
    instance = reader(tmp_path, monkeypatch, service)
    upsert_messages(instance.conn, [normalize_message(_api_message(id="unrelated"))])
    result = json.loads(instance.search('"hợp tác" -in:trash', 10))
    assert result["fresh"] and not result["limited"]
    assert [row["gmail_id"] for row in result["messages"]] == ["old", "new"]
    assert result["messages"][0]["body_text"] == "Old invitation"
    assert service.calls[0][1]["q"] == '"hợp tác" -in:trash'
    assert service.calls[1][1]["pageToken"] == "p2"
    assert all(name in {"list", "get"} for name, _ in service.calls)


def test_search_marks_limit_and_rejects_repeated_pagination(tmp_path, monkeypatch):
    service = FakeGmail({"": {"messages": [{"id": "m1"}], "nextPageToken": "same"}, "same": {"messages": [], "nextPageToken": "same"}}, {"m1": _api_message()})
    instance = reader(tmp_path, monkeypatch, service)
    assert json.loads(instance.search("partnership", 1))["limited"]
    with pytest.raises(ValueError, match="phân trang lặp"):
        instance.search("partnership", 10)


def test_thread_retains_sent_reply_and_uses_newest_messages_with_limit_warning(tmp_path, monkeypatch):
    first, reply = _api_message(id="first", date_ms="1700000000000"), _api_message(id="reply", date_ms="1800000000000")
    reply["labelIds"] = ["SENT"]
    instance = reader(tmp_path, monkeypatch, FakeGmail({}, {}, thread={"messages": [reply, first]}))
    instance.conn.execute(
        """INSERT INTO crm_emails(gmail_id, thread_id, subject, internal_date)
           VALUES(?,?,?,?)""",
        ("seed-thread1", "thread1", "Seed", "2026-10-22T00:00:00+00:00"),
    )
    instance.conn.commit()
    result = json.loads(instance.thread("thread1", 1))
    assert result["limited"] and result["messages"][0]["gmail_id"] == "reply"
    assert result["messages"][0]["sent"] is True


def test_html_email_preserves_signature_links_and_excludes_active_content():
    html = '<style>secret style</style><p>Xin chào</p><div>Website: <a href="https://acme.example">Acme</a></div><script>sendAllKeys()</script>'
    result = html_body_text(html)
    assert "Website:" in result and "https://acme.example" in result
    assert "sendAllKeys" not in result and "secret style" not in result
    message = _api_message()
    message["payload"]["mimeType"] = "text/html"
    message["payload"]["body"]["data"] = _b64url(html)
    assert "Xin chào" in normalize_message(message)["body_text"]


def test_plain_alternative_wins_over_nested_html_and_text_attachments():
    payload = {"parts": [
        {"filename": "attachment.txt", "mimeType": "text/plain", "body": {"data": _b64url("not the email")}},
        {"parts": [{"mimeType": "text/html", "body": {"data": _b64url("<p>html</p>")}}]},
        {"mimeType": "text/plain", "body": {"data": _b64url("actual email")}},
    ]}
    assert _plain_text(payload) == "actual email"


def test_tools_are_read_only_and_report_truncated_bodies(tmp_path, monkeypatch):
    instance = reader(tmp_path, monkeypatch, FakeGmail({}, {}))
    raw = _api_message(body="x" * 33000)
    raw["payload"]["mimeType"] = "text/plain"
    row = instance.normalize(raw)
    assert row["body_truncated"] and len(row["body_text"]) == 32000
    assert all(not tool.side_effect and tool.capability == "email:read" for tool in make_tools(instance.conn, tmp_path))
