from __future__ import annotations

import asyncio
import json
from typing import Any
from urllib import error
from urllib import request

from .config import Settings
from .models import DraftCopy, LocalContext
from .utils import compact_text, significant_terms


class _RateLimitRetry(Exception):
    """Raised inside the sync LLM call to signal an async retry with backoff."""

    def __init__(self, wait_seconds: float, next_attempt: int) -> None:
        self.wait_seconds = wait_seconds
        self.next_attempt = next_attempt


class LLMGateway:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return self._settings.llm_provider != "mock" and bool(self._settings.openai_api_key)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
    ) -> dict[str, Any]:
        attempt = 1
        while True:
            try:
                return await asyncio.to_thread(
                    self._complete_json_sync,
                    system_prompt,
                    user_prompt,
                    temperature,
                    attempt,
                )
            except _RateLimitRetry as exc:
                await asyncio.sleep(exc.wait_seconds)
                attempt = exc.next_attempt

    def _complete_json_sync(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        attempt: int = 1,
    ) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._settings.openai_api_key}",
        }
        if "openrouter.ai" in self._settings.openai_base_url:
            if self._settings.app_url:
                headers["HTTP-Referer"] = self._settings.app_url
            headers["X-Title"] = self._settings.app_name
        body = self._request_completion(
            headers=headers,
            model=self._settings.openai_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            attempt=attempt,
        )
        content = body["choices"][0]["message"]["content"]
        return json.loads(content)

    def _request_completion(
        self,
        *,
        headers: dict[str, str],
        model: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        attempt: int = 1,
    ) -> dict[str, Any]:
        payload = json.dumps(
            {
                "model": model,
                "temperature": temperature,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        req = request.Request(
            url=f"{self._settings.openai_base_url}/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._settings.llm_request_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if (
                exc.code == 402
                and "openrouter.ai" in self._settings.openai_base_url
                and model != "openrouter/free"
            ):
                return self._request_completion(
                    headers=headers,
                    model="openrouter/free",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                )
            is_free_model = model == "openrouter/free" or model.endswith(":free")
            if exc.code == 429 and attempt < 3 and not is_free_model:
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                wait_seconds = float(retry_after) if retry_after and retry_after.isdigit() else float(attempt * 2)
                raise _RateLimitRetry(wait_seconds=wait_seconds, next_attempt=attempt + 1)
            try:
                error_body = exc.read().decode("utf-8", errors="ignore").strip()
            except Exception:
                error_body = ""
            message = error_body or exc.reason or f"HTTP Error {exc.code}"
            raise RuntimeError(f"HTTP Error {exc.code}: {message}") from exc


class Copywriter:
    def __init__(self, settings: Settings, gateway: LLMGateway) -> None:
        self._settings = settings
        self._gateway = gateway

    async def draft(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        brand_guardrails: str,
        feedback: str,
        attempt: int,
    ) -> DraftCopy:
        if self._gateway.enabled and self._should_use_live_llm(attempt):
            try:
                return await self._draft_with_llm(
                    corporate_prompt=corporate_prompt,
                    context=context,
                    brand_guardrails=brand_guardrails,
                    feedback=feedback,
                    attempt=attempt,
                )
            except Exception:
                return self._draft_with_template(
                    corporate_prompt=corporate_prompt,
                    context=context,
                    feedback=feedback,
                    attempt=attempt,
                )
        return self._draft_with_template(
            corporate_prompt=corporate_prompt,
            context=context,
            feedback=feedback,
            attempt=attempt,
        )

    def _should_use_live_llm(self, attempt: int) -> bool:
        if not self._gateway.enabled:
            return False
        if self._settings.openai_model == "openrouter/free" and attempt > 1:
            return False
        return True

    async def _draft_with_llm(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        brand_guardrails: str,
        feedback: str,
        attempt: int,
    ) -> DraftCopy:
        system_prompt = (
            "You are Eulerity's hyper-local ad copywriter. Keep the national offer intact, "
            "make the copy feel specific to the neighborhood today, and never emit placeholders, "
            "brackets, or TODO text. Return JSON with headline, body, and cta."
        )
        user_prompt = "\n".join(
            [
                f"Corporate ad objective: {compact_text(corporate_prompt, self._settings.max_context_chars)}",
                f"Brand guardrails: {brand_guardrails or 'Stay brand-safe, concise, and conversion-oriented.'}",
                f"Location context: {compact_text(context.summary(), self._settings.max_context_chars)}",
                f"Rewrite attempt: {attempt}",
                f"Critic feedback: {feedback or 'None. Produce the strongest first draft.'}",
            ]
        )
        payload = await self._gateway.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.5,
        )
        return DraftCopy(
            headline=str(payload.get("headline", "")).strip(),
            body=str(payload.get("body", "")).strip(),
            cta=str(payload.get("cta", "")).strip(),
        )

    def _draft_with_template(
        self,
        *,
        corporate_prompt: str,
        context: LocalContext,
        feedback: str,
        attempt: int,
    ) -> DraftCopy:
        # Extract the product/offer phrase preferring text after "for" connector
        # e.g. "Drive enrollments for our Smooth Skin Guarantee" → "Smooth Skin Guarantee"
        _for_idx = corporate_prompt.lower().find(" for ")
        if _for_idx != -1:
            product_text = corporate_prompt[_for_idx + 5:]
            for _prefix in ("our ", "the "):
                if product_text.lower().startswith(_prefix):
                    product_text = product_text[len(_prefix):]
        else:
            product_text = corporate_prompt
        topic_terms = significant_terms(product_text)
        _verbs = {"promote", "launch", "highlight", "introduce", "drive", "increase", "boost", "maximize", "grow"}
        filtered_topic_terms = [term for term in topic_terms if term.lower() not in _verbs]
        lead_topic = " ".join(filtered_topic_terms[:3] or topic_terms[:3]) or "our offer"

        # Short neighborhood name for punchy copy (e.g. "South Beach" from "South Beach, Miami, FL")
        short_loc = context.location_name.split(",")[0].strip()
        demo = context.demographics.lower()
        tier = context.market_tier.lower()

        headline = f"{lead_topic.title()} — {short_loc}"

        # Market-tier-specific body that reads like actual advertising, not commentary about advertising
        if "tourist" in tier or "leisure" in tier:
            body = (
                f"Whether you're a regular or just passing through, {short_loc} knows great experiences. "
                f"{lead_topic.title()} is here for {demo} — "
                f"because the best offers shouldn't wait for your home market."
            )
        elif "business" in tier or "hub" in tier:
            body = (
                f"{short_loc} runs on results — and {lead_topic.title()} delivers. "
                f"Built for {demo}, this offer brings national quality "
                f"to where you work. Convenient, reliable, worth it."
            )
        elif "upscale" in tier or "enclave" in tier or "residential" in tier:
            body = (
                f"In {short_loc}, the standard is high — and {lead_topic.title()} meets it. "
                f"Designed for {demo}, this offer delivers what discerning customers expect: "
                f"quality, exclusivity, and lasting value."
            )
        elif "suburban" in tier or "growth" in tier or "tech" in tier:
            body = (
                f"{short_loc} is growing — and smart brands are here early. "
                f"{lead_topic.title()} is the offer {demo} have been waiting for, "
                f"right in their own backyard."
            )
        else:
            # Urban Core and Urban Growth
            body = (
                f"{short_loc} moves fast, and so do your customers. "
                f"{lead_topic.title()} is built for {demo} — "
                f"national-caliber quality, right in the neighborhood. "
                f"No detours, no compromises."
            )

        if feedback and attempt > 1:
            body += f" Refined for {short_loc}'s competitive landscape."

        # Context-aware CTA — check both the extracted product name and the full prompt
        urgency = "today" if attempt == 1 else "now"
        offer_text = (lead_topic + " " + corporate_prompt).lower()
        if any(w in offer_text for w in ("tutoring", "k-12", "learning center", "education")):
            cta = f"Schedule a free session in {short_loc} {urgency}."
        elif any(w in offer_text for w in ("membership", "enroll", "subscribe", "subscription")):
            cta = f"Enroll at your {short_loc} location {urgency}."
        elif any(w in offer_text for w in ("shipping", "print", "mailbox")):
            cta = f"Stop by your {short_loc} location {urgency}."
        else:
            cta = f"Visit {short_loc} {urgency}."

        return DraftCopy(
            headline=compact_text(headline, 72),
            body=compact_text(body, 360),
            cta=compact_text(cta, 140),
        )
