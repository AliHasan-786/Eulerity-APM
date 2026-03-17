"""
Vercel serverless entry point.
Routes all requests to the FastAPI app, which serves both the API endpoints
and the static web assets.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# Add src/ to path so hyperlocal_ad_studio is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from hyperlocal_ad_studio.models import GenerationRequest
from hyperlocal_ad_studio.service import HyperLocalAdStudio

WEB_ROOT = Path(__file__).parent.parent / "src" / "hyperlocal_ad_studio" / "web"
_ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")
_MAX_TARGET_VARIANTS = 3

app = FastAPI(title="Eulerity Campaign Activation Studio")

# Lazily initialized so Vercel cold starts are fast
_studio: HyperLocalAdStudio | None = None


def _get_studio() -> HyperLocalAdStudio:
    global _studio
    if _studio is None:
        _studio = HyperLocalAdStudio()
    return _studio


def _sample_requests() -> list[dict]:
    return [
        {
            "label": "European Wax Center",
            "corporate_prompt": "Drive membership enrollments for our Smooth Skin Guarantee — unlimited wax services for a flat monthly rate",
            "zip_codes": ["33139", "10001", "90012", "77002"],
            "brand_guardrails": "Tone: confident, empowering, and polished. Avoid clinical language. Stay aspirational and conversion-focused.",
            "target_variants": 3,
        },
        {
            "label": "The UPS Store",
            "corporate_prompt": "Drive in-store traffic for same-day shipping, printing, and mailbox services targeting small businesses and remote workers",
            "zip_codes": ["10036", "94103", "60611", "02108"],
            "brand_guardrails": "Lead with convenience and reliability. Keep copy clear, direct, and action-oriented. Avoid jargon.",
            "target_variants": 3,
        },
        {
            "label": "Sylvan Learning",
            "corporate_prompt": "Drive enrollment for personalized K-12 tutoring programs ahead of the new school year",
            "zip_codes": ["11201", "80202", "78641", "94087"],
            "brand_guardrails": "Speak to parents. Warm, encouraging, and results-focused tone. Emphasize trust, personalization, and measurable outcomes.",
            "target_variants": 3,
        },
        {
            "label": "Single Location",
            "corporate_prompt": "Drive membership enrollments for our Smooth Skin Guarantee — unlimited wax services for a flat monthly rate",
            "zip_codes": ["10044"],
            "brand_guardrails": "Tone: confident, empowering, and polished. Stay aspirational.",
            "target_variants": 1,
        },
    ]


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/status")
async def api_status() -> dict:
    studio = _get_studio()
    return {"runtime": studio.runtime_status(), "samples": _sample_requests()}


@app.post("/api/generate")
async def api_generate(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    try:
        zip_codes_raw = [str(z).strip() for z in payload["zip_codes"]]
        for z in zip_codes_raw:
            if not _ZIP_RE.match(z):
                raise ValueError(f"Invalid zip code: {z!r}. Expected 5-digit US format (e.g. 10001).")
        generation_request = GenerationRequest(
            corporate_prompt=str(payload["corporate_prompt"]).strip(),
            zip_codes=zip_codes_raw,
            brand_guardrails=str(payload.get("brand_guardrails", "")).strip(),
            target_variants=min(_MAX_TARGET_VARIANTS, max(1, int(payload.get("target_variants", 50)))),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    studio = _get_studio()
    result = await studio.generate_batch(generation_request)
    return result.to_dict()


@app.get("/api/trace")
async def api_trace(request_id: str, zip_code: str) -> dict:
    studio = _get_studio()
    try:
        events = studio.load_trace_events(request_id=request_id, zip_code=zip_code)
        return {"request_id": request_id, "zip_code": zip_code, "events": events}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Trace not found.")


# ─── Static File Routes ───────────────────────────────────────────────────────

@app.get("/favicon.svg")
async def favicon() -> Response:
    f = WEB_ROOT / "favicon.svg"
    if f.exists():
        return FileResponse(f, media_type="image/svg+xml")
    raise HTTPException(status_code=404)


@app.get("/styles.css")
async def styles() -> Response:
    return FileResponse(WEB_ROOT / "styles.css", media_type="text/css")


@app.get("/app.js")
async def appjs() -> Response:
    return FileResponse(WEB_ROOT / "app.js", media_type="application/javascript")


@app.get("/")
@app.get("/{path:path}")
async def index(path: str = "") -> Response:
    return FileResponse(WEB_ROOT / "index.html", media_type="text/html")
