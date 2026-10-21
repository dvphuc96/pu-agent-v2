"""One readiness computation used before and after semantic resolution."""

from __future__ import annotations

import re


def assess_preparation(items, sources, support_check):
    assessed, errors = [], []
    for original in items:
        item = dict(original)
        refs = [sources[ref] for ref in item.get("source_ids", []) if ref in sources]
        state = item.get("state", "unknown")
        reason = "not_provided"
        if state in {"known", "self_reported", "conflicting"}:
            primary = [source for source in refs if not source.derived and not source.metadata.get("snippet_only")]
            supported, reason = support_check(item.get("summary", ""), [source.excerpt for source in primary])
            if item.get("invalid_source_ids") or not primary or not supported:
                item["state"] = "unknown"
                if item.get("invalid_source_ids") or reason in {"numeric_or_date_mismatch", "numeric_unit_mismatch", "numeric_notation_unhandled"}:
                    errors.append(f"Checklist {item['key']} có số liệu hoặc nguồn chưa hợp lệ.")
            elif state == "known" and primary and all(source.source_type == "email" for source in primary):
                # An inbound assertion remains attributed to the sender.
                item["state"] = "self_reported"
            elif state == "conflicting":
                errors.append(f"Checklist {item['key']} còn bằng chứng mâu thuẫn.")
        quote = " ".join(item.get("evidence_quote", "").split())
        primary = [source for source in refs if not source.derived and not source.metadata.get("snippet_only")]
        quote_ok = bool(quote and any(quote in " ".join(source.excerpt.split()) for source in primary))
        if not quote_ok and item.get("answer_status") in {"provided", "partial"} and len(item.get("value", "")) >= 10 and not item.get("invalid_source_ids"):
            # Recover only a verbatim known value, never join quote fragments
            # or accept a paraphrase on the model's authority.
            pattern = re.escape(" ".join(item["value"].split()))
            match = next((found for source in primary if (found := re.search(pattern, " ".join(source.excerpt.split()), re.IGNORECASE))), None)
            if match:
                item["original_evidence_quote"] = item.get("evidence_quote", "")
                quote = item["evidence_quote"] = match.group(0)
                quote_ok = True
        provided = item.get("answer_status") in {"provided", "partial"} and bool(item.get("value")) and quote_ok
        if provided:
            value_ok, value_reason = support_check(item["value"], [quote])
            if not value_ok:
                provided = False
                item['value_support_reason'] = value_reason
                if value_reason in {"numeric_or_date_mismatch", "numeric_unit_mismatch", "numeric_notation_unhandled"}:
                    errors.append(f"Checklist {item['key']} có giá trị không khớp quote.")
            if re.search(r"^(chưa|cần (trao đổi|thảo luận|làm rõ)|muốn (tìm hiểu|thảo luận))\b", item["value"], re.IGNORECASE):
                provided = False
        if item.get("answer_status") == "partial" and not item.get("remaining_gap"):
            provided = False
        if (item["key"] == "timeline" and item.get("scope") == "pilot"
                and re.search(r"phút|minutes?", item.get("value", ""), re.IGNORECASE)
                and re.search(r"họp|meeting|trao đổi", quote, re.IGNORECASE)):
            provided = False
            item["scope"] = "meeting"
        if not provided:
            item["state"] = "unknown"
            item["answer_status"] = "requested" if item.get("answer_status") == "requested" and quote_ok else "unknown"
            item["value"] = ""
            item["remaining_gap"] = ""
        elif item["state"] not in {"known", "self_reported", "conflicting"}:
            item["state"] = "unknown"
            item["answer_status"] = "unknown"
            item["value"] = ""
            item["remaining_gap"] = ""
        item["support_reason"] = reason
        assessed.append(item)
    return assessed, errors


def readiness_score(fields: dict, checklist: list[dict]) -> float:
    def supported(key):
        return bool(fields.get(key, {}).get("supported"))
    verified_authority = any(item.get("key") == "representative_authority" and item.get("state") == "known" and item.get("answer_status") == "provided" for item in checklist)
    return round(
        0.30 * supported("request") + 0.30 * supported("meeting_preparation")
        + 0.20 * supported("sector")
        + (0.20 if verified_authority else 0.10) * supported("contact"), 4,
    )


def overall_score(coverage, source_coverage, diversity, readiness, freshness, dated_news, duplication):
    return round(0.30 * coverage + 0.30 * source_coverage + 0.10 * diversity
                 + 0.10 * (freshness if dated_news else 0.5)
                 + 0.15 * readiness + 0.05 * max(0.0, 1.0 - duplication), 4)


def readiness_summary(fields: dict, checklist: list[dict], *, trusted: bool) -> dict:
    discovery = trusted and all(fields.get(key, {}).get("supported") for key in ("sector", "request", "meeting_preparation", "contact"))
    pilot_keys = {"pilot_department", "input_documents", "source_systems", "security_requirements", "decision_owner"}
    missing = [item["key"] for item in checklist if item["key"] in pilot_keys and not (item["state"] in {"known", "self_reported"} and item.get("answer_status") == "provided" and item.get("scope") == "pilot")]
    return {"discovery": "ready_with_limits" if discovery else "needs_review",
            "pilot": "needs_review" if not trusted else "needs_confirmation" if missing else "evidence_available_requires_approval",
            "pilot_missing": missing,
            "contact_verification": "verified_evidence" if any(item["key"] == "representative_authority" and item["state"] == "known" and item.get("answer_status") == "provided" for item in checklist) else "unverified",
            "checklist": checklist}
