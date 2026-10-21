"""Concise, source-linked chat presentation of an already evaluated report."""

from __future__ import annotations

import re
from urllib.parse import quote

from pu.reporting.citations import build_citation_presentation
from pu.tools.report_delivery import report_can_release

_QUESTIONS = {
    "representative_authority": "Ai là đầu mối được ủy quyền và pháp nhân ký hợp đồng?",
    "contact_role": "Người liên hệ giữ vai trò gì, ai trực tiếp phụ trách công việc?",
    "pilot_department": "Phạm vi thử nghiệm và phòng ban tham gia là gì?",
    "pilot_users": "Có bao nhiêu người dùng tham gia thử nghiệm?",
    "input_documents": "Cần chuẩn bị tài liệu, dữ liệu mẫu và đầu ra nào?",
    "source_systems": "Cần tích hợp với hệ thống nào, quyền truy cập đến đâu?",
    "security_requirements": "Dữ liệu được xử lý ở đâu, ai được truy cập và lưu giữ bao lâu?",
    "decision_owner": "Ai quyết định và tiêu chí nghiệm thu/thành công là gì?",
    "budget": "Chi phí đào tạo, triển khai và vận hành dự kiến bao nhiêu?",
    "timeline": "Mốc bắt đầu, thời gian thử nghiệm và bàn giao dự kiến khi nào?",
}


def render_partner_brief(payload):
    presentation = build_citation_presentation(payload)
    sources = {source["id"]: source for source in payload.get("sources", []) if not source.get("derived")}

    def cite(text):
        def replace(match):
            sid = match[1]
            item = presentation.get(sid, {})
            if item.get("public") and item.get("url"):
                return f"[{item['number']}]({quote(item['url'], safe=':/?#@!$&*+,;=%')})"
            source = sources.get(sid, {})
            url = source.get("metadata", {}).get("gmail_url", "")
            if source.get("source_type") == "email" and url.startswith("https://mail.google.com/"):
                return f"[thư]({url})"
            return ""
        return re.sub(r"\[((?:S|W)\d+)\]", replace, str(text or "")).strip()

    def compact(text, limit=850):
        # Whole lines/sentences keep each retained fact's own citation; never
        # append citations borrowed from facts removed by shortening.
        text = str(text or "").strip()
        if len(text) <= limit:
            return cite(text)
        chunks = re.split(r"\n+|(?<=[.!?])\s+(?=[A-ZÀ-Ỹ])", text)
        kept = []
        for chunk in chunks:
            if kept and sum(map(len, kept)) + len(chunk) > limit:
                break
            kept.append(chunk)
        return cite("\n".join(kept))

    sections, metadata = payload.get("sections", {}), payload.get("metadata", {})
    lines = [compact(payload.get("executive_summary"), 700), ""]
    for key, label in (("company_context", "Thông tin công ty"), ("email_need", "Nội dung lời mời"), ("recent_updates", "Cập nhật công khai")):
        text = sections.get(key)
        if key == "company_context" and not text:
            text = sections.get("public_research") or sections.get("company")
        if text:
            lines += [f"**{label}:** {compact(text)}", ""]
    if not sections.get("recent_updates"):
        lines += ["Chưa có cập nhật gần đây được xác minh để đưa vào briefing này.", ""]
    identity = metadata.get("partner_identity", {})
    notes = [*identity.get("conflicts", []), *identity.get("affiliation_warnings", [])]
    notes += [item.get("description", "") if isinstance(item, dict) else str(item) for item in payload.get("contradictions", [])]
    notes = list(dict.fromkeys(note for note in notes if note))
    if notes:
        lines += ["**Điểm cần lưu ý:**", "", *["- " + cite(note) for note in notes[:5]], ""]
    if sections.get("meeting_preparation"):
        lines += ["**Chuẩn bị trao đổi:** " + compact(sections["meeting_preparation"], 450), ""]
    questions = []
    checklist = metadata.get("preparation_assessment", metadata.get("preparation_checklist", []))
    priority = ["representative_authority", "budget", "security_requirements", "decision_owner", "timeline", "pilot_department", "input_documents", "source_systems", "contact_role", "pilot_users"]
    for item in sorted(checklist, key=lambda item: priority.index(item["key"]) if item.get("key") in priority else len(priority)):
        if item.get("answer_status") == "provided" and item.get("state") in {"known", "self_reported"}:
            continue
        question = _QUESTIONS.get(item.get("key"))
        if question:
            questions.append(question)
    questions += [cite(item) for item in payload.get("missing_information", [])]
    questions = list(dict.fromkeys(questions))
    if questions:
        lines += ["**Câu hỏi còn thiếu:**", "", *["- " + question for question in questions[:6]], ""]
    availability = metadata.get("availability", {})
    events = availability.get("events", [])
    if events:
        lines += ["**Cuộc hẹn liên quan đã có trên lịch:**", ""]
        lines += [f"- {event.get('title', 'Cuộc hẹn')} · {event.get('start', '')}" for event in events[:3]]
        lines.append("")
    elif availability.get("status") == "available":
        lines += ["Chưa thấy cuộc hẹn liên quan trong phạm vi lịch đã kiểm tra.", ""]
    if not report_can_release(payload):
        lines.append("**Đánh giá còn sơ bộ:** báo cáo chưa vượt qua kiểm tra chất lượng; cần xác minh các khoảng trống trước khi duyệt gửi hoặc lưu tri thức.")
    return "\n".join(lines).strip()
