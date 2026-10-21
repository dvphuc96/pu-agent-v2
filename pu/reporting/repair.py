"""Specific repair diagnostics and conservative candidate selection."""

from __future__ import annotations

import hashlib
import json

from pu.reporting.citations import canonical_public_url
from pu.reporting.numeric_evidence import compare_numeric, number_literals


def repair_diagnostics(report, evaluation) -> dict:
    sources = {source.id: source for source in report.sources if not source.derived and not source.metadata.get("snippet_only")}
    details = evaluation.metrics.status_details

    def describe(key, text, refs, reason):
        excerpts = [sources[ref].excerpt for ref in refs if ref in sources]
        numeric = compare_numeric(text, excerpts)
        return {"id": key, "text": text, "source_ids": refs, **numeric, "reason": reason,
                "primary_source_available": bool(excerpts),
                "instruction": "Remove this unsupported claim everywhere (summary, prose, coverage and claim list), or rewrite atomically using only cited primary evidence. Do not replace it with an invented source or repeat the same missing token."}

    claims = [describe(claim.id, claim.text, list(claim.source_ids), details.get("claims", {}).get(claim.id, {}).get("support_reason"))
              for claim in report.claims if not details.get("claims", {}).get(claim.id, {}).get("supported")]
    fields = [describe(key, item.get("summary", ""), item.get("source_ids", []), item.get("support_reason"))
              for key, item in details.get("field_coverage", {}).items()
              if not item.get("supported") and item.get("status") in {'supported', 'conflicting'}]
    from pu.reporting.evidence import _relevant_excerpt

    needed = {ref for item in [*claims, *fields] for ref in item['source_ids']}
    return {"claims_to_fix": claims, "fields_to_fix": fields, "findings": evaluation.findings,
            "blockers": blocking_issues(report, evaluation),
            "primary_excerpts_by_id": {ref: _relevant_excerpt(sources[ref], max_chars=3500) for ref in sorted(needed) if ref in sources},
            "judge_reason": evaluation.judge.reason if evaluation.judge else None,
            "prose_duplicates": details.get("prose_duplicates", [])}


