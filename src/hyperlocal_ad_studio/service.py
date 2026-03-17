from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import time
import uuid

from .config import Settings, load_settings
from .critic import Critic
from .llm import Copywriter, LLMGateway
from .local_context import Localizer
from .models import AdVariant, BatchResult, GenerationRequest
from .tracing import load_trace
from .workflow import SupervisorWorkflow


class HyperLocalAdStudio:
    def __init__(
        self,
        settings: Settings | None = None,
        workflow: SupervisorWorkflow | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._workflow = workflow or self._build_default_workflow(self._settings)

    def _build_default_workflow(self, settings: Settings) -> SupervisorWorkflow:
        gateway = LLMGateway(settings)
        return SupervisorWorkflow(
            settings=settings,
            localizer=Localizer(settings),
            copywriter=Copywriter(settings, gateway),
            critic=Critic(settings, gateway),
        )

    async def generate_batch(self, generation_request: GenerationRequest) -> BatchResult:
        zip_codes = self._normalize_zip_codes(generation_request)
        request_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        semaphore = asyncio.Semaphore(self._settings.max_parallelism)

        async def run_variant(zip_code: str) -> AdVariant:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        self._workflow.run(
                            request_id=request_id,
                            zip_code=zip_code,
                            corporate_prompt=generation_request.corporate_prompt,
                            brand_guardrails=generation_request.brand_guardrails,
                        ),
                        timeout=self._settings.variant_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    return AdVariant(
                        request_id=request_id,
                        zip_code=zip_code,
                        status="timeout",
                        attempts=0,
                        latency_ms=int(self._settings.variant_timeout_seconds * 1000),
                        trace_id=f"{request_id}:{zip_code}",
                        error="Variant generation exceeded the configured time budget.",
                    )

        variants = await asyncio.gather(*[run_variant(zip_code) for zip_code in zip_codes])
        successful_variants = sum(1 for variant in variants if variant.status == "passed")
        duration_ms = int((time.perf_counter() - started) * 1000)
        pass_rate = (successful_variants / len(variants)) if variants else 0.0
        return BatchResult(
            request_id=request_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            duration_ms=duration_ms,
            requested_variants=len(zip_codes),
            successful_variants=successful_variants,
            pass_rate=round(pass_rate, 4),
            variants=variants,
        )

    def _normalize_zip_codes(self, generation_request: GenerationRequest) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for zip_code in generation_request.zip_codes:
            candidate = str(zip_code).strip()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
            if len(normalized) >= generation_request.target_variants:
                break
        if not normalized:
            raise ValueError("At least one zip code is required to generate localized variants.")
        return normalized

    def runtime_status(self) -> dict[str, object]:
        llm_live = self._settings.llm_provider != "mock" and bool(self._settings.openai_api_key)
        serper_live = bool(self._settings.serper_api_key)
        return {
            "llm": {
                "provider": self._settings.llm_provider,
                "active": llm_live,
                "model": self._settings.openai_model if llm_live else None,
                "missing": [] if llm_live else ["OPENAI_API_KEY or OPENROUTER_API_KEY"],
                "base_url": self._settings.openai_base_url,
            },
            "localizer": {
                "provider": "serper" if serper_live else "mock",
                "active": serper_live,
                "missing": [] if serper_live else ["SERPER_API_KEY"],
            },
            "workflow": {
                "runtime": self._settings.workflow_runtime,
                "critic_mode": self._settings.critic_mode,
                "max_rewrites": self._settings.max_rewrites,
                "max_parallelism": self._settings.max_parallelism,
                "variant_timeout_seconds": self._settings.variant_timeout_seconds,
            },
            "langfuse": {
                "active": self._settings.enable_langfuse,
                "missing": [] if self._settings.enable_langfuse else ["HYPERLOCAL_ENABLE_LANGFUSE"],
            },
        }

    def load_trace_events(self, request_id: str, zip_code: str) -> list[dict[str, object]]:
        return load_trace(self._settings.trace_dir, request_id=request_id, zip_code=zip_code)
