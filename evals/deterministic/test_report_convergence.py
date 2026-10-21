"""Regression cases from the unread-PDF, stray-year and false readiness failure."""

import json
from dataclasses import replace

from evals.deterministic.test_report_editorial_calibration import _compact, _evaluate
from pu.evaluation.preparation import assess_preparation
from pu.evaluation.report import DeterministicReportEvaluator, _text_support_reason
from pu.reporting.evidence import EvidenceBundle, StructuredReportBuilder
from pu.reporting.evidence_routing import route_evidence
from pu.reporting.models import ReportClaim, ReportSource
from pu.reporting.preparation import normalize_preparation
from pu.reporting.reading_view import freeze_reading_view
from pu.reporting.repair import repair_diagnostics, select_repair_candidate
from pu.reporting.text import normalize_prose


def test_layout_normalization_preserves_vietnamese_code_url_and_windows_path():
    value = r"Việt Nam\n- Nguồn https://example.com/p?q=%5Cn\n- `r'\n'` và C:\new\test.txt"
    assert normalize_prose(value) == "Việt Nam\n- Nguồn https://example.com/p?q=%5Cn\n- `r'\\n'` và C:\\new\\test.txt"
    assert normalize_prose(r"Dòng một\\nDòng hai") == "Dòng một\nDòng hai"
    assert normalize_prose(r"```python\nprint('x')```") == r"```python\nprint('x')```"


def test_leads_and_syntheses_are_not_generation_or_routing_evidence():
    primary = ReportSource('W3', 'web', 'web', 'Investor', 'Có mặt tại 65 quốc gia.', url='https://example.com/investors', external=True)
    snippet = replace(primary, id='W14', title='Report 2023', metadata={'snippet_only': True}, excerpt='200,000 points of sale')
    derived = replace(primary, id='S99', derived=True, excerpt='Unverified synthesis')
    bundle = EvidenceBundle((primary, snippet, derived))
    assert [item['source_id'] for item in bundle.prompt_payload()] == ['W3']
    routed = route_evidence([source.__dict__ for source in bundle.sources])
    assert [item['source_id'] for item in routed['web']['references']] == ['W3']


def test_routing_deduplicates_email_and_selects_latest_calendar_without_renumbering():
    sources = [
        {'id':'old','source_type':'calendar','content':'old'},
        {'id':'email1','source_type':'email','content':'same'},
        {'id':'email2','source_type':'email','content':'same'},
        {'id':'new','source_type':'calendar','content':'new'},
    ]
    contexts = route_evidence(sources)
    assert contexts['email']['source_ids'] == ['email1']
    assert contexts['calendar']['source_ids'] == ['new']
    assert contexts['calendar']['references'][0]['report_source_id'] == 'W4'


def test_diagnostics_pinpoint_missing_year_without_calling_65_wrong():
    report = _compact()
    source = replace(report.sources[1], id='W3', excerpt='Sản phẩm có mặt tại 65 quốc gia và vùng lãnh thổ.')
    report.sources.append(source)
    report.claims.append(ReportClaim('CX', 'Sản phẩm có mặt tại 65 quốc gia, khác với năm 2023.', 'company_context', ('W3',)))
    result = DeterministicReportEvaluator().evaluate(report)
    diagnostic = next(item for item in repair_diagnostics(report, result)['claims_to_fix'] if item['id']=='CX')
    assert '2023' in diagnostic['missing_numbers']
    assert '65' not in diagnostic['missing_numbers']
    assert diagnostic['primary_source_available']
    assert not result.release_allowed


def _assess(key, quote, *, answer='provided', value=None, scope='pilot'):
    source = ReportSource('E1', 'email', 'email', 'Synthetic', quote)
    items = normalize_preparation([{'key':key,'state':'self_reported','summary':quote,'answer_status':answer,
                                    'value':value or quote,'scope':scope,'evidence_quote':quote,'source_ids':['E1']}], {'E1'})
    assessed, errors = assess_preparation(items, {'E1':source}, _text_support_reason)
    return next(item for item in assessed if item['key']==key), errors


def test_security_discussion_is_requested_not_an_answer():
    item, errors = _assess('security_requirements', 'Muốn trao đổi thêm về bảo mật.', answer='requested')
    assert not errors
    assert item['answer_status']=='requested' and item['state']=='unknown' and not item['value']


