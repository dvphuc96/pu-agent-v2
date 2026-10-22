"""Counterexamples for rubric v5 and the compact reading contract."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
from types import SimpleNamespace
from zipfile import ZipFile

from evals.deterministic.test_report_gate_regressions import FakeJudgeProvider, _judge_payload
from evals.deterministic.test_report_quality_v2 import _materialize
from evals.helpers import admitted_judge_contract
from pu.core.interfaces.agents import AgentResult
from pu.evaluation.report import (
    DefaultEvaluationHarness,
    DeterministicReportEvaluator,
    LLMReportJudge,
)
from pu.orchestration.inbox_chat import inline_report
from pu.reporting.docx import render_docx
from pu.reporting.evidence import StructuredReportBuilder
from pu.reporting.models import ReportContradiction
from pu.reporting.preparation import normalize_preparation
from pu.reporting.reading_view import freeze_reading_view, prose_duplicates
from pu.reporting.render import ReportRenderer


def _compact():
    report = _materialize("good")
    report.sections = {
        "company_context": "Acme là công ty AI phục vụ bán lẻ [S2].\n- Acme có 120 nhân viên [S2].",
        "email_need": "Theo email, Alice đề nghị thảo luận AI pilot [S1].",
        "meeting_preparation": "Mục tiêu đề xuất: chọn pilot. Phòng ban nào thử nghiệm? Ai quyết định? Dữ liệu ở đâu? Ai duyệt bảo mật? Đo hiệu quả thế nào?",
    }
    report.metadata["partner_identity"] = {
        "status": "verified", "research_domain": "acme.example",
        "affiliation_warnings": ["Chưa có bằng chứng xác minh quyền đại diện."],
    }
    report.metadata["preparation_checklist"] = normalize_preparation([], {s.id for s in report.sources})
    report.missing_information = ["Chưa có mẫu tài liệu.", "Chưa có mẫu tài liệu."]
    freeze_reading_view(report)
    return report


def _evaluate(report):
    return DefaultEvaluationHarness(judge=LLMReportJudge(FakeJudgeProvider(_judge_payload(9)), "offline")).evaluate(report, contract=admitted_judge_contract())


def test_self_reported_contact_and_unknown_details_do_not_become_fully_verified():
    report = _compact()
    quote = "Alice states she is authorized to represent Acme."
    report.sources[0] = replace(report.sources[0], excerpt=report.sources[0].excerpt + " " + quote)
    report.metadata["preparation_checklist"] = normalize_preparation([
        {"key": "representative_authority", "state": "known", "source_ids": ["S1"],
         "summary": quote, "answer_status": "provided",
         "value": quote, "scope": "identity", "evidence_quote": quote},
    ], {s.id for s in report.sources})
    judge = json.loads(_judge_payload(9))
    judge["preparation_verdicts"] = [{"key": "representative_authority", "contains_answer": True, "scope_matches": True}]
    result = DefaultEvaluationHarness(judge=LLMReportJudge(FakeJudgeProvider(json.dumps(judge)), "offline")).evaluate(report, contract=admitted_judge_contract())
    assert result.release_allowed
    readiness = result.status_details["readiness"]
    assert readiness["discovery"] == "ready_with_limits"
    assert readiness["pilot"] == "needs_confirmation"
    assert readiness["contact_verification"] == "unverified"
    assert readiness["calendar_coverage"] == "unknown"
    assert result.metrics.meeting_readiness == 0.9
    checklist = {item["key"]: item for item in readiness["checklist"]}
    assert checklist["representative_authority"]["state"] == "self_reported"
    assert checklist["budget"]["state"] == "unknown"


def test_granular_numeric_or_invented_source_failure_cannot_be_waived():
    for item in (
        {"key": "pilot_users", "state": "known", "summary": "Acme has 999999 employees.", "source_ids": ["S2"]},
        {"key": "budget", "state": "known", "summary": "Approved budget.", "source_ids": ["S999"]},
    ):
        report = _compact()
        report.metadata["preparation_checklist"] = normalize_preparation([item], {s.id for s in report.sources})
        result = _evaluate(report)
        assert result.judge.score == 9
        assert not result.release_allowed
        assert any("Checklist" in finding for finding in result.findings)


def test_email_and_calendar_do_not_increase_public_publisher_diversity():
    report = _compact()
    report.sources = [source for source in report.sources if source.source_type != "news"]
    report.claims = [claim for claim in report.claims if "S4" not in claim.source_ids]
    result = DeterministicReportEvaluator().evaluate(report)
    assert result.metrics.public_publisher_count == 1
    assert result.metrics.source_diversity == 0.3333


def test_product_update_without_relevant_article_is_blocked_even_with_high_judge():
    report = _compact()
    report.sections["recent_updates"] = "Thông tin về màu sắc và vị ngọt sản phẩm [S2]."
    freeze_reading_view(report)
    result = _evaluate(report)
    assert not result.release_allowed
    assert any("Mục cập nhật" in finding for finding in result.findings)


def test_vague_meeting_preparation_does_not_pass_as_ready_brief():
    report = _compact()
    report.sections["meeting_preparation"] = "Đề xuất trao đổi thêm về AI."
    freeze_reading_view(report)
    result = _evaluate(report)
    assert not result.release_allowed
    assert result.status_details["readiness"]["discovery"] == "needs_review"


def test_duplicate_prose_reports_locations_without_deleting_unique_facts():
    report = _compact()
    repeated = "Đây là đoạn mô tả rất dài về quy trình và hệ thống của doanh nghiệp nhằm chuẩn bị nội dung cho một buổi trao đổi ban đầu với đối tác."
    report.sections["company_context"] = repeated + "\nUnique operating fact [S2]."
    report.sections["meeting_preparation"] = repeated.replace("doanh nghiệp", "công ty")
    freeze_reading_view(report)
    assert prose_duplicates(report)[0]["locations"] == ["company_context:1", "meeting_preparation:1"]
    assert "Unique operating fact" in report.sections["company_context"]


def test_revision_refreezes_view_without_changing_the_reviewed_snapshot():
    from pu.reporting.revisions import revise_report

    report = _compact()
    original = deepcopy(report.to_dict())
    revised = revise_report(original, {"sections": {"company_context": "New reviewed content [S2]."}})
    assert revised.metadata["reading_view"]["blocks"][0]["text"] == "New reviewed content [S2]."
    assert "New reviewed content" in revised.markdown
    assert original == report.to_dict()


def test_frozen_view_has_one_warning_and_same_unique_content_in_all_exports():
    report = _compact()
    report.contradictions = [ReportContradiction("Hai nguồn khác nhau về phạm vi vận hành.", ("S2", "S4"))]
    freeze_reading_view(report)
    warning = report.metadata["partner_identity"]["affiliation_warnings"][0]
    original = deepcopy(report.to_dict())
    renderer = ReportRenderer()
    outputs = [StructuredReportBuilder.render_markdown(report), renderer.render_html(report), renderer.render_print_html(report)]
    with ZipFile(BytesIO(render_docx(report.to_dict()))) as archive:
        outputs.append(archive.read("word/document.xml").decode())
    for output in outputs:
        assert output.count(warning) == 1
        assert output.count("Chưa có mẫu tài liệu.") == 1
        assert output.count("Hai nguồn khác nhau về phạm vi vận hành.") == 1
        assert "Acme" in output and "120" in output
    assert report.to_dict() == original  # Reading must not alter the approved snapshot.
    chat = inline_report(report.to_dict())
    assert chat.count(warning) == 1
    assert "Các điểm nổi bật" in chat


def test_backend_timing_uses_elapsed_turn_and_shared_envelope_for_two_reports(monkeypatch):
    from pu.ops import dashboard

    saved = []
    result = AgentResult(reply="Done", reports=[{"report_id": "one"}, {"report_id": "two"}], chat_message_id=7)
    agent = SimpleNamespace(
        respond=lambda *args, **kwargs: result,
        memory=SimpleNamespace(update_response_timing=lambda *args: saved.append(args)),
        settings=SimpleNamespace(model="offline", small_model="offline"),
    )
    clock = iter([100.0, 105.0, 110.0, 145.0])
    monkeypatch.setattr(dashboard.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(dashboard, "get_agent", lambda: agent)
    monkeypatch.setattr(dashboard, "maybe_rotate_session", lambda agent: None)
    events = []
    dashboard.chat_stream("hello", lambda kind, event: events.append((kind, event)))
    done = next(event for kind, event in events if kind == "done")
    assert done["response_timing"] == {"scope": "backend_response", "duration_seconds": 45.0,
                                       "phases": {"lock_wait": 5.0, "session_setup": 5.0, "agent_response": 35.0}}
    assert done["latency_ms"] == 45000
    assert len(done["reports"]) == 2
    assert saved == [(7, done["response_timing"])]


def test_timing_persists_on_exact_chat_row_and_does_not_modify_report(tmp_path):
    from evals.helpers import ScriptedProvider, make_pu

    app = make_pu(tmp_path, llm_provider=ScriptedProvider([]))
    first = app.memory.log_chat("one", "reply", meta={"reports": [{"report_id": "immutable"}]})
    second = app.memory.log_chat("two", "other", meta={"reports": []})
    app.memory.update_response_timing(first, {"scope": "backend_response", "duration_seconds": 45.5})
    first_meta = json.loads(app.conn.execute("SELECT meta FROM chat_log WHERE id=?", (first,)).fetchone()[0])
    second_meta = json.loads(app.conn.execute("SELECT meta FROM chat_log WHERE id=?", (second,)).fetchone()[0])
    assert first_meta["response_timing"]["duration_seconds"] == 45.5
    assert first_meta["reports"] == [{"report_id": "immutable"}]
    assert "response_timing" not in second_meta
    app.close()


def test_backend_benchmark_does_not_mix_or_sum_research_phase_records(tmp_path):
    from evals.benchmark_report_quality import benchmark, load_records

    records = [
        {"meta": {"model": "fixture", "provider": "offline", "response_timing": {"scope": "backend_response", "duration_seconds": value}}}
        for value in (17, 45, 85)
    ]
    records.append({"scope": "research_workflow", "duration_seconds": 1000})
    path = tmp_path / "sanitized-records.json"
    path.write_text(json.dumps(records))
    result = benchmark(load_records(path, scope="backend_response"), scope="backend_response")
    assert result["sample_count"] == 3 and result["excluded_records"] == 1
    assert result["p50_seconds"] == 45 and result["p95_seconds"] == 85
    assert result["cache_unknown"]["sample_count"] == 3
    assert result["by_provider_model"]["offline/fixture"]["sample_count"] == 3
