"""Freeze the new reading layout before evaluation and content hashing."""

from __future__ import annotations

import re

from pu.reporting.numeric_evidence import number_literals

READING_VIEW_VERSION = "partner-brief-v2"


def _unique(items):
    seen, result = set(), []
    for text in items:
        text = str(text or "").strip()
        key = " ".join(text.casefold().split())
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def freeze_reading_view(report):
    if "company_context" not in report.sections:
        return  # Legacy reports retain their original presentation.
    blocks = [{"key": key, "title": title, "text": report.sections[key]}
              for key, title in (
                  ("company_context", "Công ty và bối cảnh liên quan"),
                  ("email_need", "Nhu cầu từ email"),
                  ("meeting_preparation", "Chuẩn bị trao đổi"),
                  ("recent_updates", "Cập nhật liên quan"),
              ) if report.sections.get(key)]
    represented = {block["key"] for block in blocks}
    # Preserve explicit human additions instead of silently hiding their text.
    blocks.extend({"key": key, "title": key, "text": text}
                  for key, text in report.sections.items() if key not in represented and text)
    checks = report.metadata.get('company_profile_checks', [])
    for block in blocks:
        if block['key'] != 'company_context' or not checks:
            continue
        sentences = re.split(r'(?<=[.!?])(?=\s|$)', block['text'])
        kept = []
        for sentence in sentences:
            refs = set(re.findall(r'\[((?:W|S)\d+)\]', sentence))
            years = set(re.findall(r'(?<!\w)(?:19|20)\d{2}(?!\w)', sentence))
            warning_only = bool(re.match(r'\s*(?:Các|Những) (?:trang|nguồn)\b', sentence, re.IGNORECASE)
                                and re.search(r'(?:mốc|năm) thành lập.*khác nhau', sentence, re.IGNORECASE))
            represented = warning_only and any(
                years and years == set(check.get('years', [])) and number_literals(sentence) <= years
                and set(check.get('source_ids', [])) == refs
                for check in checks
            )
            if not represented:
                kept.append(sentence)
        block['text'] = ''.join(kept).strip()
    seen = {" ".join(report.executive_summary.casefold().split())}
    for block in blocks:
        lines = []
        for line in block["text"].splitlines():
            key = " ".join(line.casefold().split())
            if len(key) >= 60 and key in seen:
                continue
            if key:
                seen.add(key)
            lines.append(line)
        block["text"] = "\n".join(lines).strip()
    blocks = [block for block in blocks if block["text"]]
    identity = report.metadata.get("partner_identity") or {}
    conflicts = [item.description + " " + " ".join(f"[{ref}]" for ref in item.source_ids) for item in report.contradictions]
    profile_warnings = []
    for check in report.metadata.get('company_profile_checks', []):
        represented = any(
            set(check.get('source_ids', [])) <= set(item.source_ids)
            and all(year in item.description for year in check.get('years', []))
            and re.search(r'thành lập|founding|設立', item.description, re.IGNORECASE)
            for item in report.contradictions
        )
        if not represented:
            profile_warnings.append(check['message'])
    gaps = []
    if report.metadata.get("preparation_schema_version", 1) in (2, 3):
        checklist = report.metadata.get("preparation_assessment", report.metadata.get("preparation_checklist", []))
        for item in checklist:
            key = item.get("key")
            if key == "representative_authority" and identity.get("affiliation_warnings"):
                continue
            provided = item.get("answer_status") == "provided" and item.get("state") in {"known", "self_reported"}
            correct_scope = item.get("scope") == ("identity" if key in {"contact_role", "representative_authority"} else "pilot")
            if not (provided and correct_scope):
                label = str(item.get("label") or key).lower()
                scope = "người liên hệ" if key in {"contact_role", "representative_authority"} else "pilot"
                if item.get("answer_status") == "partial" and item.get("state") in {"known", "self_reported"} and item.get("value"):
                    value = item['value'].rstrip('.; ')
                    gap = (item.get('remaining_gap') or 'phần thông tin còn thiếu').rstrip('.; ')
                    gaps.append(f"{item.get('label') or key}: đã biết một phần — {value}. Cần làm rõ: {gap}.")
                else:
                    gaps.append(f"Cần làm rõ {label}." if item.get("answer_status") == "requested" else f"Chưa xác định {label} cho {scope}.")
    report.metadata["reading_view"] = {
        "version": READING_VIEW_VERSION, "blocks": blocks,
        "open_items": _unique([*identity.get("conflicts", []),
                               *identity.get("affiliation_warnings", []),
                               *profile_warnings,
                               *conflicts,
                               *gaps,
                               *report.missing_information]),
    }


def prose_duplicates(report) -> list[dict]:
    """Locate exact and near-duplicate paragraphs; do not delete facts."""
    from difflib import SequenceMatcher

    paragraphs = []
    view = report.metadata.get("reading_view") or {}
    sections = [(block["key"], block["text"]) for block in view.get("blocks", [])] if view.get("version") == READING_VIEW_VERSION else report.sections.items()
    for section, text in [("summary", report.executive_summary), *sections]:
        if len(paragraphs) >= 60:
            break
        for index, line in enumerate(str(text or "").splitlines()):
            normalized = re.sub(r"\[(?:S|W)\d+\]", "", line)
            normalized = " ".join(re.findall(r"\w+", normalized.casefold()))
            if len(normalized) >= 100:
                paragraphs.append((f"{section}:{index + 1}", normalized[:2000]))
            if len(paragraphs) >= 60:
                break
    duplicates = []
    for index, (location, text) in enumerate(paragraphs):
        for other_location, other_text in paragraphs[:index]:
            # Word-level matching avoids quadratic work on long repetitive
            # character strings while preserving useful paragraph locations.
            matcher = SequenceMatcher(None, text.split(), other_text.split())
            if matcher.quick_ratio() < 0.88:
                continue
            similarity = matcher.ratio()
            if similarity >= 0.88:
                duplicates.append({"locations": [other_location, location], "similarity": round(similarity, 3)})
                if len(duplicates) >= 20:
                    return duplicates
    return duplicates[:20]
