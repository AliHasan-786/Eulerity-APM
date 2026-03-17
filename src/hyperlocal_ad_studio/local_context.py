from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any
from urllib import request

from .config import Settings
from .models import LocalContext
from .utils import compact_text


# (location_name, market_tier, demographics, competition)
_KNOWN_LOCATIONS: dict[str, tuple[str, str, str, str]] = {
    "10001": (
        "Chelsea, New York, NY",
        "Urban Core",
        "Affluent young professionals and creative-industry workers",
        "High — multiple national chains within 0.3 miles",
    ),
    "10004": (
        "Financial District, New York, NY",
        "Business Hub",
        "Finance and legal professionals with strong weekday purchasing power",
        "Moderate — category leaders compete on convenience",
    ),
    "10036": (
        "Midtown West, New York, NY",
        "Business Hub",
        "Office workers, commuters, and hotel guests with high daily foot traffic",
        "Very high — dense midtown corridor with premium brand concentration",
    ),
    "10044": (
        "Roosevelt Island, New York, NY",
        "Residential Enclave",
        "Mixed-income urban residents in an underserved retail market",
        "Low — limited nearby competition with strong local capture potential",
    ),
    "11201": (
        "Downtown Brooklyn, NY",
        "Urban Core",
        "Young professionals and diverse urban households with growing incomes",
        "High — dense retail corridor with mix of national and independent brands",
    ),
    "19103": (
        "Rittenhouse Square, Philadelphia, PA",
        "Residential Upscale",
        "High-income residents with strong premium brand preference",
        "Moderate — established local favorites alongside select nationals",
    ),
    "02108": (
        "Beacon Hill, Boston, MA",
        "Residential Upscale",
        "Affluent long-term residents and professionals with high brand loyalty",
        "Low-to-moderate — selective, brand-loyal consumer base",
    ),
    "60611": (
        "Streeterville, Chicago, IL",
        "Urban Core",
        "Tourists, affluent shoppers, and professional residents",
        "High — flagship retail corridor with premium brand density",
    ),
    "73301": (
        "Downtown Austin, TX",
        "Urban Growth",
        "Young tech professionals and creative workers with rising incomes",
        "High and growing — new entrants accelerating competitive pressure",
    ),
    "77002": (
        "Downtown Houston, TX",
        "Business Hub",
        "Business travelers and office-district workers on weekday schedules",
        "Moderate — category concentration driven by weekday demand",
    ),
    "80202": (
        "LoDo, Denver, CO",
        "Urban Growth",
        "Young active professionals with brand-forward spending habits",
        "Growing — competitive but not yet saturated",
    ),
    "90012": (
        "Downtown Los Angeles, CA",
        "Urban Core",
        "Diverse urban residents, commuters, and business district workers",
        "High — multi-brand competitive corridor",
    ),
    "94103": (
        "SoMa, San Francisco, CA",
        "Urban Core",
        "Tech workers and design professionals with high disposable income",
        "High — affluent but brand-selective consumer base",
    ),
    "33139": (
        "South Beach, Miami, FL",
        "Tourist & Leisure",
        "High-income tourists, locals, and seasonal residents",
        "High — premium brand concentration in a tourist-heavy market",
    ),
    "78641": (
        "Leander, TX",
        "Suburban Growth",
        "Young suburban families with growing households and dual incomes",
        "Low-to-moderate — emerging suburban market with high capture potential",
    ),
    "94087": (
        "Sunnyvale, CA",
        "Suburban Tech",
        "Tech industry professionals with high household income",
        "Moderate — suburban retail serving commuter demand",
    ),
    "95112": (
        "Downtown San Jose, CA",
        "Urban Growth",
        "Tech professionals and young urban residents",
        "Moderate — growing urban core with increasing brand presence",
    ),
}

_TIER_OPTIONS = [
    "Urban Core",
    "Suburban Growth",
    "Business Hub",
    "Residential Upscale",
    "Urban Growth",
    "Suburban Tech",
]

_DEMOGRAPHICS_OPTIONS = [
    "Young professionals with mid-to-high household income",
    "Suburban families with strong brand loyalty and high purchase frequency",
    "Business professionals seeking convenience-led experiences",
    "Affluent residents with premium category preference",
    "Dual-income households with high discretionary spending capacity",
    "Tech-adjacent workers with brand-forward spending habits",
]

