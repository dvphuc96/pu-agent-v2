"""Real report regressions: next-week intent, partial answers and profile depth."""

from dataclasses import replace
from datetime import UTC, datetime

from evals.deterministic.test_report_convergence import _assess
from evals.deterministic.test_report_editorial_calibration import _compact
from pu.evaluation.preparation import assess_preparation, readiness_summary
from pu.evaluation.report import _text_support_reason
from pu.orchestration.inbox_chat import calendar_markdown
from pu.reporting.evidence import _relevant_excerpt
from pu.reporting.models import ReportSource
from pu.reporting.preparation import normalize_preparation
from pu.reporting.reading_view import freeze_reading_view
from pu.reporting.scheduling import meeting_window

REFERENCE = datetime(2026, 10, 17, 6, 17, tzinfo=UTC)


def email(body, received='2026-10-17T04:00:00+00:00'):
    return {'body_text':body, 'internal_date':received}


def test_next_week_email_uses_requested_week_instead_of_saturday_remainder():
    window = meeting_window([email('Anh có thể họp 45 phút trong tuần tới không?')], reference=REFERENCE)
    assert window['arguments']=={'start_date':'2026-10-19','days':7,'duration':45}
    assert window['week_end']=='2026-10-26' and window['basis']=='email'
    text = calendar_markdown({'status':'unknown','warnings':['Chưa kết nối lịch'], 'scheduling_window':window})
    assert '19/10–25/10/2026' in text and 'Chưa kết nối lịch' in text


def test_relative_week_is_anchored_to_received_date_and_expired_request_is_not_moved():
    window = meeting_window([email('Họp tuần tới nhé?', '2026-10-03T05:00:00+00:00')], reference=REFERENCE)
    assert window['status']=='expired' and window['week_start']=='2026-10-05'
    assert 'arguments' not in window


def test_user_calendar_request_overrides_email_but_inbox_week_does_not():
    incoming = [email('Có thể họp tuần tới không?')]
    explicit = meeting_window(incoming,user_message='Kiểm tra lịch tuần này giúp anh',reference=REFERENCE)
    assert explicit['basis']=='user' and explicit['arguments']['start_date']=='2026-10-17'
    inbox_only = meeting_window(incoming,user_message='Tuần này có email mới không?',reference=REFERENCE)
    assert inbox_only['basis']=='email' and inbox_only['week_start']=='2026-10-19'


def test_quoted_old_email_and_pilot_timeline_do_not_change_meeting_week():
    body='Muốn triển khai pilot tuần tới.\n> Họp tuần tới nhé?'
    assert meeting_window([email(body)],reference=REFERENCE)['basis']=='default'


def test_latest_meeting_request_wins_without_using_input_order():
    emails=[email('Họp tuần tới?', '2026-10-16T09:00:00+00:00'),email('Họp tuần này?', '2026-10-17T04:00:00+00:00')]
    assert meeting_window(emails,reference=REFERENCE)['week_start']=='2026-10-12'
    assert meeting_window(list(reversed(emails)),reference=REFERENCE)['week_start']=='2026-10-12'


def test_conflicting_or_unparsed_specific_time_is_unknown_instead_of_current_week():
    for body in ('Họp tuần này hoặc tuần tới?', 'Họp ngày 22/10/2026?', 'Họp ngày mai nhé?'):
        window=meeting_window([email(body)],reference=REFERENCE)
        assert window['status']=='needs_confirmation' and 'arguments' not in window