def blocking_issues(report, evaluation):
    """Stable evidence blockers do not disappear when model claim IDs change."""
    details = evaluation.metrics.status_details
    sources = {source.id: source for source in report.sources}
    claims = {claim.id: claim for claim in report.claims}
    issues = []

    def add(code, key, text='', refs=(), reason='', numeric=None, hard=True):
        numeric = numeric or {}
        category = 'evaluator_limitation' if reason == 'numeric_notation_unhandled' else 'content_evidence'
        canonical_refs = sorted({canonical_public_url(sources[ref].url) or ref for ref in refs if ref in sources})
        signature = [code, key if code != 'claim' else '', ' '.join(text.casefold().split()), canonical_refs, reason,
                     numeric.get('missing_numbers', []), numeric.get('missing_dates', []), numeric.get('missing_units', [])]
        fingerprint = hashlib.sha256(json.dumps(signature, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
        issues.append({'code':code, 'id':key, 'fingerprint':fingerprint, 'cause_category':category,
                       'hard':hard, 'reason':reason, 'source_ids':list(refs),
                       'repairable_by_generation':category != 'evaluator_limitation'})

    for key, detail in details.get('claims', {}).items():
        if detail.get('supported'):
            continue
        claim = claims.get(key)
        add('claim', key, claim.text if claim else '', detail.get('source_ids', []), detail.get('support_reason', ''), detail.get('numeric_evidence'),
            hard=key in details.get('hard_unsupported_claims', []) or key in details.get('semantic_negative_claims', []))
    for key, detail in details.get('field_coverage', {}).items():
        if detail.get('status') == 'conflicting' or (detail.get('status') == 'supported' and not detail.get('supported')):
            add('field', key, refs=detail.get('source_ids', []), reason='coverage_conflict' if detail.get('status') == 'conflicting' else detail.get('support_reason', ''),
                numeric=detail.get('numeric_evidence'), hard=detail.get('status') == 'conflicting' or key in details.get('hard_field_failures', []))
    for item in details.get('preparation_checklist', []):
        reason = item.get('value_support_reason') or item.get('support_reason')
        if reason == 'numeric_notation_unhandled':
            add('checklist', item['key'], reason=reason)
    for finding in evaluation.findings:
        if finding.startswith('Checklist'):
            add('checklist_contract', finding)
    semantic = evaluation.status_details.get('semantic_review')
    if semantic in {'unavailable', 'incomplete', 'unavailable_or_incomplete'}:
        issues.append({'code':'semantic_unavailable', 'id':semantic, 'fingerprint':'semantic_unavailable', 'cause_category':'evaluator_unavailable', 'hard':True, 'repairable_by_generation':False})
    elif semantic == 'failed':
        for key in evaluation.status_details.get('semantic_blockers') or ['semantic_failed']:
            issues.append({'code':'semantic_failed','id':key,'fingerprint':'semantic:'+key,'cause_category':'semantic_editorial','hard':False,'repairable_by_generation':True})
    if not evaluation.metrics.total_claims or evaluation.metrics.invalid_source_refs:
        add('contract', 'empty_claims' if not evaluation.metrics.total_claims else 'invalid_references')
    if not evaluation.release_allowed and not issues:
        issues.append({'code':'quality_contract','id':'quality_contract','fingerprint':'quality_contract','cause_category':'semantic_editorial','hard':False,'repairable_by_generation':True})
    return list({item['fingerprint']:item for item in issues}.values())


def plan_repair(report, evaluation):
    identity = report.metadata.get('partner_identity') or {}
    if identity.get('status') == 'conflicting':
        return {'decision':'skip','reason':'identity_conflict','blockers':[]}
    if evaluation.release_allowed:
        return {'decision':'skip','reason':'already_released','blockers':[]}
    issues = blocking_issues(report, evaluation)
    if any(item['cause_category'] == 'evaluator_unavailable' for item in issues) or evaluation.judge is None:
        return {'decision':'skip','reason':'evaluator_unavailable','blockers':issues}
    repairable = [item for item in issues if item['repairable_by_generation']]
    limited = any(item['cause_category'] == 'evaluator_limitation' for item in issues)
    if not repairable or (limited and not any(item['hard'] for item in repairable)):
        return {'decision':'skip','reason':'evaluator_limitation','blockers':issues}
    return {'decision':'generate','reason':'content_or_editorial_blockers','blockers':issues}


def _preserves_critical(before_report, before, candidate, after):
    before_fields = before.metrics.status_details.get('field_coverage', {})
    after_fields = after.metrics.status_details.get('field_coverage', {})
    for key in ('sector', 'contact', 'request', 'meeting_preparation'):
        if before_fields.get(key, {}).get('supported') and not after_fields.get(key, {}).get('supported'):
            return False
    old_items = before.status_details.get('readiness', {}).get('checklist', [])
    new_items = {item['key']:item for item in after.status_details.get('readiness', {}).get('checklist', [])}
    for old in old_items:
        if old.get('answer_status') not in {'provided', 'partial'} or old.get('state') not in {'known','self_reported'}:
            continue
        new = new_items.get(old['key'], {})
        if new.get('answer_status') not in {'provided','partial'} or new.get('state') not in {'known','self_reported'} or new.get('scope') != old.get('scope'):
            return False
        if not number_literals(old.get('value', '')).issubset(number_literals(new.get('value', ''))):
            return False
        from pu.evaluation.report import _tokens

        if not _tokens(old.get('value', '')).issubset(_tokens(new.get('value', '') + ' ' + new.get('evidence_quote', ''))):
            return False
    original_calendar = before_report.metadata.get('availability') or {}
    candidate_calendar = candidate.metadata.get('availability') or {}
    return all(original_calendar.get(key) == candidate_calendar.get(key) for key in ('slots','start','end','duration_minutes','scheduling_window'))


def select_repair_candidate(before_report, before, candidate, after):
    original = blocking_issues(before_report, before)
    proposed = blocking_issues(candidate, after)
    old = {item['fingerprint'] for item in original}
    new = {item['fingerprint'] for item in proposed}
    old_hard = {item['fingerprint'] for item in original if item['hard']}
    new_hard = {item['fingerprint'] for item in proposed if item['hard']}
    accepted, outcome = False, 'no_improvement'
    if (not after.evaluated or not after.metrics.total_claims or after.metrics.invalid_source_refs > before.metrics.invalid_source_refs
            or not _preserves_critical(before_report, before, candidate, after) or new_hard - old_hard):
        outcome = 'invalid_candidate'
    elif after.release_allowed:
        accepted, outcome = True, 'released'
    elif (old_hard and new_hard < old_hard and not (new - old)) or (not old_hard and new < old):
        accepted, outcome = True, 'improved_draft'
    return {'decision':'generate','accepted':accepted,'outcome':outcome,'reason':outcome,
            'blockers_before':original,'blockers_after':proposed,
            'resolved':sorted(old-new),'new':sorted(new-old),'remaining':sorted(new)}
