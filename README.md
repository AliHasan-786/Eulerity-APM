# Franchise Campaign Activation Studio

An AI agent pipeline that takes a single national brand brief and produces market-specific ad copy for every franchise location in the network — localized by zip code, scored against brand guidelines, and automatically rewritten if it doesn't pass.

**[Live demo →](https://eulerity-apm.vercel.app)**

---

## The Problem

Enterprise franchise brands face a structural tension in advertising. A national campaign brief needs to reach hundreds or thousands of locations, but each market is different — demographics, competitive density, and consumer behavior vary dramatically between South Beach and suburban Leander, TX. Generic copy underperforms. Manual localization at scale is prohibitively expensive and slow.

The other side of the problem is brand compliance. When franchise owners write their own ads, quality and legal consistency break down. When a central team reviews each one, it becomes a bottleneck. The question is whether an automated system can write copy that's both locally resonant and brand-compliant — without a human in the loop for either step.

This pipeline explores that question. It's built around the same core loop that powers modern AI marketing automation: gather local market signals, generate location-specific copy, evaluate it against brand guardrails, and iterate until it passes.

---

## How It Works

```
National Brief + Zip Codes
         │
         ▼
┌─────────────────┐
│   Localizer     │  Resolves each zip code to market tier, demographics,
│                 │  and competitive context via Serper (or curated fallback)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│   Copywriter    │  Fuses the national brief with local context using an
│                 │  OpenAI-compatible LLM (or deterministic template mode)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     Critic      │  Scores copy across 5 brand dimensions. Failed drafts
│                 │  are routed back to the Copywriter — up to 2 retry cycles.
└────────┬────────┘
         │
    passed / failed
         │
         ▼
  AdVariant output
  (with full trace)
```

Each location runs through the loop independently and in parallel. The `SupervisorWorkflow` manages the retry budget and writes a structured JSON trace per variant for auditability. Everything runs with zero external dependencies by default — the LLM and context APIs are optional layers on top of a working fallback.

---

## Scoring Dimensions

The Critic evaluates each draft on five dimensions, each scored 1–5:

| Dimension | What it checks |
|---|---|
| `brand_safety` | No placeholders, brackets, or prohibited terms |
| `local_relevance` | Copy references the specific market, demographics, and competitive context |
| `tone_alignment` | Language matches the brand's stated voice and register |
| `core_message_retention` | The national offer is clearly preserved |
| `cta_strength` | A clear, actionable call to action is present |

A draft passes when every dimension scores ≥ 4. Anything below triggers a rewrite with the critic's feedback passed back to the copywriter.

---

## Project Structure

```
src/hyperlocal_ad_studio/
├── workflow.py        # SupervisorWorkflow — retry loop + optional LangGraph adapter
├── service.py         # Batch orchestration, concurrency control, timeout handling
├── local_context.py   # Localizer: Serper API + curated fallback for 17 US markets
├── llm.py             # Copywriter: LLM gateway + template fallback
├── critic.py          # Critic: LLM judge + heuristic brand-safety evaluator
├── models.py          # LocalContext, DraftCopy, Critique, AdVariant, BatchResult
├── tracing.py         # Per-variant JSON trace recorder
├── config.py          # Settings loaded from environment / .env
├── webapp.py          # stdlib HTTP server for local development
├── api.py             # Optional FastAPI surface
└── web/               # Frontend: index.html, styles.css, app.js

api/
└── index.py           # Vercel serverless entry point (FastAPI)

tests/
└── test_workflow.py   # Workflow retry logic + batch generation tests
```

---

## Running Locally

No installation required for the core pipeline:

```bash
git clone https://github.com/AliHasan-786/Eulerity-APM.git
cd Eulerity-APM
PYTHONPATH=src python3 -m hyperlocal_ad_studio.webapp --port 8000
```

Open [http://localhost:8000](http://localhost:8000). The app runs in template mode by default — no API keys needed. Add keys (see below) to enable live LLM copy generation and real market intelligence.

**CLI (no browser):**

```bash
PYTHONPATH=src python3 -m hyperlocal_ad_studio.cli \
  --prompt "Drive enrollment for our unlimited membership program" \
  --zip 10001 --zip 94103 --zip 33139
```

---

## Configuration

Copy `.env.example` to `.env` and set the values you want:

```bash
cp .env.example .env
```

| Variable | Effect |
|---|---|
| `OPENROUTER_API_KEY` | Enables live LLM copy generation via OpenRouter |
| `OPENAI_API_KEY` | Alternative: use the standard OpenAI endpoint |
| `OPENAI_BASE_URL` | Override the API base URL (default: OpenAI or OpenRouter) |
| `OPENAI_MODEL` | Model to use (default: `openai/gpt-4.1-mini`) |
| `SERPER_API_KEY` | Enables live local market intelligence per zip code |
| `HYPERLOCAL_CRITIC_MODE` | `auto` (default), `llm`, or `heuristic` |
| `HYPERLOCAL_MAX_REWRITES` | Max retry cycles per variant (default: `2`) |
| `HYPERLOCAL_MAX_PARALLELISM` | Concurrent variants (default: `8`, lower for free-tier models) |
| `HYPERLOCAL_VARIANT_TIMEOUT_SECONDS` | Per-variant timeout (default: `12`) |
| `HYPERLOCAL_WORKFLOW_RUNTIME` | `internal` (default) or `langgraph` |

**Free-tier OpenRouter note:** Set `OPENAI_MODEL=openrouter/free` and `HYPERLOCAL_MAX_PARALLELISM=1` to stay within rate limits. The critic automatically falls back to heuristic mode on the free model.

---

## Deployment

The app deploys to Vercel with no additional configuration. `vercel.json` routes all traffic through `api/index.py`, which serves both the API endpoints and the static frontend.

```bash
# Install Vercel CLI if needed
npm i -g vercel

vercel deploy
```

Set `OPENROUTER_API_KEY` and `SERPER_API_KEY` as environment variables in the Vercel dashboard to enable the live AI path.

---

## Optional Extensions

**LangGraph runtime:**

```bash
pip install -e '.[langgraph]'
HYPERLOCAL_WORKFLOW_RUNTIME=langgraph python3 -m hyperlocal_ad_studio.webapp
```

Swaps the internal retry loop for a LangGraph state graph. The interface and output shape are identical — the runtime is the only difference.

**Langfuse observability:**

```bash
pip install -e '.[integrations]'
```

Set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST`. Trace events are already structured for Langfuse ingestion — the integration hooks in cleanly on top of the existing trace recorder.

**FastAPI surface:**

```bash
pip install -e '.[api]'
uvicorn hyperlocal_ad_studio.api:create_app --factory --reload
```

Exposes a `POST /generate-variants` endpoint with the same request/response shape as the web UI.

---

## Tests

```bash
PYTHONPATH=src pytest tests/ -v
```