_COMPETITION_OPTIONS = [
    "High — multiple national brands competing in this corridor",
    "Moderate — 1–2 established competitors in category",
    "Low — underserved market with strong capture potential",
    "Moderate-to-high — mix of local favorites and national chains",
    "Growing — new entrants increasing competitive pressure",
    "Low-to-moderate — selective consumer base with high brand loyalty",
]


class Localizer:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def gather(self, zip_code: str) -> LocalContext:
        if self._settings.serper_api_key:
            try:
                return await self._gather_from_serper(zip_code)
            except Exception:
                return self._build_mock_context(zip_code)
        return self._build_mock_context(zip_code)

    async def _gather_from_serper(self, zip_code: str) -> LocalContext:
        queries = {
            "market": f"neighborhood demographics income profile {zip_code}",
            "competition": f"retail businesses brands {zip_code} area",
            "context": f"zip code {zip_code} neighborhood overview",
        }
        results = await asyncio.gather(
            *[asyncio.to_thread(self._serper_search, query) for query in queries.values()]
        )
        known = _KNOWN_LOCATIONS.get(zip_code)
        location_name = self._extract_location_name(results) or (known[0] if known else f"ZIP {zip_code}")
        market_tier = known[1] if known else _TIER_OPTIONS[int(hashlib.sha256(zip_code.encode()).hexdigest(), 16) % len(_TIER_OPTIONS)]
        demographics = self._extract_summary(results[0], fallback="mixed demographics with moderate-to-high consumer spending")
        competition = self._extract_summary(results[1], fallback="moderate competition with a mix of local and national brands")
        sources = []
        for payload in results:
            sources.extend(self._extract_links(payload))
        return LocalContext(
            zip_code=zip_code,
            location_name=location_name,
            market_tier=market_tier,
            demographics=demographics,
            competition=competition,
            sources=sources[:6],
        )

    def _serper_search(self, query: str) -> dict[str, Any]:
        payload = json.dumps({"q": query, "gl": "us", "hl": "en"}).encode("utf-8")
        req = request.Request(
            url="https://google.serper.dev/search",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "X-API-KEY": self._settings.serper_api_key or "",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self._settings.context_request_timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    def _extract_summary(self, payload: dict[str, Any], fallback: str) -> str:
        answer_box = payload.get("answerBox") or {}
        answer_value = answer_box.get("answer") or answer_box.get("snippet")
        if answer_value:
            return compact_text(str(answer_value), self._settings.max_context_chars // 3)
        organic = payload.get("organic") or []
        if organic:
            top_result = organic[0]
            combined = " ".join(
                part for part in [top_result.get("title"), top_result.get("snippet")] if part
            )
            return compact_text(combined, self._settings.max_context_chars // 3)
        return fallback

    def _extract_location_name(self, payloads: list[dict[str, Any]]) -> str | None:
        for payload in payloads:
            knowledge_graph = payload.get("knowledgeGraph") or {}
            title = knowledge_graph.get("title")
            if title:
                return compact_text(str(title), 64)
        return None

    def _extract_links(self, payload: dict[str, Any]) -> list[str]:
        links: list[str] = []
        for item in payload.get("organic") or []:
            link = item.get("link")
            if link:
                links.append(str(link))
        return links

    def _build_mock_context(self, zip_code: str) -> LocalContext:
        known = _KNOWN_LOCATIONS.get(zip_code)
        if known:
            location_name, market_tier, demographics, competition = known
        else:
            seed = int(hashlib.sha256(zip_code.encode("utf-8")).hexdigest(), 16)
            location_name = f"ZIP {zip_code}"
            market_tier = _TIER_OPTIONS[seed % len(_TIER_OPTIONS)]
            demographics = _DEMOGRAPHICS_OPTIONS[(seed // 7) % len(_DEMOGRAPHICS_OPTIONS)]
            competition = _COMPETITION_OPTIONS[(seed // 13) % len(_COMPETITION_OPTIONS)]
        return LocalContext(
            zip_code=zip_code,
            location_name=location_name,
            market_tier=market_tier,
            demographics=demographics,
            competition=competition,
            sources=["mock://market", "mock://competition", "mock://context"],
        )
