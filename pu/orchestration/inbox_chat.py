"""Chat is the delivery surface for inbox → new partner → grounded report."""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime
from email.utils import parseaddr
from urllib.parse import quote, urlparse
from zoneinfo import ZoneInfo

from pu.core.interfaces.agents import AgentResult
from pu.core.interfaces.llm import LLMRequest
from pu.core.interfaces.tools import ToolContext
from pu.evaluation.issues import report_issues
from pu.harness.audit import redact
from pu.ops.briefing import PERSONAL_DOMAINS
from pu.orchestration.partner_validation import (
    POLICY_VERSION,
    REQUEST_RULES,
    precheck,
    request_passages,
    subject_signal,
    validate_request,
)
from pu.reporting.citations import build_citation_presentation
from pu.reporting.evidence import StructuredReportBuilder
from pu.reporting.identity import RESEARCH_POLICY_VERSION, candidate_website, domain_of
from pu.reporting.research_plan import source_priority
from pu.reporting.workspace import WorkspaceRepository
from pu.tools.report_delivery import public_research_sources, report_can_release


def _inbox_text(message):
    text = unicodedata.normalize("NFD", message.lower().replace("đ", "d"))
    return "".join(c for c in text if not unicodedata.combining(c))


def latest_inbox_limit(message):
    text = _inbox_text(message)
    if not re.search(r"gan nhat|moi nhat|\b(latest|recent|last)\b", text):
        return None
    # Explicit day filters belong to the day-specific flow, not an all-time scan.
    if re.search(r"hom nay|\btoday\b|hom qua|\byesterday\b", text):
        return None
    count = re.search(r"\b(\d+)\s*(?:(?:latest|recent|last)\s+)?(?:emails?|mails?|thu)\b", text)
    return max(1, min(int(count.group(1)) if count else 10, 100))


def is_inbox_request(message):
    text = _inbox_text(message)
    if re.search(
        r"\b(gui|send|forward|xoa|delete|code|prompt)\b|huong dan|vi du|(?:khong (?:can|duoc)|dung|do not|don't) (?:doc|kiem tra|read|check)",
        text,
    ):
        return False
    return bool(
        re.search(r"\b(emails?|mails?|inbox|hop thu)\b", text)
        and (latest_inbox_limit(message) is not None or re.search(r"hom nay|moi|inbox|today|new|hop thu", text))
    )


def latest_inbox_table(messages):
    def cell(value):
        # The lightweight chat renderer splits on every pipe and does not
        # implement Markdown backslash escapes. Keep untrusted cells as text.
        return " ".join(str(value or "").split()).translate(str.maketrans({
            '|': '¦', '[': '［', ']': '］', '<': '＜', '>': '＞',
            '*': '＊', '_': '＿', '`': '｀', '\\': '＼',
        }))

    lines = ["| # | Người gửi | Chủ đề | Thời gian (giờ Việt Nam) |", "|---|---|---|---|"]
    for index, email in enumerate(messages, 1):
        try:
            stamp = datetime.fromisoformat(email["internal_date"])
            received = stamp.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).strftime("%d/%m/%Y, %H:%M") if stamp.tzinfo else "Chưa xác định"
        except (KeyError, TypeError, ValueError):
            received = "Chưa xác định"
        sender = email.get("sender_name") or email.get("sender_email") or "Chưa rõ người gửi"
        lines.append(f"| {index} | {cell(sender)}{' · Chưa đọc' if email.get('unread') else ''} | {cell(email.get('subject'))} | {received} |")
    return "\n".join(lines)


def latest_attention_markdown(messages):
    """Subject signals, not claims that a security or billing incident is real."""
    signals = []
    for index, email in enumerate(messages, 1):
        subject = _inbox_text(email.get("subject") or "")
        reason = None
        if re.search(r"bao mat|mat khau|dang nhap|\b(security|password|oauth|sign.in|verify your identity)\b", subject):
            reason = "có dấu hiệu thông báo bảo mật hoặc truy cập tài khoản"
        elif re.search(r"qua han|thanh toan that bai|\b(overdue|payment failed)\b", subject):
            reason = "có dấu hiệu vấn đề thanh toán hoặc quá hạn"
        elif re.search(r"doi lich|duoc doi|rescheduled|event .* updated", subject):
            reason = "có dấu hiệu thay đổi lịch sự kiện"
        if reason:
            signals.append(f"- **Email #{index}:** tiêu đề {reason}; cần mở email để xác minh chi tiết.")
    return "\n".join(["**Thông báo khác nên kiểm tra (dựa trên tiêu đề):**", "", *signals[:5]]) if signals else ""


