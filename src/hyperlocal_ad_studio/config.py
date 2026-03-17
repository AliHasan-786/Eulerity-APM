from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

_DOTENV_LOADED = False


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_dotenv(dotenv_path: Path) -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED or not dotenv_path.exists():
        return
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    _DOTENV_LOADED = True


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    critic_mode: str
    workflow_runtime: str
    max_rewrites: int
    max_parallelism: int
    variant_timeout_seconds: float
    llm_request_timeout_seconds: float
    context_request_timeout_seconds: float
    max_context_chars: int
    trace_dir: Path
    serper_api_key: str | None
    openai_api_key: str | None
    openai_base_url: str
    openai_model: str
    app_name: str
    app_url: str | None
    enable_langfuse: bool


def load_settings() -> Settings:
    _load_dotenv(Path.cwd() / ".env")
    # Vercel and serverless platforms: /tmp is the only writable dir; also use
    # tighter defaults so variants finish within Vercel Hobby's 10s hard limit.
    on_serverless = bool(os.getenv("VERCEL") or os.getenv("AWS_LAMBDA_FUNCTION_NAME"))
    if on_serverless:
        base_dir = Path("/tmp") / "hyperlocal_traces"
    else:
        base_dir = Path.cwd() / "artifacts" / "traces"
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    openai_api_key = os.getenv("OPENAI_API_KEY") or openrouter_api_key
    llm_provider = os.getenv("HYPERLOCAL_LLM_PROVIDER")
    if not llm_provider and openrouter_api_key:
        llm_provider = "openrouter"
    return Settings(
        llm_provider=(llm_provider or "mock").strip().lower(),
        critic_mode=os.getenv("HYPERLOCAL_CRITIC_MODE", "auto").strip().lower(),
        workflow_runtime=os.getenv("HYPERLOCAL_WORKFLOW_RUNTIME", "internal").strip().lower(),
        # On Vercel: 1 retry max (2 attempts × 2 LLM calls = 4 total ≈ 40s, fits in 50s budget).
        # Locally: 2 retries (higher quality, no time pressure).
        max_rewrites=max(0, int(os.getenv("HYPERLOCAL_MAX_REWRITES", "1" if on_serverless else "2"))),
        max_parallelism=max(1, int(os.getenv("HYPERLOCAL_MAX_PARALLELISM", "2" if on_serverless else "8"))),
        variant_timeout_seconds=max(
            1.0, float(os.getenv("HYPERLOCAL_VARIANT_TIMEOUT_SECONDS", "60" if on_serverless else "12"))
        ),
        llm_request_timeout_seconds=max(
            1.0, float(os.getenv("HYPERLOCAL_LLM_REQUEST_TIMEOUT_SECONDS", "20" if on_serverless else "6"))
        ),
        context_request_timeout_seconds=max(
            1.0, float(os.getenv("HYPERLOCAL_CONTEXT_REQUEST_TIMEOUT_SECONDS", "8" if on_serverless else "6"))
        ),
        max_context_chars=max(120, int(os.getenv("HYPERLOCAL_MAX_CONTEXT_CHARS", "600"))),
        trace_dir=base_dir,
        serper_api_key=os.getenv("SERPER_API_KEY"),
        openai_api_key=openai_api_key,
        openai_base_url=os.getenv(
            "OPENAI_BASE_URL",
            "https://openrouter.ai/api/v1" if openrouter_api_key else "https://api.openai.com/v1",
        ).rstrip("/"),
        openai_model=os.getenv(
            "OPENAI_MODEL",
            "google/gemini-2.0-flash-exp:free" if openrouter_api_key else "gpt-4.1-mini",
        ),
        app_name=os.getenv("HYPERLOCAL_APP_NAME", "HyperLocal Agentic Ad Studio"),
        app_url=os.getenv("HYPERLOCAL_APP_URL", "http://127.0.0.1:8000").strip() or None,
        enable_langfuse=_as_bool(os.getenv("HYPERLOCAL_ENABLE_LANGFUSE"), default=False),
    )
