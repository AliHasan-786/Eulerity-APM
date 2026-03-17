from __future__ import annotations

from typing import Any

from .config import Settings
from .llm import LLMGateway
from .models import Critique, DraftCopy, LocalContext
from .utils import significant_terms


class Critic:
    def __init__(self, settings: Settings, gateway: LLMGateway) -> None:
        self._settings = settings
        self._gateway = gateway

    async def evaluate(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        draft: DraftCopy,
    ) -> Critique:
        if self._should_use_llm():
            try:
                return await self._evaluate_with_llm(
                    corporate_prompt=corporate_prompt,
                    context=context,
                    draft=draft,
                )
            except Exception:
                return self._evaluate_with_heuristics(
                    corporate_prompt=corporate_prompt,
                    context=context,
                    draft=draft,
                )
        return self._evaluate_with_heuristics(
            corporate_prompt=corporate_prompt,
            context=context,
            draft=draft,
        )

    def _should_use_llm(self) -> bool:
        if not self._gateway.enabled:
            return False
        if self._settings.critic_mode == "heuristic":
            return False
        if self._settings.critic_mode == "llm":
            return True
        return self._settings.openai_model != "openrouter/free"

    async def _evaluate_with_llm(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        draft: DraftCopy,
    ) -> Critique:
        expected_keys = {
            "brand_safety",
            "local_relevance",
            "tone_alignment",
            "core_message_retention",
            "cta_strength",
        }
        payload = await self._gateway.complete_json(
            system_prompt=(
                "You are a brand safety and performance reviewer. Score each category from 1 to 5, "
                "set passed to true only if every category is at least 4, and return JSON with "
                "passed, scores, feedback, and rationale. The scores object must use exactly these keys: "
                "brand_safety, local_relevance, tone_alignment, core_message_retention, cta_strength."
            ),
            user_prompt="\n".join(
                [
                    f"Corporate objective: {corporate_prompt}",
                    f"Location context: {context.summary()}",
                    f"Draft ad: {draft.full_text}",
                ]
            ),
            temperature=0.1,
        )
        scores = {
            key: int(value)
            for key, value in dict(payload.get("scores", {})).items()
            if isinstance(value, (int, float, str))
        }
        if set(scores.keys()) != expected_keys:
            return self._evaluate_with_heuristics(
                corporate_prompt=corporate_prompt,
                context=context,
                draft=draft,
            )
        feedback_raw = payload.get("feedback", "")
        if isinstance(feedback_raw, dict):
            feedback = " ".join(f"{key}: {value}" for key, value in feedback_raw.items())
        else:
            feedback = str(feedback_raw).strip()
        rationale_raw = payload.get("rationale", [])
        if isinstance(rationale_raw, str):
            rationale = [rationale_raw]
        elif isinstance(rationale_raw, list):
            rationale = [str(item) for item in rationale_raw]
        else:
            rationale = [str(rationale_raw)]
        return Critique(
            passed=bool(payload.get("passed", False)),
            scores=scores,
            feedback=feedback,
            rationale=rationale,
        )

    def _evaluate_with_heuristics(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        draft: DraftCopy,
    ) -> Critique:
        full_text = draft.full_text.lower()
        local_tokens = {
            token.lower()
            for token in significant_terms(
                f"{context.location_name} {context.market_tier} {context.demographics} {context.competition}"
            )
        }
        prompt_tokens = {token.lower() for token in significant_terms(corporate_prompt)}
        banned_placeholder_tokens = {"{", "}", "[", "]", "todo"}
        cta_tokens = {
            "stop",
            "visit",
            "order",
            "shop",
            "try",
            "swing",
            "come",
            "start",
            "grab",
            "sip",
            "taste",
            "enjoy",
            "enroll",
            "schedule",
            "book",
            "join",
            "sign",
            "get",
            "claim",
            "unlock",
            "save",
        }

        local_hits = sum(1 for token in local_tokens if token and token in full_text)
        prompt_hits = sum(1 for token in prompt_tokens if token and token in full_text)
        has_promo_tone = any(word in full_text for word in {
            "today", "now", "new", "local", "offer", "feature",
            "quality", "built for", "delivers", "national", "exclusive", "right in",
        })
        has_cta = any(token in draft.cta.lower() for token in cta_tokens)
        has_placeholders = any(token in draft.full_text.lower() for token in banned_placeholder_tokens)

        scores = {
            "brand_safety": 5 if not has_placeholders else 1,
            "local_relevance": 5 if local_hits >= 4 else 4 if local_hits >= 2 else 2,
            "tone_alignment": 5 if has_promo_tone else 3,
            "core_message_retention": 5 if prompt_hits >= 2 else 4 if prompt_hits == 1 else 2,
            "cta_strength": 5 if has_cta else 2,
        }

        deficiencies = [name for name, score in scores.items() if score < 4]
        rationale = [
            f"{name} scored {score}/5 based on heuristic checks."
            for name, score in scores.items()
        ]

        feedback_map = {
            "brand_safety": "Remove placeholders or bracketed text and keep the ad production-ready.",
            "local_relevance": "Anchor the copy more tightly to the neighborhood context and today's signals.",
            "tone_alignment": "Make the copy feel more promotional and conversion-oriented.",
            "core_message_retention": "Reinforce the original national product message more explicitly.",
            "cta_strength": "End with a clearer action for the local customer to take now.",
        }
        feedback = (
            "Passed the brand-safety rubric."
            if not deficiencies
            else " ".join(feedback_map[item] for item in deficiencies)
        )
        return Critique(
            passed=not deficiencies,
            scores=scores,
            feedback=feedback,
            rationale=rationale,
        )