def test_meeting_duration_does_not_become_pilot_timeline():
    item, errors = _assess('timeline', 'Đề nghị họp 45 phút.', value='45 phút')
    assert not errors
    assert item['state']=='unknown' and item['scope']=='meeting'


def test_concrete_budget_remains_sender_reported_and_numeric_mismatch_is_hard():
    item, errors = _assess('budget', 'Ngân sách pilot là 100 triệu đồng.', value='Ngân sách pilot là 100 triệu đồng.')
    assert not errors and item['state']=='self_reported' and item['answer_status']=='provided'
    item, errors = _assess('budget', 'Ngân sách pilot là 100 triệu đồng.', value='Ngân sách pilot là 999 triệu đồng.')
    assert errors and item['state']=='unknown'


def test_missing_semantic_verdict_never_confirms_concrete_checklist_answer():
    report = _compact()
    source = report.sources[0]
    quote = 'Alice at Acme requested a meeting.'
    report.sources[0] = replace(source, excerpt=quote)
    report.metadata['preparation_checklist'] = normalize_preparation([
        {'key':'contact_role','state':'self_reported','summary':quote,'answer_status':'provided',
         'value':quote,'scope':'identity','evidence_quote':quote,'source_ids':[source.id]}], {s.id for s in report.sources})
    result = _evaluate(report)
    item = result.status_details['readiness']['checklist'][0]
    assert item['answer_status']=='unknown' and item['support_reason']=='answer_not_confirmed'


def test_final_gaps_are_derived_from_assessed_answers_and_exports_use_same_snapshot():
    report = _compact()
    report.metadata['preparation_schema_version'] = 2
    item, _ = _assess('security_requirements','Muốn trao đổi thêm về bảo mật.', answer='requested')
    report.metadata['preparation_assessment'] = [item]
    freeze_reading_view(report)
    assert 'Cần làm rõ yêu cầu bảo mật.' in report.metadata['reading_view']['open_items']
    before = json.dumps(report.to_dict(), sort_keys=True)
    assert 'Cần làm rõ yêu cầu bảo mật.' in StructuredReportBuilder.render_markdown(report)
    assert json.dumps(report.to_dict(), sort_keys=True)==before


def test_repair_selection_rejects_equal_or_new_numeric_failure():
    original = _compact()
    original.claims.append(ReportClaim('bad','Acme có 999999 nhân viên.','company_context',('S2',)))
    before = _evaluate(original)
    assert not select_repair_candidate(original,before,original,_evaluate(original))['accepted']
    from copy import deepcopy

    worse = deepcopy(original)
    worse.claims.append(ReportClaim('worse','Acme có 888888 nhà máy.','company_context',('S2',)))
    assert not select_repair_candidate(original,before,worse,_evaluate(worse))['accepted']


def test_empty_calendar_status_is_honest_and_consistent_in_all_exports():
    from io import BytesIO
    from zipfile import ZipFile

    from pu.reporting.docx import render_docx
    from pu.reporting.render import ReportRenderer

    report = _compact()
    report.metadata['availability'] = {'status':'available','checked_at':'2026-10-17T05:00:00+00:00',
                                       'timezone':'Asia/Ho_Chi_Minh','coverage':'local_only','slots':[]}
    renderer = ReportRenderer()
    outputs = [StructuredReportBuilder.render_markdown(report), renderer.render_html(report), renderer.render_print_html(report)]
    with ZipFile(BytesIO(render_docx(report.to_dict()))) as archive:
        outputs.append(archive.read('word/document.xml').decode())
    for output in outputs:
        assert 'Tại thời điểm kiểm tra, chưa tìm được khoảng trống' in output
        assert 'chưa kiểm tra Google Calendar' in output


def test_print_citation_anchor_survives_filtering_an_uncited_url_alias():
    from pu.reporting.citations import build_citation_presentation
    from pu.reporting.render import ReportRenderer

    report = _compact()
    official = next(source for source in report.sources if source.id == 'S2')
    report.sources.insert(0, replace(official, id='URL_ALIAS'))
    report.metadata['citation_presentation'] = build_citation_presentation(report)
    output = ReportRenderer().render_print_html(report)
    assert "href='#src-URL_ALIAS'" in output
    assert "name='src-URL_ALIAS'" in output