def calendar_markdown(snapshot):
    window = (snapshot or {}).get("scheduling_window") or {}
    lines = ["### " + (window.get("label") if window.get("basis") in {"user", "email", "alternative", "suggested"} else "Lịch trống trong tuần của anh"), ""]
    if not snapshot or snapshot.get("status") == "unknown":
        return "\n".join(lines + [*(snapshot or {}).get("warnings", []), "Em chưa đọc đủ dữ liệu lịch để gợi ý giờ hẹn đáng tin cậy."])
    sources = snapshot.get("checked_sources", [])
    if not any("Google" in source for source in sources):
        lines += [
            "Gợi ý theo lịch đã lưu trong PU; **chưa kiểm tra Google Calendar** và lịch của đối tác.",
            "",
        ]
    else:
        lines += ["Đã đối chiếu " + ", ".join(sources) + "; chưa biết lịch của đối tác.", ""]
    if window.get("warning"):
        lines += [window["warning"], ""]
    slots = snapshot.get("slots", [])
    if slots:
        lines += ["| Ngày | Khung giờ | Thời lượng |", "| --- | --- | --- |"]
    for slot in slots[:3]:
        label = slot['label']
        try:
            day = datetime.fromisoformat(slot['start']).astimezone(ZoneInfo(snapshot.get('timezone') or 'Asia/Ho_Chi_Minh'))
            label = f"{('Thứ Hai', 'Thứ Ba', 'Thứ Tư', 'Thứ Năm', 'Thứ Sáu', 'Thứ Bảy', 'Chủ Nhật')[day.weekday()]} {day:%d/%m/%Y}"
        except (KeyError, ValueError, TypeError):
            pass
        lines.append(f"| {label} | {slot['window']} | {slot['duration_minutes']} phút |")
    if not slots:
        lines.append(f"Chưa tìm được khoảng trống đủ {snapshot.get('duration_minutes', 45)} phút trong phạm vi đã kiểm tra.")
    if snapshot.get("start") and snapshot.get("end"):
        start = datetime.fromisoformat(snapshot['start'])
        end = datetime.fromisoformat(snapshot['end'])
        lines += ["", f"Phạm vi kiểm tra: {start:%H:%M %d/%m/%Y} đến trước {end:%H:%M %d/%m/%Y}."]
    try:
        checked = datetime.fromisoformat(snapshot["checked_at"])
        if checked.tzinfo is not None:
            checked = checked.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
            lines += ["", f"Cập nhật lúc {checked:%H:%M, %d/%m/%Y} · giờ Việt Nam."]
    except (KeyError, ValueError, TypeError):
        pass
    return "\n".join(lines)


def inline_report(payload):
    """A source-backed conversational introduction; the full report stays attached."""
    sources = {s["id"]: s for s in payload.get("sources", []) if not s.get("derived")}
    presentation = build_citation_presentation(payload)
    public_sources = sorted(public_research_sources(payload),
                            key=lambda source: source_priority(source.get("url") or ""), reverse=True)[:8]
    used_public = set()

    def link(url):
        return quote(url, safe=":/?#[]@!$&'*+,;=%")

    def cite(text):
        def replace(match):
            sid = match.group(1)
            if sid not in sources:
                return ""
            item = presentation.get(sid) or {}
            if item.get("public") and item.get("url"):
                used_public.add(sid)
                return f"[{item['number']}]({link(item['url'])})"
            return ""

        rendered = re.sub(r"\[(S\d+|W\d+)\]", replace, text or "")
        rendered = re.sub(r"[ \t]+([.,;:!?])", r"\1", rendered)
        return re.sub(r"[ \t]{2,}", " ", rendered).strip()

    def excerpt(text, limit=450):
        text = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", text.strip(), flags=re.MULTILINE)
        text = " ".join(text.split())
        if len(text) <= limit:
            return text
        end = max(text.rfind(". ", 0, limit), text.rfind("; ", 0, limit))
        end = end + 1 if end >= limit // 2 else text.rfind(" ", 0, limit)
        result = text[:end].rstrip() + ("" if text[:end].endswith(".") else "…")
        refs = list(dict.fromkeys(re.findall(r"\[(?:S|W)\d+\]", text)))
        return result + " " + "".join(ref for ref in refs if ref not in result)

    company = payload.get("metadata", {}).get("company") or payload["title"]
    lines = [
        f"Dưới đây là những thông tin em tìm được về **{company}**:",
        "",
        cite(payload.get("executive_summary")),
        "",
    ]
    sections = payload.get("sections", {})
    view = payload.get("metadata", {}).get("reading_view") or {}
    compact = view.get("version") == "partner-brief-v2"
    public = sections.get("company_context", "") if compact else sections.get("public_research", "")
    bullets = re.findall(r"^\s*(?:[-*]|\d+\.)\s+(.+)$", public, re.MULTILINE)
    if bullets:
        highlights = [excerpt(bullet, 260 if compact else 450) for bullet in bullets[:3 if compact else 5]]
    else:
        highlights = [
            f"**{label}:** {excerpt(sections[key])}"
            for key, label in (
                ("public_research", "Lĩnh vực và giải pháp"),
                ("company_scale", "Quy mô và vận hành"),
                ("business_context", "Bối cảnh công nghệ"),
            )
            if sections.get(key)
        ]
        if compact and public:
            highlights = [excerpt(public, 550)]
    if highlights:
        lines += (
            ["**Các điểm nổi bật:**", ""]
            + [f"{i}. {cite(item)}" for i, item in enumerate(highlights, 1)]
            + [""]
        )
    if sections.get("email_need"):
        lines += ["**Nhu cầu từ email:** " + cite(excerpt(sections["email_need"], 550)), ""]
    preparation = sections.get("meeting_preparation") or ""
    if preparation:
        # Only the first objective/proposal belongs in the chat; questions and
        # full pilot details remain in the attached, evaluated report.
        first = next((part.strip() for part in preparation.splitlines() if part.strip()), "")
        lines += ["**Gợi ý chuẩn bị:** " + cite(excerpt(first, 320)), ""]
    affiliation_warnings = (
        payload.get("metadata", {}).get("partner_identity", {}).get("affiliation_warnings", [])
    )
    gaps = payload.get("missing_information") or []
    if affiliation_warnings and not compact:
        # Contact-authority gaps are already described by the exact warning.
        gaps = [gap for gap in gaps if not any(word in gap.casefold() for word in (
            "đại diện", "có phải nhân sự", "affiliation", "xác minh người gửi",
        ))]
    notes = list(dict.fromkeys([*affiliation_warnings, *gaps[:2]]))
    if compact:
        notes = view.get("open_items", [])[:2]
    for conflict in ([] if compact else payload.get("contradictions") or []):
        description = conflict.get("description", "") if isinstance(conflict, dict) else str(conflict)
        refs = conflict.get("source_ids", []) if isinstance(conflict, dict) else []
        notes.append(description + " " + " ".join(f"[{sid}]" for sid in refs))
    if notes:
        lines += ["**Cần xác minh:**", "", *["- " + cite(note) for note in notes], ""]
    if report_can_release(payload):
        lines.append(
            "Báo cáo chi tiết được đính kèm bên dưới. Anh có thể mở đọc và chọn **Import vào sổ tay** để lưu báo cáo."
        )
    else:
        lines.append(
            "**Bản nháp cần xác minh thêm.** Anh có thể đọc báo cáo đính kèm và đối chiếu các nguồn bên dưới; hiện chưa thể duyệt lưu hoặc gửi."
        )
        issues = report_issues(payload.get("evaluation") or {})
        for issue in issues[:3]:
            lines.append("- " + cite(issue["message"]))
    # Every source cited in the chat remains listed, even beyond the preferred
    # eight-source limit. Numbering comes from the export contract.
    compact = (payload.get("metadata", {}).get("reading_view") or {}).get("version") == "partner-brief-v2"
    candidates = [*([] if compact else public_sources), *(sources[sid] for sid in sorted(used_public))]
    selected = {}
    for source in candidates:
        item = presentation.get(source["id"]) or {}
        if item.get("public"):
            selected.setdefault(item["number"], item)
    public_sources = [selected[number] for number in sorted(selected)]
    if public_sources:
        lines += ["", "**Nguồn tham khảo:**", ""]
        for source in public_sources:
            title = re.sub(
                r"[\r\n\[\]<>]", " ", source.get("label") or urlparse(source["url"]).hostname
            )
            # A Markdown ordered list would renumber gaps after selecting
            # sources, making its displayed numbers disagree with citations.
            lines.append(f"- [{source['number']}] [{title}]({link(source['url'])})")
    else:
        lines += [
            "",
            "Chưa đọc được nguồn công khai đủ dữ kiện; nội dung hiện dựa trên email và các tài liệu được cung cấp.",
        ]
    return "\n".join(lines)


