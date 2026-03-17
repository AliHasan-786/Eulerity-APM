# HyperLocal Agentic Ad Studio

Dependency-light Python prototype for the PRD you provided. It now includes a browser-based portfolio demo so recruiters and hiring managers can interact with the multi-agent workflow directly.

It implements the core Eulerity flow:

- `Localizer` gathers zip-level context through Serper when `SERPER_API_KEY` is present, otherwise it falls back to deterministic mock context for demo reliability.
- `Copywriter` fuses the national ad objective with local context, using an OpenAI-compatible chat endpoint when credentials are configured and a deterministic template mode otherwise.
- `Critic` scores each draft across five categories and routes failed drafts back for rewrite until they pass or exhaust the retry budget.
- `SupervisorWorkflow` runs the loop internally today and can switch to a real LangGraph graph by setting `HYPERLOCAL_WORKFLOW_RUNTIME=langgraph` after installing the optional dependency.
- Every run writes a JSON trace file to `artifacts/traces/` for auditability.
- `webapp.py` serves a local browser experience with live runtime badges, OKR scorecards, localized variant cards, and click-to-open traces.

## Repo Layout

- `src/hyperlocal_ad_studio/workflow.py`: Supervisor, retry loop, optional LangGraph adapter.
- `src/hyperlocal_ad_studio/service.py`: Batch orchestration, concurrency control, timeout handling.
- `src/hyperlocal_ad_studio/webapp.py`: Local HTTP server for browser testing.
- `src/hyperlocal_ad_studio/web/`: Portfolio UI assets.
- `src/hyperlocal_ad_studio/local_context.py`: Serper-backed localizer plus deterministic demo fallback.
- `src/hyperlocal_ad_studio/llm.py`: Copywriter and OpenAI-compatible LLM gateway.
- `src/hyperlocal_ad_studio/critic.py`: LLM or heuristic brand-safety evaluator.
- `src/hyperlocal_ad_studio/api.py`: Optional FastAPI surface for `/generate-variants`.
- `src/hyperlocal_ad_studio/cli.py`: Zero-dependency CLI entrypoint.

## Browser Demo

Run the local portfolio app:

```bash
PYTHONPATH=src python3 -m hyperlocal_ad_studio.webapp --host 127.0.0.1 --port 8000
```

Then open [http://127.0.0.1:8000](http://127.0.0.1:8000) in your browser.

The page exposes:

- Live status badges for LLM mode, local context mode, workflow runtime, and retry budget.
- A form that takes one national ad objective and multiple zip codes.
- Batch summary cards and an OKR board tied to the PRD's throughput, quality, and reliability goals.
- Clickable trace modals that show the localizer, copywriter, and critic steps for each generated variant.

## What I Need From You For Live AI

If you want recruiters to see the real LLM path instead of the deterministic fallback, add these values to `.env` in the repo root:

```bash
HYPERLOCAL_LLM_PROVIDER=openrouter
HYPERLOCAL_CRITIC_MODE=auto
OPENROUTER_API_KEY=your_key_here
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=openai/gpt-4.1-mini
```

If the OpenRouter key has no paid credits, use the zero-cost router instead:

```bash
OPENAI_MODEL=openrouter/free
```

The free router is slower, so raise the per-variant timeout for a smoother demo:

```bash
HYPERLOCAL_VARIANT_TIMEOUT_SECONDS=25
```

In `auto` mode, the app uses live LLM copywriting and switches the critic to the deterministic brand gate when `OPENAI_MODEL=openrouter/free`. If you move back to a paid model, the LLM judge is used again automatically.

For the free route, keep parallelism low to avoid hosted rate limits during recruiter demos:

```bash
HYPERLOCAL_MAX_PARALLELISM=1
```

For live hyper-local context instead of seeded mock context:

```bash
SERPER_API_KEY=your_key_here
```

Optional:

- `OPENAI_API_KEY` if you want to use the default OpenAI endpoint instead of OpenRouter.
- `OPENAI_BASE_URL` if you want to point at a different OpenAI-compatible endpoint.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` if you want to extend the prototype with hosted observability next.

## CLI

You can still run it without the browser:

Use the CLI without installing any dependencies:

```bash
PYTHONPATH=src python3 -m hyperlocal_ad_studio.cli \
  --prompt "Promote our new iced latte" \
  --zip 10001 \
  --zip 94103 \
  --zip 60611
```

Or use the bundled request example:

```bash
PYTHONPATH=src python3 -m hyperlocal_ad_studio.cli --request-file examples/sample_request.json
```

## Optional Packages

If you want the real LangGraph runtime or an HTTP API, install the optional groups:

```bash
python3 -m pip install -e '.[dev,api,langgraph,integrations]'
```

Then start the API with:

```bash
PYTHONPATH=src python3 -c "from hyperlocal_ad_studio.api import create_app; app = create_app(); print(app)"
```

Use `uvicorn` if installed:

```bash
uvicorn hyperlocal_ad_studio.api:create_app --factory --reload
```

## Environment

Copy `.env.example` into your preferred env loader and set:

- `SERPER_API_KEY` to enable live local context lookups.
- `OPENROUTER_API_KEY` plus `OPENAI_BASE_URL` / `OPENAI_MODEL`, or `OPENAI_API_KEY`, to enable live LLM drafting and judging.
- `HYPERLOCAL_WORKFLOW_RUNTIME=langgraph` to activate the graph workflow once `langgraph` is installed.
- `HYPERLOCAL_VARIANT_TIMEOUT_SECONDS` and `HYPERLOCAL_MAX_PARALLELISM` to tune batch throughput.

## Notes

- The trace files are the primary observability surface in this prototype. They are structured so Langfuse ingestion can be layered in cleanly once credentials and SDK dependencies are added.
- The mock mode is deliberate. It keeps the demo stable in environments without API keys while preserving the same orchestration path and output shape.
- For recruiter demos, the best path is to provide `OPENAI_API_KEY` and `SERPER_API_KEY`, restart the local server, and then use the runtime badges in the UI to prove the app is operating live.