def test_partial_document_types_preserve_known_value_and_sample_gap():
    quote='Dữ liệu là hóa đơn PDF và biểu mẫu scan; chưa chọn bộ dữ liệu mẫu.'
    source=ReportSource('E1','email','email','Synthetic',quote)
    checklist=normalize_preparation([{'key':'input_documents','state':'self_reported','answer_status':'partial',
        'value':'Hóa đơn PDF và biểu mẫu scan','remaining_gap':'Chưa chọn bộ dữ liệu mẫu','scope':'pilot',
        'summary':quote,'evidence_quote':quote,'source_ids':['E1']}],{'E1'})
    assessed,errors=assess_preparation(checklist,{'E1':source},_text_support_reason)
    item=next(item for item in assessed if item['key']=='input_documents')
    assert not errors and item['answer_status']=='partial' and 'PDF' in item['value']
    summary=readiness_summary({},assessed,trusted=True)
    assert 'input_documents' in summary['pilot_missing']
    report=_compact()
    report.metadata.update(preparation_schema_version=3,preparation_assessment=assessed)
    freeze_reading_view(report)
    notes=' '.join(report.metadata['reading_view']['open_items'])
    assert 'đã biết một phần' in notes and 'PDF' in notes and 'Chưa chọn bộ dữ liệu mẫu' in notes
    assert 'Chưa xác định tài liệu đầu vào' not in notes


def test_partial_without_gap_or_with_false_numeric_value_never_becomes_known():
    item,errors=_assess('budget','Ngân sách pilot là 100 triệu đồng.',answer='partial',value='999 triệu đồng')
    assert errors and item['state']=='unknown' and not item['value']
    # Test without a gap is conservative, even if its value happens to match.
    item,_=_assess('budget','Ngân sách pilot là 100 triệu đồng.',answer='partial')
    assert item['state']=='unknown'


def test_bounded_excerpt_keeps_profile_facts_after_long_service_catalogue():
    source=ReportSource('W1','web','web','Profile','Intro. '+('Web mobile software. '*400)+' COMPANY PROFILE SAIGON TECH COMPANY LIMITED 設立 2018年12月 CEO Nguyen Huy.', metadata={'research_topics':['profile']})
    selected=_relevant_excerpt(source,max_chars=2200)
    assert len(selected)<=2200 and 'COMPANY PROFILE' in selected and '2018' in selected
    assert replace(source,excerpt=selected).id==source.id
    from pu.reporting.collection import _targeted_excerpt

    collected,truncated=_targeted_excerpt(source.excerpt,('company','about','ceo','設立'),900)
    assert truncated and len(collected)<=900 and '2018' in collected


def test_quote_recovery_uses_only_verbatim_value_and_retains_original_quote():
    source=ReportSource('E1','email','email','Synthetic','OCR hóa đơn PDF và biểu mẫu scan có kiểm tra thủ công. Chưa chọn bộ mẫu.')
    items=normalize_preparation([{'key':'input_documents','state':'self_reported','answer_status':'partial',
        'value':'Hóa đơn PDF và biểu mẫu scan','remaining_gap':'Chưa chọn bộ mẫu','scope':'pilot',
        'summary':'hóa đơn PDF và biểu mẫu scan','evidence_quote':'OCR hóa đơn ... Chưa chọn bộ mẫu','source_ids':['E1']}],{'E1'})
    assessed,errors=assess_preparation(items,{'E1':source},_text_support_reason)
    item=next(item for item in assessed if item['key']=='input_documents')
    assert not errors and item['answer_status']=='partial'
    assert item['evidence_quote']=='hóa đơn PDF và biểu mẫu scan'
    assert '...' in item['original_evidence_quote']
    items[4]['value']='Hóa đơn PDF và 999 biểu mẫu scan'
    assessed,_=assess_preparation(items,{'E1':source},_text_support_reason)
    assert next(item for item in assessed if item['key']=='input_documents')['answer_status']=='unknown'


