"""Granular preparation facts; absence is unknown, never not-applicable."""

from __future__ import annotations

from pu.reporting.text import normalize_prose

PREPARATION_FIELDS = {
    "contact_role": "Vai trò người liên hệ",
    "representative_authority": "Quyền đại diện",
    "pilot_department": "Phòng ban thử nghiệm",
    "pilot_users": "Người dùng thử nghiệm",
    "input_documents": "Tài liệu đầu vào",
    "source_systems": "Hệ thống nguồn",
    "security_requirements": "Yêu cầu bảo mật",
    "decision_owner": "Người quyết định",
    "budget": "Ngân sách",
    "timeline": "Thời hạn",
}


def normalize_preparation(items, valid_ids: set[str]) -> list[dict]:
    supplied = {item["key"]: item for item in items if isinstance(item, dict) and isinstance(item.get("key"), str) and item["key"] in PREPARATION_FIELDS} if isinstance(items, list) else {}
    result = []
    for key, label in PREPARATION_FIELDS.items():
        item = supplied.get(key, {})
        state = item.get("state", "unknown")
        if state not in {"known", "self_reported", "unknown", "conflicting"}:
            state = "unknown"
        raw_refs = item.get("source_ids") or []
        refs = list(dict.fromkeys(str(ref) for ref in raw_refs)) if isinstance(raw_refs, list) else []
        invalid = item.get("invalid_source_ids") or []
        invalid = [str(ref) for ref in invalid] if isinstance(invalid, list) else []
        result.append({"key": key, "label": label, "state": state,
                       "answer_status": item.get("answer_status") if item.get("answer_status") in {"provided", "partial", "requested", "unknown"} else "unknown",
                       "remaining_gap": normalize_prose(item.get("remaining_gap")),
                       "value": normalize_prose(item.get("value")),
                       "scope": item.get("scope") if item.get("scope") in {"identity", "pilot", "company_context", "meeting"} else "unknown",
                       "evidence_quote": str(item.get("evidence_quote") or "").strip(),
                       "summary": normalize_prose(item.get("summary")),
                       "source_ids": [ref for ref in refs if ref in valid_ids],
                       "invalid_source_ids": [*invalid, *[ref for ref in refs if ref not in valid_ids]]})
    return result
