"""WorkflowEngine adapter backed by PU's deterministic graph engine.

When a run id is present, graph nodes and research stages share one
``workflow_runs`` row and the same ``(workflow_id, owner_user_id)`` checkpoints.
A later run of that id does not insert a second row and does not call a node
whose stage already completed for this owner.
"""

from __future__ import annotations

import json

from pu.core.interfaces.agents import AgentResult
from pu.core.interfaces.orchestration import ResearchWorkflowRequest
from pu.core.interfaces.workflow import WorkflowEngine
from pu.graph.engine import Graph, Node, run_graph


class GraphWorkflowEngine(WorkflowEngine):
    def __init__(self, repository=None):
        self.repository = repository

    def run(self, workflow, state: dict, observer=None, max_steps: int = 25) -> dict:
        workflow_id = str(state.get("_workflow_run_id") or "").strip()
        if self.repository is None or not workflow_id:
            return run_graph(workflow, state, observer=observer, max_steps=max_steps)
        request = state.get("_request")
        if not isinstance(request, ResearchWorkflowRequest):
            request = ResearchWorkflowRequest(prompt=getattr(workflow, "name", "") or "graph")
        self.repository.open_run(workflow_id, request)
        wrapped = Graph(workflow.name)
        for node in workflow.nodes.values():
            wrapped.add_node(
                Node(
                    name=node.name,
                    fn=self._checkpointed(workflow_id, node.fn, node.name),
                    kind=node.kind,
                    max_visits=node.max_visits,
                    on_error=node.on_error,
                )
            )
        for src, dst in workflow.edges:
            wrapped.add_edge(src, dst)
        for src, (route, targets) in workflow.routers.items():
            wrapped.add_router(src, route, targets)
        return run_graph(wrapped, state, observer=observer, max_steps=max_steps)

    def _checkpointed(self, workflow_id: str, fn, stage_name: str):
        def run(state: dict) -> dict:
            cached = self.repository.checkpoints(workflow_id).get(stage_name)
            if cached is not None and cached.status == "completed" and cached.result is not None:
                return _restore(cached.result)
            try:
                out = fn(state) or {}
            except Exception as exc:
                self.repository.checkpoint_failure(workflow_id, stage_name, repr(exc))
                raise
            storable = {
                key: value
                for key, value in out.items()
                if not str(key).startswith("_")
            }
            self.repository.save_checkpoint(
                workflow_id,
                stage_name,
                AgentResult(reply=json.dumps(storable, default=str)),
            )
            return out

        return run


def _restore(result: AgentResult) -> dict:
    try:
        payload = json.loads(result.reply or "")
    except json.JSONDecodeError:
        return {"reply": result.reply}
    if isinstance(payload, dict):
        return payload
    return {"value": payload}
