"""Phase 5 gates: span tree, redacted telemetry, per-owner cost, isolated evals.

Fixtures are synthetic users A and B. Nothing here is a real mailbox, token,
prompt, or customer record. OPS-01 proves a child span's parent. The baseline
tracer test only proves ``_trace_api`` survives ``Tracer.__init__``.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager, nullcontext

import pytest

from pu.config import Settings
from pu.core.interfaces.llm import LLMResponse, LLMUsage
from pu.db import connect
from pu.evaluation.homes import assign_eval_homes, prepare_eval_home
from pu.identity.directory import provision_user
from pu.identity.files import owner_root
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.seam import InternalPrincipalSeam
from pu.identity.worker_job import WorkerJob
from pu.loop.agent import run_loop
from pu.ops.agentops import SLOEvaluator, prometheus_text
from pu.ops.pricing import usage_summary
from pu.ops.tracing import Tracer, load_trace_events
from pu.persistence import SQLiteAgentEventRepository, SQLiteDatabase
from pu.tools.registry import ToolRegistry

CANARY = "sk-phase5canarysecretxx"
PROMPT = "phase5 prompt body alpha"
EMAIL = "phase5-inbox@fixture.example"
REPORT = "phase5 report body alpha"
BETA_TRACE = "beta-trace-body-phase5"
ALPHA_TRACE = "alpha-trace-body-phase5"


class _ParentSpan:
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent
        self.ended = False

    def end(self):
        self.ended = True


class _ParentApi:
    def set_span_in_context(self, span):
        return {"span": span}


class _ParentTracer:
    def __init__(self):
        self.spans = []

    def start_span(self, name, attributes=None):
        span = _ParentSpan(name, None)
        self.spans.append(span)
        return span

    def start_as_current_span(self, name, attributes=None, context=None):
        parent = context["span"] if context else None
        span = _ParentSpan(name, parent)
        self.spans.append(span)
        return nullcontext(span)


class _NoHarness:
    def execute(self, *_args, **_kwargs):
        raise AssertionError("the loop should not call a tool")


class _OneShot:
    def complete(self, _request, on_text=None):
        return LLMResponse(
            text="ok",
            usage=LLMUsage(input_tokens=1_000_000, output_tokens=500_000),
            finish_reason="end_turn",
        )


@contextmanager
def _attached(seam, principal):
    token = seam.attach(principal)
    try:
        yield
    finally:
        seam.detach(token)


def _open(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    conn = connect(home)
    user_a = provision_user(conn)
    user_b = provision_user(conn)
    conn.commit()
    conn.close()
    return home, InternalPrincipalSeam(), user_a, user_b


def _settings(home, **overrides):
    settings = Settings(
        home=home,
        provider=overrides.pop("provider", "openai"),
        model=overrides.pop("model", "gpt-4.1-mini"),
        otel_endpoint="",
        **overrides,
    )
    settings.ensure_home()
    return settings


def _usage_text(home, owner_user_id: str) -> str:
    paths = [
        home / "usage.jsonl",
        owner_root(home, owner_user_id) / "usage.jsonl",
    ]
    chunks = []
    for path in paths:
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_ops01_child_span_is_parented_under_the_workflow(tmp_path):
    settings = _settings(tmp_path / "home")
    tracer = Tracer(settings)
    otel = _ParentTracer()
    tracer._otel_tracer = otel
    tracer._trace_api = _ParentApi()
    tracer.event("workflow_started", {"workflow_id": "wf-ops01", "workflow": "research"})
    tracer.event("tool", {"workflow_id": "wf-ops01", "tool": "search_web", "output": "ok"})
    roots = [span for span in otel.spans if span.name == "workflow.research"]
    children = [span for span in otel.spans if span.name == "tool.search_web"]
    assert len(roots) == 1
    assert len(children) == 1
    assert children[0].parent is roots[0]
    assert tracer._trace_api is not None


def test_ops02_usage_ledger_omits_canary(tmp_path):
    home, seam, user_a, _user_b = _open(tmp_path)
    settings = _settings(home, model=CANARY, provider="openai")
    tracer = Tracer(settings)
    with _attached(seam, user_a):
        tracer.event(
            "llm",
            {
                "usage": {"in": CANARY, "out": 3},
                "prompt": CANARY,
                "output": CANARY,
                "model": CANARY,
                "api_key": CANARY,
            },
        )
    ledger = _usage_text(home, user_a.user_id)
    assert ledger
    assert CANARY not in ledger
    record = json.loads(ledger.strip().splitlines()[-1])
    assert record["in"] == 0
    assert record["out"] == 3
    assert "prompt" not in record
    assert "output" not in record
    assert "api_key" not in record


def test_ops03_llm_call_records_tokens_and_cost_for_the_principal(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    settings = _settings(home)
    tracer = Tracer(settings)
    with _attached(seam, user_a):
        tracer.event(
            "llm",
            {
                "usage": {"in": 1_000_000, "out": 500_000},
                "owner_user_id": user_b.user_id,
                "prompt": PROMPT,
            },
        )
        run_loop(
            _OneShot(),
            "gpt-4.1-mini",
            "system",
            [{"role": "user", "content": "hello"}],
            ToolRegistry(),
            _NoHarness(),
            observer=tracer.event,
        )
    lines = [
        json.loads(line)
        for line in _usage_text(home, user_a.user_id).splitlines()
        if line.strip()
    ]
    assert len(lines) == 2
    direct, looped = lines
    assert direct["owner_user_id"] == user_a.user_id
    assert direct["owner_user_id"] != user_b.user_id
    assert direct["in"] == 1_000_000
    assert direct["out"] == 500_000
    # gpt-4.1-mini is $0.40 / $1.60 per million tokens.
    assert direct["cost"] == 1.2
    assert looped["owner_user_id"] == user_a.user_id
    assert looped["in"] == 1_000_000
    assert looped["out"] == 500_000
    assert looped["cost"] == 1.2
    assert PROMPT not in _usage_text(home, user_a.user_id)
    shared = home / "usage.jsonl"
    if shared.is_file():
        assert user_a.user_id not in shared.read_text(encoding="utf-8")
    summary = None
    with _attached(seam, user_a):
        summary = usage_summary(home)
    assert summary["calls"] == 2
    assert summary["total_in"] == 2_000_000
    assert summary["total_cost"] == 2.4


def test_ops03_worker_ledger_uses_the_job_owner(tmp_path):
    home, _seam, user_a, user_b = _open(tmp_path)
    tracer = Tracer(_settings(home))
    job = WorkerJob.open(
        owner_user_id=user_b.user_id,
        workspace_id=user_b.workspace_id,
        expires_at=time.time() + 60,
    )
    try:
        tracer.event(
            "llm",
            {"usage": {"in": 2_000, "out": 0}, "owner_user_id": user_a.user_id},
        )
    finally:
        job.close()
    record = json.loads(_usage_text(home, user_b.user_id).strip().splitlines()[-1])
    assert record["owner_user_id"] == user_b.user_id
    assert record["in"] == 2_000
    assert record["cost"] == 0.0008
    shared = home / "usage.jsonl"
    if shared.is_file():
        assert user_b.user_id not in shared.read_text(encoding="utf-8")


def test_ops04_other_owner_cannot_read_traces_admin_sees_counts_only(tmp_path):
    home, seam, user_a, user_b = _open(tmp_path)
    conn = connect(home)
    admin_user = provision_user(conn)
    conn.commit()
    conn.close()
    admin = Principal(PrincipalKind.PLATFORM_ADMIN, admin_user.user_id, admin_user.workspace_id)
    settings = _settings(home)
    tracer = Tracer(settings)
    database = SQLiteDatabase.from_home(home)
    repo = SQLiteAgentEventRepository(database)
    from pu.ops.agentops import AgentOpsHarness

    with _attached(seam, user_b):
        AgentOpsHarness(repo, tracer=tracer).publish(
            "llm",
            {
                "output": BETA_TRACE,
                "prompt": PROMPT,
                "email": EMAIL,
                "report": REPORT,
                "usage": {"in": 10, "out": 4},
            },
        )
    with _attached(seam, user_a):
        AgentOpsHarness(repo, tracer=tracer).publish(
            "tool_complete",
            {"output": ALPHA_TRACE, "prompt": "alpha prompt only"},
        )
        listed = json.dumps(repo.list())
        visible, _errors = load_trace_events(home)
        rendered = json.dumps(visible)
        with pytest.raises(PermissionError):
            repo.platform_aggregate()
    assert ALPHA_TRACE in rendered
    assert BETA_TRACE not in rendered
    assert BETA_TRACE not in listed
    assert PROMPT not in listed
    assert EMAIL not in listed
    assert REPORT not in listed
    with _attached(seam, admin):
        admin_events, _admin_errors = load_trace_events(home)
        assert admin_events == []
        assert repo.list() == []
        totals = repo.platform_aggregate()
        text = prometheus_text(totals, SLOEvaluator(settings).evaluate(totals))
        admin_usage = json.dumps(usage_summary(home))
    assert totals["events"] == 2
    blob = json.dumps(totals) + text + admin_usage
    assert BETA_TRACE not in blob
    assert ALPHA_TRACE not in blob
    assert PROMPT not in blob
    assert EMAIL not in blob
    assert REPORT not in blob
    beta_file = owner_root(home, user_b.user_id)
    alpha_file = owner_root(home, user_a.user_id)
    assert beta_file != alpha_file
    beta_text = "".join(path.read_text(encoding="utf-8") for path in beta_file.rglob("*.jsonl"))
    assert BETA_TRACE in beta_text


def test_ops05_two_user_evals_do_not_share_home_database_or_traces(tmp_path):
    root = tmp_path / "suite"
    shared = root / ".pu"
    shared.mkdir(parents=True)
    (shared / "marker.txt").write_text("shared-home", encoding="utf-8")
    owner_a = "11111111-1111-4111-8111-111111111111"
    owner_b = "33333333-3333-4333-8333-333333333333"
    with pytest.raises(ValueError):
        assign_eval_homes(root, [".pu"])
    home_a = prepare_eval_home(root, owner_a)
    home_b = prepare_eval_home(root, owner_b)
    assert home_a != home_b
    assert home_a != shared and home_b != shared
    assert home_a.name != ".pu" and home_b.name != ".pu"
    assert (home_a / "state.db").is_file()
    assert (home_b / "state.db").is_file()
    assert (home_a / "state.db") != (home_b / "state.db")
    Tracer(_settings(home_a)).event("tool", {"output": ALPHA_TRACE})
    Tracer(_settings(home_b)).event("tool", {"output": BETA_TRACE})
    traces_a = sorted((home_a / "traces").glob("*.jsonl"))
    traces_b = sorted((home_b / "traces").glob("*.jsonl"))
    assert len(traces_a) == 1 and len(traces_b) == 1
    assert traces_a[0] != traces_b[0]
    text_a = traces_a[0].read_text(encoding="utf-8")
    text_b = traces_b[0].read_text(encoding="utf-8")
    assert ALPHA_TRACE in text_a and BETA_TRACE not in text_a
    assert BETA_TRACE in text_b and ALPHA_TRACE not in text_b
    shared_text = "\n".join(path.read_text(encoding="utf-8") for path in shared.rglob("*") if path.is_file())
    assert ALPHA_TRACE not in shared_text
    assert BETA_TRACE not in shared_text
    assert (shared / "marker.txt").read_text(encoding="utf-8") == "shared-home"
    assert not (shared / "state.db").exists()


def test_ops06_metrics_do_not_embed_prompt_email_or_report(tmp_path):
    home, seam, user_a, _user_b = _open(tmp_path)
    settings = _settings(home)
    database = SQLiteDatabase.from_home(home)
    repo = SQLiteAgentEventRepository(database)
    from pu.ops.agentops import AgentOpsHarness

    tracer = Tracer(settings)
    with _attached(seam, user_a):
        AgentOpsHarness(repo, tracer=tracer).publish(
            "llm",
            {
                "prompt": PROMPT,
                "email": EMAIL,
                "report": REPORT,
                "output": BETA_TRACE,
                "usage": {"in": 8, "out": 2},
                "latency_ms": 15,
            },
        )
        metrics = repo.aggregate()
        text = prometheus_text(metrics, SLOEvaluator(settings).evaluate(metrics))
    poisoned = prometheus_text(
        {
            "events": 1,
            "prompt": PROMPT,
            "email": EMAIL,
            "report": REPORT,
            "by_kind": {EMAIL: 1},
        },
        {
            "healthy": True,
            "checks": [
                {"name": EMAIL, "ok": True},
                {"name": "tool_error_rate", "ok": False, "detail": REPORT},
            ],
        },
    )
    assert "pu_agentops_events_total 1" in text
    assert "pu_tool_error_rate" in poisoned
    for document in (text, poisoned, json.dumps(metrics)):
        assert PROMPT not in document
        assert EMAIL not in document
        assert REPORT not in document
        assert BETA_TRACE not in document
