"""Existing invitation → conversation → research → read-only briefing.

Reuse the established multi-agent/evaluation pipeline, but search across dates
and disambiguate invitations before spending public research calls.
"""

from __future__ import annotations

import re

from pu.orchestration.inbox_chat import InboxChatBriefing, _inbox_text
from pu.reporting.scheduling import briefing_window

_INVITATIONS = '{"hợp tác" partnership collaboration cooperation "giới thiệu giải pháp" "đề nghị trao đổi" "business meeting"}'


def is_partner_brief_request(message):
    text = _inbox_text(message)
    if re.search(r"\b(code|source|prompt)\b|huong dan|vi du", text):
        return False
    if re.search(r"\b(?:khong|dung|do not|don't)\s+(?:duoc\s+|can\s+)?(?:doc|tim|kiem tra|nghien cuu|read|search|research|check)\b", text):
        return False
    # A prohibition of writes is a constraint, not an intent to send mail.
    text = re.sub(r"\b(?:khong|chua|dung|do not|don't|without)\s+(?:duoc\s+|can\s+)?(?:gui|send|forward|tao|create|xoa|delete)\b[^.;\n]*", "", text)
    if re.search(r"\b(?:gui|send|forward|xoa|delete)\b|tao (?:su kien|lich)", text):
        return False
    mail = re.search(r"\b(?:gmail|emails?|mails?|inbox|thu|hop thu)\b|loi moi hop tac", text)
    invitation = re.search(r"loi moi|moi hop tac|hop tac|doi tac|partnership|collaboration|invitation", text)
    action = re.search(r"danh gia|nghien cuu|kiem tra|xem|tim|brief|research|review|assess|find|check", text)
    return bool(mail and invitation and action)


class PartnerBriefing(InboxChatBriefing):
    targeted = True

    def scan(self, message, notify):
        # Search remote Gmail, never substitute an unfiltered stale local inbox.
        query = '-in:spam -in:trash -in:sent ' + _INVITATIONS
        if re.search(r"\binbox\b|hop thu den", _inbox_text(message)):
            query = "in:inbox " + query
        return self.tool("search_gmail", notify, {"query": query, "max_results": 50})

    def select_partners(self, partners, message, append):
        text = _inbox_text(message)
        matches = [group for group in partners if any(
            value and re.search(r"(?<!\w)" + re.escape(_inbox_text(value)) + r"(?!\w)", text)
            for value in (group["company"], group["domain"])
        )]
        if matches:
            return matches
        # A named company must not silently resolve to the sole unrelated hit.
        if re.search(r"(?:cua|from|ve cong ty)\s+[A-ZÀ-Ỹ][\w.-]+", message):
            append("Chưa khớp được công ty anh nêu với các lời mời đã tìm thấy; cần tên công ty hoặc tiêu đề thư chính xác hơn.")
            return []
        if len(partners) <= 1 or re.search(r"tat ca|cac loi moi|all invitations", text):
            if not partners:
                append("Chưa xác định được lời mời trực tiếp đủ bằng chứng trong kết quả đã đọc. Anh có thể bổ sung tên công ty hoặc tiêu đề thư để tìm chính xác hơn.")
            return partners
        options = []
        for group in partners[:8]:
            email = group["emails"][0]
            options.append(f"- **{group['company']}** — {email['subject']} ({email['internal_date'][:10]})")
        append("Có nhiều lời mời phù hợp; cần anh chọn công ty hoặc tiêu đề thư để tránh đánh giá nhầm:\n\n" + "\n".join(options))
        return []

    def candidates(self, scan):
        readable = []
        for email in scan["messages"]:
            if email.get("body_available") is False or not email.get("body_text"):
                self.record_validation(email, "uncertain", "Chưa đọc được nội dung thư; snippet không đủ làm bằng chứng lời mời.")
            else:
                readable.append(email)
        return super().candidates({**scan, "messages": readable})

    def conversation(self, group, notify, append):
        emails = {email["gmail_id"]: email for email in group["emails"]}
        for thread_id in dict.fromkeys(e.get("thread_id") for e in group["emails"]):
            if not thread_id:
                continue
            try:
                result = self.tool("read_gmail_thread", notify, {"thread_id": thread_id, "max_messages": 30})
                for email in result["messages"]:
                    emails[email["gmail_id"]] = email
                if result.get("limited"):
                    append("Chuỗi thư dài: chỉ đọc 30 tin gần nhất, có thể thiếu ngữ cảnh cũ.")
            except Exception:
                append("Chưa đọc được toàn bộ chuỗi thư; đánh giá dựa trên email tìm thấy và chưa loại trừ có phản hồi đổi lịch.")
        for email in emails.values():
            if email.get("body_truncated") or email.get("body_available") is False:
                append("Một email thiếu nội dung đầy đủ; các chi tiết chưa thấy cần được xác minh lại.")
        original = group["emails"][0]
        url = original.get("display_url")
        title = re.sub(r"[\[\]<>\n]", " ", original["subject"])
        label = f"[{title}]({url})" if url else title
        append(f"**Lời mời:** {label} · nhận {original['internal_date'][:10]}. Đã đọc {len(emails)} tin liên quan.")
        return {**group, "emails": sorted(emails.values(), key=lambda e: e["internal_date"])}

    def scheduling_window(self, emails, message):
        return briefing_window(emails, user_message=message)

    def render_report(self, payload):
        from pu.reporting.chat_brief import render_partner_brief
        return render_partner_brief(payload)
