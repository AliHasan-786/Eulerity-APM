from __future__ import annotations

import asyncio

from hyperlocal_ad_studio.config import Settings
from hyperlocal_ad_studio.models import Critique, DraftCopy, GenerationRequest, LocalContext
from hyperlocal_ad_studio.service import HyperLocalAdStudio
from hyperlocal_ad_studio.workflow import SupervisorWorkflow


class StaticLocalizer:
    async def gather(self, zip_code: str) -> LocalContext:
        return LocalContext(
            zip_code=zip_code,
            location_name="Chelsea, New York, NY",
            market_tier="Urban Core",
            demographics="Affluent young professionals and creative-industry workers",
            competition="High — multiple national chains within 0.3 miles",
            sources=["mock://context"],
        )


class SequenceCopywriter:
    def __init__(self) -> None:
        self.calls = 0

    async def draft(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        brand_guardrails: str,
        feedback: str,
        attempt: int,
    ) -> DraftCopy:
        self.calls += 1
        if self.calls == 1:
            return DraftCopy(
                headline="Visit {City}",
                body="A generic message with no local detail.",
                cta="Learn more",
            )
        return DraftCopy(
            headline="Iced Latte — Chelsea, New York, NY",
            body=(
                "Promote our new iced latte in Chelsea, New York. "
                "This urban core market draws affluent young professionals, "
                "making brand relevance and local resonance essential."
            ),
            cta="Visit your Chelsea location today and experience our new iced latte.",
        )


class SequenceCritic:
    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        draft: DraftCopy,
    ) -> Critique:
        self.calls += 1
        if self.calls == 1:
            return Critique(
                passed=False,
                scores={"brand_safety": 1},
                feedback="Remove placeholders and add neighborhood context.",
                rationale=[],
            )
        return Critique(
            passed=True,
            scores={"brand_safety": 5},
            feedback="Passed.",
            rationale=[],
        )


def make_settings(tmp_path) -> Settings:
    return Settings(
        llm_provider="mock",
        critic_mode="auto",
        workflow_runtime="internal",
        max_rewrites=2,
        max_parallelism=4,
        variant_timeout_seconds=5,
        llm_request_timeout_seconds=3,
        context_request_timeout_seconds=3,
        max_context_chars=600,
        trace_dir=tmp_path / "traces",
        serper_api_key=None,
        openai_api_key=None,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4.1-mini",
        app_name="HyperLocal Agentic Ad Studio",
        app_url="http://127.0.0.1:8000",
        enable_langfuse=False,
    )


def test_workflow_retries_until_critic_passes(tmp_path) -> None:
    workflow = SupervisorWorkflow(
        settings=make_settings(tmp_path),
        localizer=StaticLocalizer(),
        copywriter=SequenceCopywriter(),
        critic=SequenceCritic(),
    )

    variant = asyncio.run(
        workflow.run(
            request_id="test-run",
            zip_code="10001",
            corporate_prompt="Promote our new iced latte",
            brand_guardrails="Stay premium and neighborhood-specific.",
        )
    )

    assert variant.status == "passed"
    assert variant.attempts == 2
    assert variant.trace_path is not None


def test_batch_generation_returns_requested_variants(tmp_path) -> None:
    studio = HyperLocalAdStudio(settings=make_settings(tmp_path))
    result = asyncio.run(
        studio.generate_batch(
            GenerationRequest(
                corporate_prompt="Promote our new iced latte",
                zip_codes=["10001", "94103"],
                brand_guardrails="Stay premium and neighborhood-specific.",
                target_variants=2,
            )
        )
    )

    assert result.requested_variants == 2
    assert len(result.variants) == 2
    assert result.pass_rate >= 0
    assert all(variant.status in {"passed", "failed", "timeout", "error"} for variant in result.variants)
    assert all(variant.trace_path for variant in result.variants if variant.status in {"passed", "failed"})
