"""Phase 3 gates: typed requests, one workflow row, owner-keyed checkpoints.

Fixtures are synthetic users A and B. Nothing here is a real mailbox, token,
or customer record.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

from evals.helpers import ScriptedProvider, response, text_block, tool_block
from pu.adapters import GraphWorkflowEngine
from pu.config import Settings
from pu.core.container import create_application
from pu.core.interfaces.agents import AgentResult, AgentRunRequest
from pu.core.interfaces.events import AgentEvent
from pu.core.interfaces.orchestration import ResearchWorkflowRequest
from pu.core.interfaces.tools import ToolContext
from pu.db import connect
from pu.graph import END, START, Graph, Node, run_graph
from pu.graph.nodes import agent_node, llm_node
from pu.harness import DefaultSecurityHarness, DefaultToolHarness, InMemoryToolAuditSink
from pu.identity.contract import AgentRequest, AgentRequestRejected, invoke_tool
from pu.identity.directory import provision_user
from pu.identity.principal import Principal, PrincipalKind
from pu.identity.seam import InternalPrincipalSeam
from pu.identity.worker_job import WorkerJob, owner_from_grant
from pu.ops.briefing import BriefingService
from pu.orchestration.research import WorkflowExecutionError
from pu.persistence import SQLiteAgentEventRepository, SQLiteDatabase, SQLiteWorkflowRepository
from pu.runtime import DefaultAgentRuntime
from pu.tools.registry import Tool, ToolRegistry

SECRET = "fixture-checkpoint-secret"
EVENT_SECRET = "fixture-event-secret"


@contextmanager
def _as(seam: InternalPrincipalSeam, principal: Principal):
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
    return home, conn, InternalPrincipalSeam(), user_a, user_b


def _counts(home: Path, stage: str, workflow_id: str) -> tuple[int, int]:
    database = SQLiteDatabase.from_home(home)
    with database.connection() as conn:
        runs = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0]
        stages = conn.execute(
            """SELECT COUNT(*) FROM workflow_stage_checkpoints
               WHERE workflow_id=? AND stage_name=?""",
            (workflow_id, stage),
        ).fetchone()[0]
    return int(runs), int(stages)


def test_p3_01_missing_principal_or_owner_is_rejected_before_model_or_tool():
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(Tool(
        name="echo",
        description="echo",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        fn=lambda text: (calls.append(text), text)[1],
        capability="test:read",
        required_scope="test:read",
    ))
    harness = DefaultToolHarness(registry, DefaultSecurityHarness(), InMemoryToolAuditSink())
    provider = ScriptedProvider([
        response([tool_block("echo", {"text": SECRET})], "tool_use"),
        response([text_block("should-not-run")]),
    ])
    runtime = DefaultAgentRuntime(provider, harness)
    missing = AgentRequest(principal=None, owner_user_id="", workspace_id="")
    with pytest.raises(AgentRequestRejected):
        runtime.run(AgentRunRequest(
            model="test",
            system="test",
            messages=[{"role": "user", "content": "go"}],
            tools=registry,
            contract=missing,
        ))
    user_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())
    principal = Principal(PrincipalKind.USER, user_id, workspace_id)
    missing_owner = AgentRequest(
        principal=principal,
        owner_user_id="",
        workspace_id=workspace_id,
        agent_scopes=frozenset({"test:read"}),
        tool_scopes=frozenset({"test:read"}),
    )
    with pytest.raises(AgentRequestRejected):
        invoke_tool(harness, "echo", {"text": SECRET}, missing_owner)
    assert calls == []
    assert provider.requests == []

    admitted = AgentRequest(
        principal=principal,
        owner_user_id=user_id,
        workspace_id=workspace_id,
        agent_scopes=frozenset({"test:read"}),
        tool_scopes=frozenset({"test:read"}),
    )
    result = invoke_tool(
        harness,
        "echo",
        {"text": "ok"},
        admitted,
        scopes=frozenset({"test:read"}),
        capabilities=frozenset({"test:read"}),
    )
    assert result.ok is True
    assert calls == ["ok"]


class _StopAfterEmail:
    def __init__(self):
        self.calls: list[str] = []

    def run(self, request, observer=None):
        agent_id = request.tool_context.agent_id
        self.calls.append(agent_id)
        if agent_id == "email-agent":
            return AgentResult(reply=SECRET)
        raise RuntimeError("stop after email")


def test_p3_02_resume_keeps_one_run_and_skips_completed_stages(tmp_path):
    first = _StopAfterEmail()
    app = create_application(
        settings=Settings(home=tmp_path, api_key="offline", gmail=False, graph_workflows=False),
        llm_provider=ScriptedProvider([]),
        agent_runtime=first,
    )
    with pytest.raises(WorkflowExecutionError) as err:
        app.run_research_workflow("Prepare the fixture brief")
    workflow_id = err.value.workflow_id
    runs, stages = _counts(tmp_path, "email", workflow_id)
    assert runs == 1
    assert stages == 1
    assert first.calls == ["email-agent", "company-info-agent"]
    app.close()

    second = _StopAfterEmail()
    app2 = create_application(
        settings=Settings(home=tmp_path, api_key="offline", gmail=False, graph_workflows=False),
        llm_provider=ScriptedProvider([]),
        agent_runtime=second,
    )
    with pytest.raises(WorkflowExecutionError):
        app2.resume_research_workflow(workflow_id)
    runs, stages = _counts(tmp_path, "email", workflow_id)
    assert runs == 1
    assert stages == 1
    assert "email-agent" not in second.calls
    assert second.calls == ["company-info-agent"]
    app2.close()


def test_p3_02_graph_resume_reuses_the_same_run_row(tmp_path):
    connect(tmp_path).close()
    repository = SQLiteWorkflowRepository(SQLiteDatabase.from_home(tmp_path))
    calls: list[str] = []

    def one(state):
        calls.append("one")
        return {"value": state["seed"] + 1}

    graph = Graph("phase3-shared")
    graph.add_node(Node("one", one))
    graph.add_edge(START, "one")
    graph.add_edge("one", END)
    engine = GraphWorkflowEngine(repository=repository)
    state = {"seed": 4, "_workflow_run_id": "wf-graph"}
    assert engine.run(graph, state)["value"] == 5
    assert engine.run(graph, {"seed": 4, "_workflow_run_id": "wf-graph"})["value"] == 5
    assert calls == ["one"]
    runs, stages = _counts(tmp_path, "one", "wf-graph")
    assert runs == 1
    assert stages == 1
    # A research open of the same id does not insert a second state row.
    repository.open_run("wf-graph", ResearchWorkflowRequest(prompt="same run"))
    runs, stages = _counts(tmp_path, "one", "wf-graph")
    assert runs == 1
    assert stages == 1


def test_p3_03_checkpoint_of_a_is_not_readable_as_b(tmp_path):
    home, conn, seam, user_a, user_b = _open(tmp_path)
    workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
    events = SQLiteAgentEventRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_a):
        workflows.create("wf-a", ResearchWorkflowRequest(prompt=SECRET))
        workflows.save_checkpoint("wf-a", "email", AgentResult(reply=SECRET))
        events.append(AgentEvent(
            kind="workflow_stage_completed",
            payload={"stage": "email", "body": EVENT_SECRET},
            workflow_id="wf-a",
        ))
    with _as(seam, user_b):
        workflows.create("wf-b", ResearchWorkflowRequest(prompt="fixture-b"))
        assert workflows.checkpoints("wf-a") == {}
        assert workflows.get("wf-a") is None
        assert events.for_run("wf-a") == []
        own = workflows.checkpoints("wf-b")
        assert SECRET not in str(own)
        assert EVENT_SECRET not in str(events.for_run("wf-b"))
    conn.close()


def test_p3_04_worker_loses_owner_after_job_end_or_lease_expiry(tmp_path):
    home, conn, seam, user_a, _user_b = _open(tmp_path)
    workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_a):
        workflows.create("wf-a", ResearchWorkflowRequest(prompt=SECRET))
        workflows.save_checkpoint("wf-a", "email", AgentResult(reply=SECRET))
        conn.execute(
            """INSERT INTO briefing_state(key, value, owner_user_id)
               VALUES('lease_until', ?, ?)""",
            (str(int(time.time() + 120)), user_a.user_id),
        )
        conn.commit()

    job = WorkerJob.open(
        owner_user_id=user_a.user_id,
        workspace_id=user_a.workspace_id,
        expires_at=time.time() + 120,
        db_path=str(home / "state.db"),
        watch_db_lease=False,
    )
    try:
        assert workflows.checkpoints("wf-a")["email"].result.reply == SECRET
        job.finish()
        with pytest.raises(PermissionError) as ended:
            workflows.checkpoints("wf-a")
        assert SECRET not in str(ended.value)
    finally:
        job.close()

    with _as(seam, user_a):
        assert workflows.checkpoints("wf-a")["email"].result.reply == SECRET
        conn.execute(
            """UPDATE briefing_state SET value=?
               WHERE key='lease_until' AND owner_user_id=?""",
            (str(int(time.time() - 10)), user_a.user_id),
        )
        conn.commit()

    expired = WorkerJob.open(
        owner_user_id=user_a.user_id,
        workspace_id=user_a.workspace_id,
        expires_at=time.time() + 120,
        db_path=str(home / "state.db"),
        watch_db_lease=True,
    )
    try:
        with pytest.raises(PermissionError) as leased:
            workflows.checkpoints("wf-a")
        assert SECRET not in str(leased.value)
    finally:
        expired.close()

    with _as(seam, user_a):
        assert workflows.checkpoints("wf-a")["email"].result.reply == SECRET
    conn.close()


def test_production_modules_do_not_default_local_user():
    root = Path(__file__).resolve().parents[2] / "pu"
    # legacy_import maps the old label. contract.py names it only to reject it.
    allowed = {"identity/legacy_import.py", "identity/contract.py"}
    offenders = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "local-user" not in text and "graph-local-user" not in text:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in allowed:
            continue
        offenders.append(relative)
    assert offenders == []


def test_p3_01_graph_chat_makes_no_provider_call_without_an_admitted_principal(tmp_path):
    provider = ScriptedProvider([response([text_block("should-not-run")])])
    app = create_application(
        settings=Settings(home=tmp_path, api_key="offline", gmail=False, graph_workflows=True),
        llm_provider=provider,
    )
    job = WorkerJob.open(
        owner_user_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        expires_at=time.time() + 120,
    )
    job.finish()
    try:
        with pytest.raises(PermissionError):
            app.respond("thanks")
    finally:
        job.close()
    assert provider.requests == []
    app.close()


def test_p3_01_llm_node_admits_before_the_provider():
    provider = ScriptedProvider([response([text_block("should-not-run")])])
    rejected = llm_node(
        "classify",
        "Message: {message}",
        "route",
        provider=provider,
        model="small-model",
        request=AgentRequest(principal=None),
    )
    with pytest.raises(AgentRequestRejected):
        rejected.fn({"message": "thanks"})
    assert provider.requests == []

    user_id = str(uuid.uuid4())
    workspace_id = str(uuid.uuid4())
    admitted = AgentRequest(
        principal=Principal(PrincipalKind.USER, user_id, workspace_id),
        owner_user_id=user_id,
        workspace_id=workspace_id,
    )
    allowed = ScriptedProvider([response([text_block("quick")])])
    node = llm_node(
        "classify",
        "Message: {message}",
        "route",
        provider=allowed,
        model="small-model",
        request=admitted,
    )
    assert node.fn({"message": "thanks"}) == {"route": "quick"}
    assert len(allowed.requests) == 1


def test_p3_01_string_principal_does_not_reach_the_model():
    provider = ScriptedProvider([
        response([text_block("should-not-run")]),
        response([text_block("should-not-run")]),
    ])
    registry = ToolRegistry()
    harness = DefaultToolHarness(registry, DefaultSecurityHarness(), InMemoryToolAuditSink())
    runtime = DefaultAgentRuntime(provider, harness)
    with pytest.raises(AgentRequestRejected):
        runtime.run(AgentRunRequest(
            model="test",
            system="test",
            messages=[{"role": "user", "content": "hello"}],
            tools=registry,
            tool_context=ToolContext(principal="local-user"),
        ))
    node = agent_node(
        "full_agent",
        out_key="result",
        provider=provider,
        model="test",
        system="test",
        tools=registry,
        tool_context=ToolContext(principal="local-user"),
    )
    graph = Graph("string-principal")
    graph.add_node(node)
    graph.add_edge(START, node.name)
    graph.add_edge(node.name, END)
    state = run_graph(graph, {"message": "hello"})
    assert provider.requests == []
    assert "full_agent" in state["errors"]


def test_lease_read_error_fails_closed(tmp_path):
    job = WorkerJob.open(
        owner_user_id=str(uuid.uuid4()),
        workspace_id=str(uuid.uuid4()),
        expires_at=time.time() + 120,
        db_path=str(tmp_path),
        watch_db_lease=True,
    )
    try:
        with pytest.raises(PermissionError) as err:
            owner_from_grant()
        assert str(err.value) == "worker job ended or lease expired"
    finally:
        job.close()


def test_briefing_worker_does_not_read_while_lease_is_held_or_expired(tmp_path):
    home, conn, seam, user_a, _user_b = _open(tmp_path)
    workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_a):
        workflows.create("wf-a", ResearchWorkflowRequest(prompt=SECRET))
        workflows.save_checkpoint("wf-a", "email", AgentResult(reply=SECRET))
        conn.execute(
            """INSERT INTO briefing_state(key, value, owner_user_id)
               VALUES('lease_owner', 'other-process', ?)""",
            (user_a.user_id,),
        )
        conn.execute(
            """INSERT INTO briefing_state(key, value, owner_user_id)
               VALUES('lease_until', ?, ?)""",
            (str(int(time.time() + 120)), user_a.user_id),
        )
        conn.commit()
    service = BriefingService(home)
    seen: list[str] = []

    def read_secret():
        seen.append(workflows.checkpoints("wf-a")["email"].result.reply)

    assert service._run_as_owner(user_a.user_id, read_secret) is None
    assert seen == []

    with _as(seam, user_a):
        conn.execute(
            """UPDATE briefing_state SET value=?
               WHERE key='lease_until' AND owner_user_id=?""",
            (str(int(time.time() - 10)), user_a.user_id),
        )
        conn.commit()

    def read_after_claim():
        with service.repo.database.connection() as owned:
            row = owned.execute(
                """SELECT value FROM briefing_state
                   WHERE key='lease_until' AND owner_user_id = pu_current_owner()"""
            ).fetchone()
        assert float(row[0]) > time.time()
        seen.append(workflows.checkpoints("wf-a")["email"].result.reply)

    service._run_as_owner(user_a.user_id, read_after_claim)
    assert seen == [SECRET]
    called: list[str] = []
    assert service._run_as_owner(str(uuid.uuid4()), lambda: called.append("ran")) is None
    assert called == []
    conn.close()


def test_missing_lease_until_fails_closed(tmp_path):
    home, conn, seam, user_a, _user_b = _open(tmp_path)
    workflows = SQLiteWorkflowRepository(SQLiteDatabase.from_home(home))
    with _as(seam, user_a):
        workflows.create("wf-a", ResearchWorkflowRequest(prompt=SECRET))
        workflows.save_checkpoint("wf-a", "email", AgentResult(reply=SECRET))
    job = WorkerJob.open(
        owner_user_id=user_a.user_id,
        workspace_id=user_a.workspace_id,
        expires_at=time.time() + 120,
        db_path=str(home / "state.db"),
        watch_db_lease=True,
    )
    try:
        with pytest.raises(PermissionError) as err:
            workflows.checkpoints("wf-a")
        assert SECRET not in str(err.value)
    finally:
        job.close()
    conn.close()


def test_research_reaches_the_model_only_for_an_admitted_owner(tmp_path):
    admitted = ScriptedProvider([response([text_block("fixture stage")]) for _ in range(8)])
    app = create_application(
        settings=Settings(home=tmp_path / "admitted", api_key="offline", gmail=False, graph_workflows=False),
        llm_provider=admitted,
    )
    result = app.run_research_workflow("Prepare the fixture brief")
    assert admitted.requests
    assert result.stages["email"].reply == "fixture stage"
    assert isinstance(app.agent_runtime, DefaultAgentRuntime)
    app.close()

    denied = ScriptedProvider([response([text_block("should-not-run")])])
    blocked = create_application(
        settings=Settings(home=tmp_path / "denied", api_key="offline", gmail=False, graph_workflows=False),
        llm_provider=denied,
    )
    with pytest.raises(WorkflowExecutionError) as err:
        blocked.agent_orchestrator.run(ResearchWorkflowRequest(prompt="Prepare the fixture brief"))
    assert err.value.stage == "email"
    assert isinstance(err.value.cause, AgentRequestRejected)
    assert denied.requests == []
    blocked.close()