class InboxChatBriefing:
    targeted = False

    def __init__(self, app):
        self.app = app
        self.repo = WorkspaceRepository(app.settings.home)
        self.calls = []
        self.validation = {}
        self.timings = {}

    def scan(self, message, notify):
        limit = latest_inbox_limit(message)
        return self.tool("scan_inbox_recent", notify, {"max_results": limit}) if limit else self.tool("scan_inbox_today", notify)

    def select_partners(self, partners, message, append):
        return partners

    def conversation(self, group, notify, append):
        return group

    def scheduling_window(self, emails, message):
        from pu.reporting.scheduling import meeting_window
        return meeting_window(emails, user_message=message)

    def render_report(self, payload):
        return inline_report(payload)

    @contextmanager
    def measure(self, phase):
        started = time.perf_counter()
        try:
            yield
        finally:
            self.timings[phase] = self.timings.get(phase, 0.0) + time.perf_counter() - started

    def record_validation(self, email, status, reason, **evidence):
        self.validation[email["gmail_id"]] = {
            "email_id": email["gmail_id"],
            "subject": email["subject"],
            "status": status,
            "reason": reason,
            "policy_version": POLICY_VERSION,
            **evidence,
        }

    def tool(self, name, notify, arguments=None):
        arguments = arguments or {}
        with self.measure("calendar" if name == "read_week_availability" else "inbox_scan"):
            result = self.app.tool_harness.execute(
                name,
                arguments,
                ToolContext(
                    principal="local-user", actor="chat-inbox", agent_id="inbox-briefing-agent",
                    request_id=str(uuid.uuid4()), scopes=frozenset({"email:read", "calendar:read"}) if self.targeted else self.app.tools.scopes(),
                    capabilities=frozenset({"email:read", "calendar:read"}) if self.targeted else self.app.tools.agent_capabilities(), observer=notify,
                ),
            )
        self.calls.append({"tool": name, "args": arguments, "output": result.output, "ok": result.ok})
        if not result.ok:
            raise ValueError(result.output)
        return json.loads(result.output)

    def candidates(self, scan):
        groups, excluded = {}, 0
        for email in scan["messages"]:
            status, reason = precheck(email)
            if status != "candidate":
                self.record_validation(email, status, reason)
                excluded += 1
                continue
            self.record_validation(email, "uncertain", "Chưa hoàn tất kiểm tra nội dung và lịch sử")
            address = parseaddr(email["sender_email"])[1].lower()
            _, _, sender_domain = address.rpartition("@")
            website = candidate_website(email)
            domain = domain_of(website) or sender_domain
            urls = re.findall(r"https?://[^\s<>\"()]+", email["body_text"] or "")
            urls = [url.rstrip(".,;") for url in urls if urlparse(url).hostname]
            if domain in PERSONAL_DOMAINS:
                urls = [
                    url
                    for url in urls
                    if urlparse(url).hostname not in PERSONAL_DOMAINS
                    and not any(
                        site in (urlparse(url).hostname or "")
                        for site in ("google.", "facebook.", "linkedin.", "youtube.")
                    )
                ]
                if not urls:
                    self.record_validation(
                        email, "uncertain", "Email cá nhân chưa có website nhận diện công ty"
                    )
                    excluded += 1
                    continue
                domain = (urlparse(urls[0]).hostname or domain).removeprefix("www.")
                website = "https://" + domain
            group = groups.setdefault(
                email["gmail_id"],
                {
                    "candidate_id": "email:" + email["gmail_id"],
                    "domain": domain,
                    "sender_domain": sender_domain,
                    "website": website,
                    "urls": set(),
                    "emails": [],
                },
            )
            group["urls"].update(urls)
            group["emails"].append(email)
        for group in groups.values():
            with self.repo.database.connection() as conn:
                rows = conn.execute(
                    "SELECT subject,body_text FROM crm_emails WHERE lower(sender_email) LIKE ? AND julianday(internal_date)<julianday(?) ORDER BY internal_date DESC LIMIT 3",
                    ("%@" + group["domain"], scan["start"]),
                ).fetchall()
                knowledge = conn.execute(
                    "SELECT c.content FROM knowledge_chunks c JOIN knowledge_sources s ON s.id=c.source_id WHERE s.enabled=1 AND c.content LIKE ? LIMIT 2",
                    ("%" + group["domain"] + "%",),
                ).fetchall()
            group["history"] = [
                {"subject": row["subject"], "body": row["body_text"][:1500]} for row in rows
            ]
            group["knowledge"] = [row[0][:1500] for row in knowledge]
        return list(groups.values()), excluded

    def classify(self, candidates, notify):
        decisions = []
        # Negative decisions must cover every message, including later pages.
        paged = []
        for group in candidates:
            for offset in range(0, len(group["emails"]), 10):
                paged.append(
                    {
                        **group,
                        "candidate_id": group["candidate_id"] + f"#{offset // 10}",
                        "emails": group["emails"][offset : offset + 10],
                        "original": group,
                    }
                )
        candidates = paged
        for offset in range(0, len(candidates), 5):
            batch = candidates[offset : offset + 5]
            content = [
                {
                    "candidate_id": item["candidate_id"],
                    "sender_domain": item["sender_domain"],
                    "emails": [
                        {
                            "id": e["gmail_id"],
                            "sender": e["sender_name"],
                            "subject": e["subject"],
                            "subject_signal": subject_signal(e["subject"])[0],
                            "body": (e["body_text"] or e["snippet"])[:3000],
                            "request_passages": request_passages(e),
                        }
                        for e in item["emails"]
                    ],
                    "older_correspondence": item["history"],
                    "internal_knowledge": item["knowledge"],
                    "website_candidates": sorted(item["urls"] | {item["website"]}),
                }
                for item in batch
            ]
            response = self.app.llm_provider.complete(
                LLMRequest(
                    model=self.app.settings.small_model or self.app.settings.model,
                    max_tokens=6000,
                    system="Nhận diện email kinh doanh cần chuẩn bị báo cáo cho người dùng hôm nay. "
                    + REQUEST_RULES
                    + "Mỗi ứng viên chỉ có một email. Không dùng bằng chứng của email khác, kể cả cùng người gửi hoặc cùng miền. Miền người gửi không quyết định công ty được nghiên cứu; dùng tên tự giới thiệu và website công ty ghi trong đúng email. "
                    "Phân loại từng email trong email_decisions bằng email_id, status (new_partner/existing_partner/not_partner/uncertain), reason. "
                    "Nếu email có đề nghị trực tiếp, tên tự giới thiệu và website công ty rõ ràng, miền gửi khác website chỉ là cảnh báo quyền đại diện chưa xác minh; không chọn needs_research=false chỉ vì khác miền. "
                    "needs_research=true cho MỌI yêu cầu kinh doanh trực tiếp đang cần xử lý, kể cả đã từng trao đổi hoặc là đối tác cũ. Lịch sử để bổ sung ngữ cảnh, không phải lý do bỏ qua email hẹn gặp. "
                    "Trao đổi trước về cùng cơ hội chưa chứng minh đã là đối tác cũ; chỉ kết luận có quan hệ cũ khi có bằng chứng dự án/hợp đồng/giao dịch trong lịch sử. Newsletter và báo cáo AI không chứng minh quan hệ đối tác. "
                    "Không thấy bằng chứng quan hệ cũ trong dữ liệu chỉ có nghĩa chưa tìm thấy, không khẳng định tuyệt đối chưa từng làm việc. "
                    "Workspace hoặc báo cáo nháp có sẵn không chứng minh đó là đối tác cũ. "
                    "Company phải lấy từ email, không bịa pháp nhân. Website phải thuộc website_candidates. "
                    'Trả duy nhất JSON {"partners":[{"candidate_id":"domain#0","is_new_partner":true,"needs_research":true,"company":"tên công ty có trong email","website":"URL đã cho","intent":"partnership|project|quotation|demo|business_meeting","direct_request":true,"request_evidence":{"email_id":"id","passage_id":"p0"},"reason":"nhu cầu và kết quả kiểm tra lịch sử","email_decisions":[{"email_id":"id","status":"new_partner","reason":"lý do"}]}]}, đúng một quyết định cho MỖI candidate_id và MỖI email. passage_id phải trỏ vào đoạn có đề nghị kinh doanh. Thiếu bằng chứng yêu cầu thì needs_research=false. Đối tác cũ có nhu cầu trực tiếp thì is_new_partner=false nhưng needs_research=true.',
                    messages=[{"role": "user", "content": json.dumps(content, ensure_ascii=False)}],
                )
            )
            notify(
                "llm",
                {
                    "agent_id": "email-partner-classifier",
                    "model": self.app.settings.small_model or self.app.settings.model,
                    "usage": {
                        "in": response.usage.input_tokens,
                        "out": response.usage.output_tokens,
                    },
                },
            )
            parsed = StructuredReportBuilder._parse_json(response.text)
            items = parsed.get("partners") if parsed else None
            if (
                not isinstance(items, list)
                or len(items) != len(batch)
                or {item.get("candidate_id") for item in items if isinstance(item, dict)}
                != {item["candidate_id"] for item in batch}
            ):
                raise ValueError(
                    "Model chưa trả đủ quyết định phân loại đối tác; chưa tự bỏ qua các email chưa phân loại."
                )
            for item in items:
                if not isinstance(item.get("is_new_partner"), bool) or not isinstance(
                    item.get("needs_research"), bool
                ):
                    raise TypeError("Kết quả phân loại đối tác không hợp lệ.")
                group = next(
                    group for group in batch if group["candidate_id"] == item["candidate_id"]
                )
                # Only verified evidence below may promote a message to eligible.
                email_decisions = item.get("email_decisions")
                if (
                    not isinstance(email_decisions, list)
                    or len(email_decisions) != len(group["emails"])
                    or {d.get("email_id") for d in email_decisions if isinstance(d, dict)}
                    != {e["gmail_id"] for e in group["emails"]}
                    or any(
                        not isinstance(d, dict)
                        or d.get("status")
                        not in {"new_partner", "existing_partner", "not_partner", "uncertain"}
                        for d in email_decisions
                    )
                ):
                    raise ValueError("Chưa có quyết định hợp lệ cho từng email; chưa tự research.")
                if isinstance(email_decisions, list):
                    for decision in email_decisions:
                        if not isinstance(decision, dict):
                            continue
                        email = next(
                            (
                                e
                                for e in group["emails"]
                                if e["gmail_id"] == decision.get("email_id")
                            ),
                            None,
                        )
                        status = {"existing_partner": "existing", "not_partner": "excluded"}.get(
                            decision.get("status"), "uncertain"
                        )
                        if email:
                            self.record_validation(
                                email,
                                status,
                                "Chưa đối chiếu được trích dẫn yêu cầu cho email này"
                                if decision.get("status") == "new_partner"
                                else str(decision.get("reason") or "Chưa đủ bằng chứng"),
                            )
                if item["needs_research"]:
                    verified, reason = validate_request(item, group["emails"])
                    if not verified:
                        attempted = item.get("request_evidence")
                        attempted = attempted if isinstance(attempted, dict) else {}
                        for email in group["emails"]:
                            if self.validation[email["gmail_id"]]["status"] == "uncertain" or email[
                                "gmail_id"
                            ] == attempted.get("email_id"):
                                self.record_validation(
                                    email,
                                    "uncertain",
                                    reason,
                                    attempted_evidence={
                                        "email_id": str(attempted.get("email_id") or "")[:200],
                                        "quote": str(attempted.get("quote") or "")[:3000],
                                        "passage_id": str(attempted.get("passage_id") or "")[:100],
                                        "company": str(item.get("company") or "")[:200],
                                        "intent": str(item.get("intent") or "")[:100],
                                    },
                                )
                        continue
                    verdict = next(
                        d for d in email_decisions if d["email_id"] == verified["email"]["gmail_id"]
                    )
                    if verdict["status"] not in {"new_partner", "existing_partner"}:
                        continue
                    self.record_validation(
                        verified["email"],
                        "eligible",
                        "Có yêu cầu kinh doanh trực tiếp cần chuẩn bị báo cáo",
                        relationship="new" if item["is_new_partner"] else "existing",
                        quote=verified["quote"],
                        intent=item["intent"],
                        company=verified["company"],
                        identity_conflicts=verified["identity"]["conflicts"],
                        affiliation_warnings=verified["identity"].get("affiliation_warnings", []),
                    )
                    company = verified["company"]
                    website = group["website"]
                    identity = {
                        **verified["identity"],
                        "website": website,
                        "sender_domain": group["sender_domain"],
                        "research_domain": group["domain"],
                    }
                    # Consolidate only after validating each individual message.
                    existing = next(
                        (
                            d
                            for d in decisions
                            if d["domain"] == group["domain"]
                            and d["company"].casefold() == company.casefold()
                        ),
                        None,
                    )
                    if existing:
                        existing["emails"].append(verified["email"])
                        existing["identity"]["conflicts"] = list(
                            dict.fromkeys(existing["identity"]["conflicts"] + identity["conflicts"])
                        )
                        if existing["identity"]["conflicts"]:
                            existing["identity"]["status"] = "conflicting"
                        existing["identity"]["affiliation_warnings"] = list(
                            dict.fromkeys(
                                existing["identity"].get("affiliation_warnings", [])
                                + identity.get("affiliation_warnings", [])
                            )
                        )
                    else:
                        decisions.append(
                            {
                                **group["original"],
                                "emails": [verified["email"]],
                                "company": company,
                                "website": website,
                                "is_new_partner": item["is_new_partner"],
                                "identity": identity,
                            }
                        )
        return decisions

    def partner_report(self, group, scan, calendar, notify):
        from pu.reporting.cache import company_evidence_is_current, reusable_company_sources
        from pu.reporting.policy import CURRENT_RUBRIC_VERSION
        from pu.tools.report_delivery import report_can_release

        research_domain = domain_of(group["website"])
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    POLICY_VERSION,
                    "report-quality-v2-targeted-v1" if self.targeted else "report-quality-v2",
                    CURRENT_RUBRIC_VERSION,
                    RESEARCH_POLICY_VERSION,
                    scan["start"],
                    research_domain,
                    group["company"],
                    sorted((e["gmail_id"], e.get("body_text") or e.get("snippet") or "") for e in group["emails"]),
                ],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        with self.repo.database.connection() as conn:
            cached = conn.execute(
                "SELECT workspace_id,payload_json FROM workspace_reports WHERE json_extract(payload_json,'$.metadata.inbox_fingerprint')=? ORDER BY created_at DESC LIMIT 1",
                (fingerprint,),
            ).fetchone()
        cached_company_sources = []
        company_checked_at = ""
        if cached:
            payload = json.loads(cached["payload_json"])
            if (
                payload.get("claims")
                and payload.get("sections")
                and not payload.get("metadata", {}).get("parse_fallback")
                and payload.get("metadata", {}).get("evidence_policy_version")
                == RESEARCH_POLICY_VERSION
                and payload.get("metadata", {}).get("quality_policy_version") == "report-quality-v2"
            ):
                from pu.reporting.availability import snapshot_is_current

                if company_evidence_is_current(payload):
                    enabled_ids = {s["id"] for s in self.repo.sources(cached["workspace_id"]) if s["enabled"]}
                    cached_company_sources = reusable_company_sources(payload, enabled_ids)
                    company_checked_at = payload["metadata"]["company_evidence_checked_at"]
                    expected_ids = {
                        s.get("metadata", {}).get("workspace_source_id") for s in payload.get("sources", [])
                        if not s.get("derived") and s.get("source_type") not in {"calendar"}
                    }
                    if (
                        expected_ids <= enabled_ids and report_can_release(payload)
                        and snapshot_is_current(payload.get("metadata", {}).get("availability", {}))
                        and str(payload["metadata"]["availability"].get("start", ""))[:10] == str(calendar.get("start", ""))[:10]
                        and all(payload["metadata"]["availability"].get(key) == calendar.get(key)
                                for key in ("slots", "status", "checked_sources", "timezone", "end", "duration_minutes", "scheduling_window"))
                    ):
                        notify("inbox_progress", {"stage": "report_cache", "company": group["company"]})
                        return cached["workspace_id"], payload
        workspace = next(
            (
                w
                for w in self.repo.list()
                if domain_of(w["website"]) == research_domain
            ),
            None,
        )
        workspace = workspace or self.repo.create(
            group["company"], group["website"], group["emails"][0]["sender_email"]
        )
        wid = workspace["id"]
        if cached and wid != cached["workspace_id"]:
            cached_company_sources = []
            company_checked_at = ""
        if workspace["company"] != group["company"]:
            with self.repo.database.connection() as conn:
                conn.execute(
                    "UPDATE research_workspaces SET company=? WHERE id=?", (group["company"], wid)
                )
        current_emails = []
        for email in sorted(group["emails"], key=lambda email: email["internal_date"]):
            current_emails.append(self.repo.add_source(
                wid,
                title=email["subject"][:300],
                source_type="email",
                content=f"Người gửi: {email['sender_name']} <{email['sender_email']}>\nNgày nhận: {email['internal_date']}\n{email['body_text'] or email['snippet']}",
                published_at=email["internal_date"],
                metadata={
                    "gmail_id": email["gmail_id"],
                    "gmail_url": email.get("display_url", ""),
                    "thread_id": email.get("thread_id", ""),
                    "sent": email.get("sent", False),
                    "body_truncated": email.get("body_truncated", False),
                    "untrusted_input": True,
                    "partner_identity": group.get("identity", {}),
                },
            ))
        from pu.reporting.collection import collect_partner_sources

        if cached_company_sources:
            from pu.reporting.availability import filter_partner_events

            snapshot = filter_partner_events(calendar, workspace)
            calendar_source = self.repo.add_source(
                wid, title="Lịch họp liên quan và giờ trống đã kiểm tra", source_type="calendar",
                content=json.dumps(snapshot, ensure_ascii=False),
                metadata={"automatic": True, "availability": snapshot},
            )
            sources = [*current_emails, *cached_company_sources, calendar_source]
            warnings = []
            notify("inbox_progress", {"stage": "calendar_refresh", "company": group["company"]})
        else:
            warnings = collect_partner_sources(
                self.repo,
                wid,
                app=self.app,
                calendar_snapshot=calendar,
                progress=lambda stage: notify(
                    "inbox_progress", {"stage": stage, "company": group["company"]}
                ),
            )
            from datetime import UTC, datetime

            company_checked_at = datetime.now(UTC).isoformat()
            sources, size = [], 0
            current_email_ids = {source['id'] for source in current_emails}
            for source in reversed(self.repo.sources(wid)):
                if self.targeted and source['source_type'] == 'email' and source['id'] not in current_email_ids:
                    continue
                if source["enabled"] and len(sources) < 30 and size + len(source["content"]) <= 110000:
                    sources.append(source)
                    size += len(source["content"])
            sources.reverse()
        result = self.app.run_research_workflow(
            "Viết báo cáo công ty để chuẩn bị trao đổi kinh doanh. Chỉ nghiên cứu đúng đối tác trong email đã cung cấp. "
            "Lịch sử liên hệ chỉ là ngữ cảnh; không suy đoán đây là đối tác cũ hoặc đã có hợp đồng. "
            "Bao gồm lĩnh vực hoạt động, sản phẩm/dịch vụ, nhu cầu email, tin có ngày xuất bản, người liên hệ, câu hỏi và lưu ý trước cuộc gặp. "
            "Không thay đối tác bằng công ty khác trong inbox. Chỉ dùng snapshot lịch đã cung cấp và đúng phạm vi scheduling_window; không tự đổi tuần. "
            + " ".join(warnings),
            company=group["company"],
            workspace_id=wid,
            evidence_sources=sources,
            evidence_cache={"reused": bool(cached_company_sources), "checked_at": company_checked_at},
            partner_identity=group.get("identity", {}),
            require_semantic_review=True,
            inbox_fingerprint=fingerprint,
            observer=notify,
        )
        return wid, {
            **result.structured_report.to_dict(),
            "evaluation": result.evaluation.to_dict(),
        }

    def run(self, message, *, notify):
        started = time.perf_counter()
        parts, reports = [], []

        def append(text):
            parts.append(text)
            notify("text", {"delta": text + "\n\n"})

        notify("inbox_progress", {"stage": "inbox"})
        latest_limit = latest_inbox_limit(message)
        try:
            scan = self.scan(message, notify)
        except Exception as exc:
            append(
                ("Chưa tìm được lời mời trong Gmail: " if self.targeted else "Chưa đọc được email gần nhất: " if latest_limit else "Chưa đọc được inbox hôm nay: ")
                + redact(str(exc))
                + ". Em chưa thể xác nhận email mới hoặc tự nghiên cứu đối tác."
            )
            return AgentResult(reply="\n\n".join(parts), tool_calls=self.calls)
        if self.targeted:
            append(f"Em đã tìm email liên quan đến lời mời hợp tác trong Gmail ({len(scan['messages'])} kết quả; không giới hạn trong hôm nay).")
            if scan.get("limited"):
                append("Kết quả tìm kiếm chạm giới hạn; có thể còn thư chưa xem. Chưa kết luận đây là toàn bộ lời mời.")
        elif latest_limit:
            append(f"Em đã kiểm tra **{len(scan['messages'])} email gần nhất{' trong Gmail INBOX' if scan['fresh'] else ' đang lưu trong PU'}** (tối đa {latest_limit} email; không giới hạn trong hôm nay).")
            if scan['messages']:
                append(latest_inbox_table(scan['messages']))
                attention = latest_attention_markdown(scan['messages'])
                if attention:
                    append(attention)
        else:
            append(f"{'Hôm nay anh nhận được' if scan['fresh'] else 'Dữ liệu đang lưu có'} **{len(scan['messages'])} email**.")
        if not scan["fresh"]:
            append(
                "**Chưa đồng bộ được Gmail. Đây chỉ là dữ liệu đã lưu, không phải xác nhận inbox mới nhất.**\n"
                + scan.get("warning", "")
            )
        if scan.get("limited") and not latest_limit and not self.targeted:
            append(
                "Inbox vượt giới hạn 500 email/lượt; kết quả có thể chưa bao gồm toàn bộ email hôm nay."
            )
        calendars = {}

        def read_calendar(emails=()):
            from pu.reporting.scheduling import window_snapshot

            window = self.scheduling_window(emails, message)
            key = json.dumps({name: window.get(name) for name in ("status", "arguments", "week_start", "week_end")}, sort_keys=True)
            if key not in calendars:
                notify("inbox_progress", {"stage": "calendar"})
                snapshot = {"status": "unknown", "slots": [], "events": [], "checked_sources": [],
                            "timezone": "Asia/Ho_Chi_Minh", "warnings": [window.get("warning") or "Chưa đọc được lịch; không xác nhận giờ trống."]}
                if window["status"] == "resolved":
                    try:
                        snapshot = self.tool("read_week_availability", notify, window["arguments"])
                    except Exception:
                        pass
                calendars[key] = window_snapshot(snapshot, window)
            return window_snapshot(calendars[key], window)
        try:
            notify("inbox_progress", {"stage": "triage"})
            candidates, _excluded = self.candidates(scan)
            with self.measure("classification"):
                partners = self.classify(candidates, notify) if candidates else []
            partners = self.select_partners(partners, message, append)
            if partners:
                append(
                    f"Có **{len(partners)} cuộc trao đổi kinh doanh cần anh chú ý**. Em đã kiểm tra nội dung và đang chuẩn bị thông tin công ty để anh xem."
                )
            elif not self.targeted:
                append(
                    "Em chưa tìm thấy yêu cầu kinh doanh trực tiếp nào đủ thông tin để chuẩn bị báo cáo."
                )
            excluded = sum(v["status"] == "excluded" for v in self.validation.values())
            uncertain = sum(v["status"] == "uncertain" for v in self.validation.values())
            if excluded and not self.targeted:
                append(
                    f"Có **{excluded} email không phải yêu cầu hợp tác trực tiếp**; vẫn được liệt kê trong bảng để anh xem." if latest_limit else f"Đã gộp **{excluded} email quảng cáo, thông báo hoặc nội dung không cần xử lý**."
                )
            if uncertain:
                append(
                    f"Có **{uncertain} email chưa đủ dữ kiện**; anh có thể xem trong chi tiết lọc email."
                )
        except Exception as exc:
            append(
                "Chưa hoàn tất phân loại đối tác: "
                + redact(str(exc))
                + ". Không kết luận rằng inbox không có đối tác mới."
            )
            partners = []
            for item in self.validation.values():
                if item["status"] == "eligible":
                    item.update(
                        status="uncertain",
                        reason="Chưa hoàn tất phân loại toàn bộ; chưa tự research",
                    )
        for group in partners:
            notify("inbox_progress", {"stage": "research", "company": group["company"]})
            try:
                group = self.conversation(group, notify, append)
                calendar = read_calendar(group["emails"])
                with self.measure("partner_reports"):
                    wid, payload = self.partner_report(group, scan, calendar, notify)
                append(self.render_report(payload))
                stored = self.repo.require_report(wid, payload["report_id"])
                reports.append(
                    {
                        "workspace_id": wid,
                        "report_id": payload["report_id"],
                        "title": payload["title"],
                        "company": group["company"],
                        "content_hash": stored["content_hash"],
                        "evidence_policy_version": payload.get("metadata", {}).get(
                            "evidence_policy_version"
                        ),
                        "quality_policy_version": payload.get("metadata", {}).get("quality_policy_version"),
                        "rubric_version": payload.get("evaluation", {}).get("rubric_version"),
                        "release_allowed": payload.get("evaluation", {}).get(
                            "release_allowed", False
                        ),
                    }
                )
                if payload.get("evaluation", {}).get("release_allowed") and not self.targeted:
                    from pu.ops.briefing import BriefingService

                    try:
                        with self.measure("approval_preparation"):
                            BriefingService(self.app.settings.home).prepare_approvals(wid, payload, self.app)
                    except Exception as exc:
                        append(
                            "Báo cáo đã tạo, nhưng chưa chuẩn bị được hành động chờ duyệt: "
                            + redact(str(exc))
                        )
            except Exception as exc:
                notify(
                    "inbox_report_failed", {"company": group["company"], "error": redact(str(exc))}
                )
                append(
                    f"**{group['company']}:** em đã nhận diện được yêu cầu, nhưng chưa hoàn tất báo cáo. Anh có thể yêu cầu thử lại; hiện chưa có báo cáo để duyệt."
                )
        if not calendars:
            read_calendar()
        for calendar in calendars.values():
            append(calendar_markdown(calendar))
        if self.targeted:
            append("Em chưa gửi thư, tạo sự kiện hoặc lưu báo cáo vào kho tri thức. Các hành động này cần anh xác nhận.")
        elif any(report["release_allowed"] for report in reports):
            append(
                "Anh có thể đọc báo cáo và chọn **Duyệt lưu tri thức** hoặc duyệt gửi email khi đã cấu hình người nhận. Em chưa thực hiện hành động phân phối nào."
            )
        notify("inbox_progress", {"stage": "completed"})
        self.timings["other"] = max(0.0, time.perf_counter() - started - sum(self.timings.values()))
        return AgentResult(
            reply="\n\n".join(parts),
            tool_calls=self.calls,
            reports=reports,
            iterations=1,
            inbox_validation=list(self.validation.values()),
            timing_breakdown={key: round(value, 3) for key, value in self.timings.items()},
        )
