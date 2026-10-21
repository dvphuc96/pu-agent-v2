"""Counterexamples from C4: Japanese calendar notation and unchanged blockers."""

from copy import deepcopy
from dataclasses import replace

import pytest

from evals.deterministic.test_report_editorial_calibration import _compact, _evaluate
from pu.evaluation.report import _number_literals, _text_support_reason
from pu.reporting.models import ReportClaim
from pu.reporting.numeric_evidence import (
    compare_numeric,
    extract_numeric,
    number_literals,
    number_units,
)
from pu.reporting.repair import plan_repair, select_repair_candidate


def test_c4_years_are_supported_by_vietnamese_and_japanese_primary_excerpts():
    supported, _ = _text_support_reason(
        'Các trang công ty nêu năm thành lập 2014, 2018 và 2019.',
        ['Công ty thành lập năm 2014.', 'SGTech được thành lập năm 2019.', 'COMPANY PROFILE 設立2018年12月'],
    )
    assert supported
    assert '2018' in _number_literals('設立２０１８年１２月')


def test_a_wrong_year_stays_hard_even_when_the_judge_is_positive():
    report = _compact()
    report.sources[1] = replace(report.sources[1], excerpt=report.sources[1].excerpt + ' 設立2018年12月')
    report.claims.append(ReportClaim('YEAR', 'Công ty thành lập năm 2017.', 'company_context', ('S2',)))
    result = _evaluate(report)
    assert not result.release_allowed
    assert result.metrics.status_details['claims']['YEAR']['support_reason'] == 'numeric_or_date_mismatch'


@pytest.mark.parametrize('source', ['設立2018年12月', '設立２０１８年１２月', '2018/12', '12/2018', 'tháng 12 năm 2018'])
def test_year_month_precision_is_preserved(source):
    assert compare_numeric('tháng 12/2018', [source])['supported']
    assert compare_numeric('2018', [source])['supported']
    assert not compare_numeric('tháng 11/2018', [source, 'Có 11 nhân viên.'])['supported']
    assert not compare_numeric('05/12/2018', [source, 'Có 5 nhân viên.'])['supported']


def test_full_dates_unicode_spans_and_invalid_calendar_values():
    raw='会社は２０１８年１２月５日設立'
    evidence=extract_numeric(raw)
    literal=next(item for item in evidence.literals if item.kind=='calendar_date')
    assert raw[literal.start:literal.end]==literal.raw_text=='２０１８年１２月５日'
    assert literal.canonical_value=='2018-12-05' and literal.precision=='day'
    assert compare_numeric('05/12/2018',[raw])['supported']
    assert not compare_numeric('2018年13月',['2018年13月'])['supported']
    assert not compare_numeric('2018年2月30日',['2018年2月30日'])['supported']


def test_identifiers_duration_and_decimal_units_remain_distinct():
    assert not number_literals('ISO2018')
    assert not number_literals('ISO2018年')
    assert number_units('5年')=={('5','years')}
    assert not compare_numeric('2018 năm',['2018年12月'])['supported']
    assert number_literals('1,2 triệu và 1.500 người')=={'1.2','1500'}
    assert not compare_numeric('1,2 triệu',['12 triệu'])['supported']
    assert not compare_numeric('15 người',['15 triệu'])['supported']


def test_unhandled_era_is_a_limitation_not_a_silent_numeric_pass():
    result=compare_numeric('Thành lập năm 2018',['設立 平成30年'])
    assert not result['supported'] and result['reason']=='numeric_notation_unhandled'
    assert compare_numeric('Thành lập năm 2018',['設立 平成2018年'])['reason']=='numeric_notation_unhandled'
    report=_compact()
    report.sources[1]=replace(report.sources[1],excerpt=report.sources[1].excerpt+' 設立 平成30年')
    report.claims.append(ReportClaim('LIMIT','Công ty thành lập năm 2018.','company_context',('S2',)))
    evaluation=_evaluate(report)
    assert not evaluation.release_allowed
    decision=plan_repair(report,evaluation)
    assert decision['decision']=='skip' and decision['reason']=='evaluator_limitation'
    evaluation.status_details.update(semantic_review='failed',semantic_blockers=['criterion:nondup'])
    assert plan_repair(report,evaluation)['decision']=='skip'  # Editorial-only changes cannot clear the remaining hard limitation.


def test_snippet_cannot_supply_a_missing_year_when_an_unrelated_primary_is_cited():
    report=_compact()
    report.sources.append(replace(report.sources[1],id='SNIP',excerpt='Thành lập năm 2018',metadata={'snippet_only':True}))
    report.claims.append(ReportClaim('YEAR','Công ty thành lập năm 2018.','company_context',('S2','SNIP')))
    result=_evaluate(report)
    assert not result.release_allowed and not result.metrics.status_details['claims']['YEAR']['supported']


