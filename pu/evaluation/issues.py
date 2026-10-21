"""Actionable presentation of evaluator results; never changes gate decisions."""

from __future__ import annotations


def report_issues(evaluation: dict) -> list[dict]:
    issues = []
    details = evaluation.get("status_details") or {}
    metrics = (evaluation.get("metrics") or {}).get("status_details") or {}
    conflicting_fields = set()
    labels = {"contact": "Người liên hệ", "scale": "Quy mô", "calendar": "Lịch",
              "website": "Website", "request": "Nhu cầu từ email", "sector": "Lĩnh vực",
              "products": "Sản phẩm và dịch vụ", "markets": "Thị trường",
              "digital_context": "Bối cảnh công nghệ", "meeting_preparation": "Chuẩn bị cuộc gặp"}
    for field, detail in (metrics.get("field_coverage") or {}).items():
        if detail.get("status") == "conflicting":
            conflicting_fields.add(field)
            issues.append({"code": "coverage_conflict", "severity": "error", "field": field,
                           "message": f"{labels.get(field, field)}: {detail.get('summary') or 'còn dữ kiện mâu thuẫn cần đối chiếu.'}",
                           "source_ids": detail.get("source_ids", []),
                           "affected_actions": ["import_verified", "send"]})
        elif detail.get("status") == "supported" and not detail.get("supported"):
            explanation = 'chưa xử lý được ký hiệu số/ngày hoặc giới hạn đầu vào để kiểm định.' if detail.get('support_reason') == 'numeric_notation_unhandled' else 'mô tả chưa được nguồn đã đọc hỗ trợ đầy đủ.'
            issues.append({"code": "field_evidence", "severity": "error", "field": field,
                           "message": f"{labels.get(field, field)}: {explanation}",
                           "source_ids": detail.get("source_ids", []), "affected_actions": ["import_verified", "send"]})
    for claim_id, detail in (metrics.get("claims") or {}).items():
        if detail.get("supported"):
            continue
        reason = detail.get("support_reason", "unknown")
        explanation = {
            "numeric_or_date_mismatch": "số liệu hoặc ngày tháng chưa khớp với nguồn",
            "numeric_unit_mismatch": "đơn vị của số liệu chưa khớp với nguồn",
            "numeric_notation_unhandled": "bộ kiểm định chưa xử lý được ký hiệu số/ngày hoặc giới hạn đầu vào; chưa thể xác nhận, không kết luận dữ kiện sai",
            "snippet_only_or_missing_evidence": "nguồn còn thiếu, chưa hợp lệ hoặc chỉ có trích đoạn tìm kiếm",
        }.get(reason, "chưa có bằng chứng đủ rõ để xác nhận nội dung")
        issues.append({"code": "claim_evidence", "severity": "error",
                       "message": f"Nhận định {claim_id}: {explanation}.",
                       "support_reason": reason,
                       "claim_ids": [claim_id], "source_ids": detail.get("source_ids", []),
                       "affected_actions": ["import_verified", "send"]})
    semantic = details.get("semantic_review")
    if semantic in {"unavailable", "incomplete", "failed"}:
        messages = {
            "unavailable": "Chưa hoàn tất bước đối chiếu nội dung với nguồn.",
            "incomplete": "Kết quả đối chiếu với nguồn còn thiếu tiêu chí kiểm tra.",
            "failed": "Nội dung chưa đạt bước đối chiếu với nguồn.",
        }
        judge = evaluation.get("judge") or {}
        reason = str(judge.get("reason") or "").strip()
        issues.append({"code": f"semantic_{semantic}", "severity": "error",
                       "message": messages[semantic] + (f" {reason}" if reason else ""),
                       "affected_actions": ["import_verified", "send"]})
    for finding in evaluation.get("findings") or []:
        message = str(finding)
        if any(token in message for token in ("hard evidence failures", "do not have deterministic support", "Source coverage")) and issues:
            continue
        if any(f"Trường {field} có dữ kiện mâu thuẫn" in message for field in conflicting_fields):
            continue
        if "ngữ nghĩa" in message and semantic in {"unavailable", "incomplete", "failed"}:
            continue
        folded = message.casefold()
        localized = None
        for token, translation in (
            ("report contains no structured factual claims", "Báo cáo chưa có các dữ kiện cụ thể để đối chiếu với nguồn."),
            ("invented/invalid source reference", "Một số trích dẫn không khớp với danh sách nguồn đã thu thập."),
            ("source reference(s) trong", "Một số dữ kiện dùng nguồn chưa hợp lệ hoặc chỉ là nội dung AI tổng hợp."),
            ("source coverage", "Chưa đủ nhận định được nguồn đã đọc hỗ trợ."),
            ("meeting readiness", "Thông tin chuẩn bị cuộc gặp còn thiếu; cần bổ sung mục tiêu và câu hỏi cụ thể."),
            ("overall deterministic score", "Báo cáo chưa vượt qua toàn bộ yêu cầu kiểm định chất lượng."),
            ("completeness", "Nội dung nghiên cứu chưa đủ để chuẩn bị cuộc gặp."),
            ("claim(s)", "Một số nhận định chưa được bằng chứng hỗ trợ đầy đủ."),
        ):
            if token in folded:
                localized = translation
                break
        code = "quality_requirement"
        for token, candidate in (
            ("danh tính", "identity_conflict"), ("number", "numeric_support"),
            ("nguồn", "evidence_support"), ("source", "evidence_support"),
            ("bao phủ", "information_gap"), ("readiness", "meeting_readiness"),
            ("trùng", "duplication"),
        ):
            if token in folded:
                code = candidate
                break
        issues.append({"code": code, "severity": "error", "message": localized or message,
                       "affected_actions": ["import_verified", "send"]})
    seen, unique = set(), []
    for issue in issues:
        if issue["message"] not in seen:
            seen.add(issue["message"])
            unique.append(issue)
    return unique
