"""Default provider-neutral AgentRuntime implementation."""

from __future__ import annotations

from dataclasses import replace

from pu.core.interfaces.agents import AgentResult, AgentRunRequest, AgentRuntime
from pu.core.interfaces.llm import LLMProvider
from pu.core.interfaces.tools import ToolHarness
from pu.identity.contract import admit_call, tool_context_from_request
from pu.loop.agent import run_loop


class DefaultAgentRuntime(AgentRuntime):
    """Run the shared provider-neutral loop through an injected ToolHarness."""

    def __init__(self, provider: LLMProvider, tool_harness: ToolHarness):
        self.provider = provider
        self.tool_harness = tool_harness

    def run(self, request: AgentRunRequest, observer=None) -> AgentResult:
        context = request.tool_context
        contract = admit_call(contract=request.contract, context=context)
        if context is None or not context.principal:
            context = tool_context_from_request(
                contract,
                observer=observer,
                actor="agent",
                agent_id="pu-agent",
                scopes=request.tools.scopes(),
                capabilities=request.tools.agent_capabilities(),
            )
        elif context.observer is None:
            context = replace(context, observer=observer)
        return run_loop(
            provider=self.provider,
            model=request.model,
            system=request.system,
            messages=request.messages,
            tools=request.tools,
            tool_harness=self.tool_harness,
            max_iterations=request.max_iterations,
            max_tokens=request.max_tokens,
            observer=observer,
            stream=request.stream,
            tool_context=context,
        )
