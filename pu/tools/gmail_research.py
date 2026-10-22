"""Bounded Gmail search and conversation reads; no remote mutations."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from html.parser import HTMLParser

from pu.tools.registry import Tool


def html_body_text(html: str) -> str:
    class Reader(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
            self.hidden = 0

        def handle_starttag(self, tag, attrs):
            if tag in {"script", "style", "head"}:
                self.hidden += 1
            if not self.hidden and tag in {"br", "div", "p", "li", "tr"}:
                self.parts.append("\n")
            if tag == "a" and not self.hidden:
                href = dict(attrs).get("href", "")
                if href.startswith(("https://", "http://", "mailto:")):
                    self.parts.append(" " + href.removeprefix("mailto:") + " ")

        def handle_endtag(self, tag):
            if tag in {"script", "style", "head"}:
                self.hidden = max(0, self.hidden - 1)
            if not self.hidden and tag in {"div", "p", "li", "tr"}:
                self.parts.append("\n")

        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)

    reader = Reader()
    reader.feed(html)
    return re.sub(r"\n{3,}", "\n\n", "".join(reader.parts)).strip()


class GmailResearchReader:
    def __init__(self, conn, home):
        self.conn, self.home = conn, home

    def service(self):
        from pu.tools.gmail import _load_credentials

        credentials = _load_credentials(self.home)
        if credentials is None:
            raise ValueError("Chưa kết nối được Gmail; hãy kết nối Gmail rồi thử lại.")
        from googleapiclient.discovery import build
        return build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def normalize(self, raw):
        from pu.tools.gmail import _BODY_LIMIT, _plain_text, normalize_message

        row = normalize_message(raw)
        headers = {h.get("name", "").lower(): h.get("value", "")
                   for h in raw.get("payload", {}).get("headers", [])}
        row.update(
            display_url="https://mail.google.com/mail/u/0/#all/" + row["gmail_id"],
            reply_to=headers.get("reply-to", ""),
            to=headers.get("to", ""),
            sent="SENT" in raw.get("labelIds", []),
            body_truncated=len(_plain_text(raw.get("payload", {}))) > _BODY_LIMIT,
            body_available=bool(row["body_text"]),
        )
        return row

    def search(self, query, max_results=50):
        if not query.strip() or len(query) > 1000 or not 1 <= max_results <= 100:
            raise ValueError("Cần query 1–1000 ký tự và giới hạn 1–100 email.")
        service, ids, token, seen_tokens = self.service(), [], None, set()
        while len(ids) < max_results:
            options = {"userId": "me", "q": query, "maxResults": min(100, max_results - len(ids))}
            if token:
                options["pageToken"] = token
            page = service.users().messages().list(**options).execute()
            ids.extend(item["id"] for item in page.get("messages", []) if item["id"] not in ids)
            token = page.get("nextPageToken")
            if not token:
                break
            if token in seen_tokens:
                raise ValueError("Gmail trả phân trang lặp; chưa xác nhận tìm kiếm đầy đủ.")
            seen_tokens.add(token)
        rows = [self.normalize(service.users().messages().get(userId="me", id=mid, format="full").execute())
                for mid in ids[:max_results]]
        from pu.tools.gmail import upsert_messages
        upsert_messages(self.conn, rows)
        now = datetime.now(UTC).isoformat()
        return json.dumps({"fresh": True, "limited": bool(token), "query": query,
                           "checked_at": now, "start": min((r["internal_date"] for r in rows), default=now),
                           "end": now, "messages": rows, "warning": ""}, ensure_ascii=False)

    def thread(self, thread_id, max_messages=30):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", thread_id) or not 1 <= max_messages <= 100:
            raise ValueError("Thread ID hoặc giới hạn email không hợp lệ.")
        from pu.agents.isolation import refuse_before_provider

        refuse_before_provider(self.conn, thread_id=thread_id)
        raw = self.service().users().threads().get(userId="me", id=thread_id, format="full").execute()
        messages = sorted(raw.get("messages", []), key=lambda item: int(item.get("internalDate", 0)))
        rows = [self.normalize(item) for item in messages[-max_messages:]]
        from pu.tools.gmail import upsert_messages
        upsert_messages(self.conn, rows)
        return json.dumps({"fresh": True, "thread_id": thread_id, "messages": rows,
                           "limited": len(messages) > max_messages,
                           "checked_at": datetime.now(UTC).isoformat()}, ensure_ascii=False)


def make_tools(conn, home):
    reader = GmailResearchReader(conn, home)
    return [
        Tool(name="search_gmail", description="Search Gmail using Gmail query syntax across dates; returns exact matched IDs and full available bodies. Read-only. Use for an existing invitation, not just today's mail.",
             input_schema={"type": "object", "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 1000}, "max_results": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["query"], "additionalProperties": False},
             fn=reader.search, capability="email:read", required_scope="email:read", external=True),
        Tool(name="read_gmail_thread", description="Read a Gmail conversation by an observed thread_id, including sent replies and latest scheduling changes. Never infer an ID. Read-only.",
             input_schema={"type": "object", "properties": {"thread_id": {"type": "string", "minLength": 1, "maxLength": 200}, "max_messages": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["thread_id"], "additionalProperties": False},
             fn=reader.thread, capability="email:read", required_scope="email:read", external=True),
    ]