def _broken():
    report=_compact()
    report.claims.append(ReportClaim('BAD','Acme có 999999 nhân viên.','company_context',('S2',)))
    return report,_evaluate(report)


def test_fewer_findings_and_changed_claim_id_do_not_fix_the_blocker():
    report,before=_broken()
    before.findings=['one','two','three','four']
    candidate=deepcopy(report)
    candidate.claims[-1]=replace(candidate.claims[-1],id='RENAMED')
    after=_evaluate(candidate)
    after.findings=['one','two','three']
    selection=select_repair_candidate(report,before,candidate,after)
    assert not selection['accepted'] and selection['outcome']=='no_improvement'
    assert not selection['resolved'] and not selection['new']


def test_fewer_real_blockers_can_only_be_an_improved_draft():
    report,_=_broken()
    report.claims.append(ReportClaim('BAD2','Acme có 888888 nhà máy.','company_context',('S2',)))
    before=_evaluate(report)
    candidate=deepcopy(report)
    candidate.claims.pop()
    after=_evaluate(candidate)
    selection=select_repair_candidate(report,before,candidate,after)
    assert selection['accepted'] and selection['outcome']=='improved_draft'
    assert not after.release_allowed and selection['remaining']


def test_new_hard_failure_or_lost_supported_request_rejects_candidate():
    report,before=_broken()
    candidate=deepcopy(report)
    candidate.claims[-1]=replace(candidate.claims[-1],text='Acme có 888888 nhân viên.')
    assert select_repair_candidate(report,before,candidate,_evaluate(candidate))['outcome']=='invalid_candidate'
    candidate=_compact()
    after=_evaluate(candidate)
    after.metrics.status_details['field_coverage']['request']['supported']=False
    assert select_repair_candidate(report,before,candidate,after)['outcome']=='invalid_candidate'


def test_coincidental_copyright_year_cannot_override_a_negative_semantic_verdict():
    import json

    from evals.deterministic.test_report_gate_regressions import FakeJudgeProvider, _judge_payload
    from pu.evaluation.report import DefaultEvaluationHarness, LLMReportJudge

    report=_compact()
    report.sources[1]=replace(report.sources[1],excerpt=report.sources[1].excerpt+' Copyright 2019.')
    report.claims.append(ReportClaim('COPYRIGHT','Công ty thành lập năm 2019.','company_context',('S2',)))
    payload=json.loads(_judge_payload(9))
    payload['claim_verdicts']=[{'id':'COPYRIGHT','supported':False,'reason':'Copyright không phải năm thành lập.'}]
    evaluation=DefaultEvaluationHarness(judge=LLMReportJudge(FakeJudgeProvider(json.dumps(payload)),'offline')).evaluate(report)
    assert not evaluation.release_allowed
    assert evaluation.metrics.unsupported_claims==1
    assert evaluation.metrics.status_details['claims']['COPYRIGHT']['support_reason']=='semantic_rejected'


def test_profile_warning_is_frozen_once_without_deleting_other_company_facts():
    from pu.reporting.reading_view import freeze_reading_view

    report=_compact()
    warning='Các trang nêu mốc thành lập khác nhau: 2014, 2018 và 2019 [W2][W3][W8].'
    unique='Công ty có quy trình phát triển phần mềm theo dự án [S2].'
    report.sections['company_context']=unique+' '+warning
    original=report.sections['company_context']
    report.metadata['company_profile_checks']=[{'years':['2014','2018','2019'],'source_ids':['W2','W3','W8'],'message':warning}]
    freeze_reading_view(report)
    view=report.metadata['reading_view']
    context=next(block['text'] for block in view['blocks'] if block['key']=='company_context')
    assert unique in context and warning not in context
    assert view['open_items'].count(warning)==1
    assert report.sections['company_context']==original


def test_editorial_progress_is_measured_by_failed_criteria_not_finding_count():
    import json

    from evals.deterministic.test_report_gate_regressions import FakeJudgeProvider, _judge_payload
    from pu.evaluation.report import DefaultEvaluationHarness, LLMReportJudge

    report=_compact()
    def assess(nondup):
        payload=json.loads(_judge_payload(9))
        payload['criteria'].update(nondup=nondup,relevance=4)
        return DefaultEvaluationHarness(judge=LLMReportJudge(FakeJudgeProvider(json.dumps(payload)),'offline')).evaluate(report)
    before,after=assess(4),assess(8)
    selection=select_repair_candidate(report,before,deepcopy(report),after)
    assert selection['accepted'] and selection['outcome']=='improved_draft'
    assert 'semantic:criterion:nondup' in selection['resolved']
    assert not after.release_allowed
