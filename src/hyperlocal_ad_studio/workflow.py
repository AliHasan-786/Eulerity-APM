from __future__ import annotations

import time
from typing import Any, TypedDict

from .config import Settings
from .critic import Critic
from .llm import Copywriter
from .local_context import Localizer
from .models import AdVariant, Critique, DraftCopy, LocalContext
from .tracing import TraceRecorder

try:
    from langgraph.graph import END, StateGraph
except ModuleNotFoundError:  # pragma: no cover
    END = "__end__"
    StateGraph = None


class WorkflowState(TypedDict, total=False):
    request_id: str
    zip_code: str
    corporate_prompt: str
    brand_guardrails: str
    attempts: int
    feedback: str
    context: LocalContext
    draft: DraftCopy
    critique: Critique
    tracer: object


class SupervisorWorkflow:
    def __init__(
        self,
        *,
        settings: Settings,
        localizer: Localizer,
        copywriter: Copywriter,
        critic: Critic,
    ) -> None:
        self._settings = settings
        self._localizer = localizer
        self._copywriter = copywriter
        self._critic = critic
        self._langgraph_app = self._build_langgraph_app() if self._use_langgraph() else None

    def _use_langgraph(self) -> bool:
        return self._settings.workflow_runtime == "langgraph" and StateGraph is not None

    async def run(
        self,
        *,
        request_id: str,
        zip_code: str,
        corporate_prompt: str,
        brand_guardrails: str,
    ) -> AdVariant:
        tracer = TraceRecorder(self._settings.trace_dir, request_id=request_id, zip_code=zip_code)
        started = time.perf_counter()
        tracer.record(
            "input",
            {
                "request_id": request_id,
                "zip_code": zip_code,
                "corporate_prompt": corporate_prompt,
                "brand_guardrails": brand_guardrails,
                "runtime": self._settings.workflow_runtime,
            },
        )
        try:
            if self._langgraph_app is not None:
                final_state = await self._langgraph_app.ainvoke(
                    {
                        "request_id": request_id,
                        "zip_code": zip_code,
                        "corporate_prompt": corporate_prompt,
                        "brand_guardrails": brand_guardrails,
                        "attempts": 0,
                        "feedback": "",
                        "tracer": tracer,
                    }
                )
                variant = self._variant_from_state(final_state, started)
            else:
                variant = await self._run_internal(
                    request_id=request_id,
                    zip_code=zip_code,
                    corporate_prompt=corporate_prompt,
                    brand_guardrails=brand_guardrails,
                    tracer=tracer,
                    started=started,
                )
        except Exception as exc:
            variant = AdVariant(
                request_id=request_id,
                zip_code=zip_code,
                status="error",
                attempts=0,
                latency_ms=int((time.perf_counter() - started) * 1000),
                trace_id=tracer.trace_id,
                error=str(exc),
            )
            tracer.record("error", {"message": str(exc)})
        variant.trace_events = tracer.events_as_list()
        variant.trace_path = tracer.flush()
        return variant

    async def _run_internal(
        self,
        *,
        request_id: str,
        zip_code: str,
        corporate_prompt: str,
        brand_guardrails: str,
        tracer: TraceRecorder,
        started: float,
    ) -> AdVariant:
        context = await self._localizer.gather(zip_code)
        tracer.record("localizer", {"context": context.summary(), "sources": context.sources})
        feedback = ""
        attempts = 0
        draft: DraftCopy | None = None
        critique: Critique | None = None
        while attempts < self._settings.max_rewrites + 1:
            attempts += 1
            draft = await self._copywriter.draft(
                corporate_prompt=corporate_prompt,
                context=context,
                brand_guardrails=brand_guardrails,
                feedback=feedback,
                attempt=attempts,
            )
            tracer.record("copywriter", {"attempt": attempts, "draft": draft.full_text})
            critique = await self._critic.evaluate(
                corporate_prompt=corporate_prompt,
                context=context,
                draft=draft,
            )
            tracer.record(
                "critic",
                {
                    "attempt": attempts,
                    "passed": critique.passed,
                    "scores": critique.scores,
                    "feedback": critique.feedback,
                },
            )
            if critique.passed:
                break
            feedback = critique.feedback

        status = "passed" if critique and critique.passed else "failed"
        return AdVariant(
            request_id=request_id,
            zip_code=zip_code,
            status=status,
            attempts=attempts,
            latency_ms=int((time.perf_counter() - started) * 1000),
            context=context,
            draft=draft,
            critique=critique,
            trace_id=tracer.trace_id,
        )

    def _variant_from_state(self, state: dict[str, Any], started: float) -> AdVariant:
        critique: Critique | None = state.get("critique")
        return AdVariant(
            request_id=str(state["request_id"]),
            zip_code=str(state["zip_code"]),
            status="passed" if critique and critique.passed else "failed",
            attempts=int(state.get("attempts", 0)),
            latency_ms=int((time.perf_counter() - started) * 1000),
            context=state.get("context"),
            draft=state.get("draft"),
            critique=critique,
            trace_id=f"{state['request_id']}:{state['zip_code']}",
        )

    def _build_langgraph_app(self) -> Any:
        if StateGraph is None:
            return None

        async def localize_node(state: dict[str, Any]) -> dict[str, Any]:
            tracer: TraceRecorder = state["tracer"]
            context = await self._localizer.gather(str(state["zip_code"]))
            tracer.record("localizer", {"context": context.summary(), "sources": context.sources})
            return {"context": context}

        async def draft_node(state: dict[str, Any]) -> dict[str, Any]:
            tracer: TraceRecorder = state["tracer"]
            attempts = int(state.get("attempts", 0)) + 1
            draft = await self._copywriter.draft(
                corporate_prompt=str(state["corporate_prompt"]),
                context=state["context"],
                brand_guardrails=str(state.get("brand_guardrails", "")),
                feedback=str(state.get("feedback", "")),
                attempt=attempts,
            )
            tracer.record("copywriter", {"attempt": attempts, "draft": draft.full_text})
            return {"draft": draft, "attempts": attempts}

        async def critic_node(state: dict[str, Any]) -> dict[str, Any]:
            tracer: TraceRecorder = state["tracer"]
            critique = await self._critic.evaluate(
                corporate_prompt=str(state["corporate_prompt"]),
                context=state["context"],
                draft=state["draft"],
            )
            tracer.record(
                "critic",
                {
                    "attempt": state["attempts"],
                    "passed": critique.passed,
                    "scores": critique.scores,
                    "feedback": critique.feedback,
                },
            )
            return {"critique": critique, "feedback": critique.feedback}

        def route_after_critic(state: dict[str, Any]) -> str:
            critique: Critique = state["critique"]
            if critique.passed or int(state["attempts"]) >= self._settings.max_rewrites + 1:
                return "finalize"
            return "draft"

        graph = StateGraph(WorkflowState)
        graph.add_node("localize", localize_node)
        graph.add_node("draft", draft_node)
        graph.add_node("critic", critic_node)
        graph.add_node("finalize", lambda state: state)
        graph.set_entry_point("localize")
        graph.add_edge("localize", "draft")
        graph.add_edge("draft", "critic")
        graph.add_conditional_edges(
            "critic",
            route_after_critic,
            {
                "draft": "draft",
                "finalize": "finalize",
            },
        )
        graph.add_edge("finalize", END)
        return graph.compile()