def test_differing_founding_milestones_are_visible_without_merging_legal_identity():
    from pu.reporting.profile_checks import company_profile_checks

    vn=ReportSource('VN','web','web','VN','SGTech thành lập năm 2014.',url='https://saigon-tech.vn/')
    jp=ReportSource('JP','web','web','JP','COMPANY PROFILE 設立 2018年12月.',url='https://www.saigon-tech.vn/jp')
    checks=company_profile_checks([vn,jp])
    assert len(checks)==1 and '2014 [VN]' in checks[0]['message'] and '2018 [JP]' in checks[0]['message']
    assert 'Chưa xác minh đây là cùng pháp nhân' in checks[0]['message']
    assert not company_profile_checks([vn,replace(vn,id='NEW',excerpt='Thành lập năm 2015.')])
    assert not company_profile_checks([vn,replace(jp,url='https://saigon-tech.vn/news/partner-story',excerpt='Đối tác thành lập năm 2018.')])
    from pu.reporting.models import ReportContradiction

    report=_compact()
    report.metadata['company_profile_checks']=checks
    report.contradictions=[ReportContradiction('Mốc thành lập 2014 và 2018 trên hai trang cần đối chiếu.',('VN','JP'))]
    freeze_reading_view(report)
    assert len([note for note in report.metadata['reading_view']['open_items'] if '2014' in note])==1


def test_one_calendar_read_for_same_window_and_distinct_reads_for_different_partners(tmp_path,monkeypatch):
    import json

    from evals.deterministic.test_inbox_chat import build, seed

    app,_,_=build(tmp_path,monkeypatch)
    seed(app)
    seed(app,'beta.example','Beta')
    app.conn.execute("UPDATE crm_emails SET body_text=body_text || ' Có thể họp tuần tới không?' WHERE gmail_id=?",('acme.example-today',))
    app.conn.commit()
    result=app.respond('Hôm nay có email gì mới?')
    calls=[call for call in result.tool_calls if call['tool']=='read_week_availability']
    assert len(calls)==2
    windows={json.loads(row[0])['metadata']['availability']['scheduling_window']['week_start'] for row in app.conn.execute('SELECT payload_json FROM workspace_reports')}
    assert len(windows)==2
    assert 'classification' in result.timing_breakdown and 'partner_reports' in result.timing_breakdown
    # Asking explicitly for the next week gives both partners one common read.
    result=app.respond('Hôm nay có email gì mới? Kiểm tra lịch tuần tới giúp anh.')
    calls=[call for call in result.tool_calls if call['tool']=='read_week_availability']
    assert len(calls)==1
    assert len(result.reports)==2
    app.close()


def test_change_requested_week_invalidates_report_cache_even_when_slots_are_empty(tmp_path,monkeypatch):
    import json

    from evals.deterministic.test_inbox_chat import build, seed

    app,_,collected=build(tmp_path,monkeypatch)
    seed(app)
    first=app.respond('Hôm nay có email gì mới?')
    second=app.respond('Hôm nay có email gì mới? Kiểm tra lịch tuần tới giúp anh.')
    assert first.reports[0]['report_id']!=second.reports[0]['report_id']
    assert len(collected)==1  # Reuses company evidence, not the calendar/report.
    payload=json.loads(app.conn.execute('SELECT payload_json FROM workspace_reports WHERE report_id=?',(second.reports[0]['report_id'],)).fetchone()[0])
    assert payload['metadata']['availability']['scheduling_window']['intent']=='next_week'
    app.close()


def test_background_calendar_uses_same_email_week_and_keeps_coverage_enum(tmp_path):
    from pu.ops.briefing import BriefingService
    from pu.reporting.availability import requested_partner_availability

    service=BriefingService(tmp_path)
    workspace=service.repo.create('Saigon Tech','https://saigon-tech.vn')
    snapshot=requested_partner_availability(tmp_path,workspace,[{'source_type':'email','published_at':'2026-10-17T04:00:00+00:00',
        'content':'Có thể họp tuần tới không?'}],reference=REFERENCE)
    assert snapshot['scheduling_window']['week_start']=='2026-10-19'
    assert snapshot['coverage']=='local_only' and snapshot['slots']
    assert all(datetime.fromisoformat(slot['start']).date().isoformat()>='2026-10-19' for slot in snapshot['slots'])
