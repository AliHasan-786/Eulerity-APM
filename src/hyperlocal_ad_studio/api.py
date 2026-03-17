from __future__ import annotations

from typing import Any

from .models import GenerationRequest
from .service import HyperLocalAdStudio

try:
    from fastapi import FastAPI, HTTPException
except ModuleNotFoundError:  # pragma: no cover
    FastAPI = None
    HTTPException = RuntimeError


def create_app() -> Any:
    if FastAPI is None:
        raise RuntimeError("FastAPI is not installed. Install the optional 'api' dependencies first.")

    app = FastAPI(title="HyperLocal Agentic Ad Studio", version="0.1.0")
    studio = HyperLocalAdStudio()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/generate-variants")
    async def generate_variants(payload: dict[str, Any]) -> dict[str, Any]:
        try:
            generation_request = GenerationRequest(
                corporate_prompt=str(payload["corporate_prompt"]).strip(),
                zip_codes=[str(zip_code) for zip_code in payload["zip_codes"]],
                brand_guardrails=str(payload.get("brand_guardrails", "")).strip(),
                target_variants=int(payload.get("target_variants", 50)),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        result = await studio.generate_batch(generation_request)
        return result.to_dict()

    return app
