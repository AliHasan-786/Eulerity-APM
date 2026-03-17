function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const statusBar = document.getElementById("status-bar");
const runtimeNotes = document.getElementById("runtime-notes");
const presetRow = document.getElementById("preset-row");
const form = document.getElementById("generator-form");
const generateButton = document.getElementById("generate-button");
const resultsSection = document.getElementById("results-section");
const batchSummary = document.getElementById("batch-summary");
const variantGrid = document.getElementById("variant-grid");
const loadingIndicator = document.getElementById("loading-indicator");
const traceModal = document.getElementById("trace-modal");
const traceEvents = document.getElementById("trace-events");
const traceTitle = document.getElementById("trace-title");
const closeTrace = document.getElementById("close-trace");

// Store variants so trace buttons can access inline trace data
let _currentVariants = [];

const fields = {
  corporatePrompt: document.getElementById("corporate-prompt"),
  zipCodes: document.getElementById("zip-codes"),
  brandGuardrails: document.getElementById("brand-guardrails"),
  targetVariants: document.getElementById("target-variants"),
};

function badge(label, value, active) {
  const stateClass = active ? "pill-live" : "pill-mock";
  return `
    <div class="status-pill ${stateClass}">
      <span class="status-dot"></span>
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(value)}</span>
    </div>
  `;
}


function variantCard(variant, variantIndex = 0) {
  const critiqueScores = variant.critique?.scores || {};
  const scoreMarkup = Object.entries(critiqueScores)
    .map(([key, value]) => `<span class="score-tag">${escapeHtml(key.replaceAll("_", " "))}: ${escapeHtml(value)}/5</span>`)
    .join("");

  const contextTags = variant.context
    ? `
      <div class="context-tags">
        <span class="context-tag">${escapeHtml(variant.context.location_name)}</span>
        <span class="context-tag">${escapeHtml(variant.context.market_tier)}</span>
        <span class="context-tag">${escapeHtml(variant.context.demographics)}</span>
      </div>
    `
    : "";

  const critiqueFeedback = variant.critique?.feedback
    ? `<blockquote>${escapeHtml(variant.critique.feedback)}</blockquote>`
    : `<blockquote>${escapeHtml(variant.error || "No critique feedback available.")}</blockquote>`;

  const traceButton = variant.trace_id
    ? `<button class="ghost-button trace-trigger" data-variant-index="${escapeHtml(String(variantIndex))}" type="button">View agent trace →</button>`
    : "";

  return `
    <article class="variant-card">
      <div class="trace-button-row">
        <div class="variant-meta">
          <span class="meta-tag">${escapeHtml(variant.zip_code)}</span>
          <span class="meta-tag">${escapeHtml(variant.status)}</span>
          <span class="meta-tag">${escapeHtml(variant.attempts)} attempt${variant.attempts === 1 ? "" : "s"}</span>
          <span class="meta-tag">${escapeHtml(variant.latency_ms)} ms</span>
        </div>
        ${traceButton}
      </div>
      ${contextTags}
      <div class="variant-copy">
        <h3>${escapeHtml(variant.draft?.headline || "No draft available")}</h3>
        <p>${escapeHtml(variant.draft?.body || variant.error || "The variant did not complete.")}</p>
        <p class="cta-line">${escapeHtml(variant.draft?.cta || "No CTA generated.")}</p>
        ${critiqueFeedback}
      </div>
      <div class="score-grid">${scoreMarkup}</div>
    </article>
  `;
}

function parseZipCodes(rawValue) {
  return rawValue
    .split(/[\s,]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function setFormFromSample(sample) {
  fields.corporatePrompt.value = sample.corporate_prompt;
  fields.zipCodes.value = sample.zip_codes.join(", ");
  fields.brandGuardrails.value = sample.brand_guardrails;
  fields.targetVariants.value = sample.target_variants;
}

async function loadStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  const runtime = data.runtime;

  statusBar.innerHTML = [
    badge("LLM", runtime.llm.active ? `Live · ${runtime.llm.model}` : "Mock fallback", runtime.llm.active),
    badge("Context", runtime.localizer.active ? "Live Serper" : "Mock context", runtime.localizer.active),
    badge("Workflow", runtime.workflow.runtime, true),
    badge("Critic", runtime.workflow.critic_mode, runtime.workflow.critic_mode !== "heuristic"),
  ].join("");

  const marketSource = runtime.localizer.active ? "live market intelligence via Serper" : "curated market dataset";
  runtimeNotes.innerHTML = runtime.llm.active
    ? `<div class="runtime-chip">Generating AI-powered copy via <strong>${escapeHtml(runtime.llm.provider)}</strong> · ${marketSource}.</div>`
    : `<div class="runtime-chip">Template mode — add <code>OPENAI_API_KEY</code> or <code>OPENROUTER_API_KEY</code> to <code>.env</code> to enable AI-powered copy generation.</div>`;

  presetRow.innerHTML = data.samples
    .map(
      (sample, index) => `
        <button class="preset-button" type="button" data-sample-index="${index}">
          ${sample.label}
        </button>
      `
    )
    .join("");

  data.samples.forEach((sample, index) => {
    const button = presetRow.querySelector(`[data-sample-index="${index}"]`);
    button?.addEventListener("click", () => setFormFromSample(sample));
  });

  if (data.samples.length > 0 && !fields.corporatePrompt.value.trim()) {
    setFormFromSample(data.samples[0]);
  }
}

function renderResults(result) {
  _currentVariants = result.variants;
  resultsSection.classList.remove("hidden");
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  const failedCount = result.requested_variants - result.successful_variants;
  const passRate = Math.round(result.pass_rate * 100);
  const summaryParts = [
    `${result.successful_variants} of ${result.requested_variants} location${result.requested_variants === 1 ? "" : "s"} activated`,
    `${passRate}% brand-approved`,
  ];
  if (failedCount > 0) {
    summaryParts.push(`${failedCount} issue${failedCount === 1 ? "" : "s"} flagged`);
  }
  batchSummary.textContent = summaryParts.join(" · ");

  variantGrid.innerHTML = result.variants.map((variant, i) => variantCard(variant, i)).join("");
  variantGrid.querySelectorAll(".trace-trigger").forEach((button) => {
    button.addEventListener("click", async () => {
      const idx = parseInt(button.getAttribute("data-variant-index"), 10);
      const variant = _currentVariants[idx];
      if (variant?.trace_events?.length) {
        renderTraceInline(variant);
      } else {
        await openTrace(variant?.request_id, variant?.zip_code);
      }
    });
  });
}

function renderTraceInline(variant) {
  traceTitle.textContent = `${variant.zip_code} · ${variant.request_id}`;
  traceEvents.innerHTML = variant.trace_events
    .map(
      (event) => `
        <article class="trace-event">
          <div class="trace-event-header">
            <strong>${escapeHtml(event.step)}</strong>
            <span>${escapeHtml(event.timestamp)}</span>
          </div>
          <pre>${escapeHtml(JSON.stringify(event.payload, null, 2))}</pre>
        </article>
      `
    )
    .join("");
  traceModal.showModal();
}

function renderLoadingState(payload) {
  resultsSection.classList.remove("hidden");
  resultsSection.scrollIntoView({ behavior: "smooth", block: "start" });
  batchSummary.textContent = `Activating ${payload.zip_codes.length} location${payload.zip_codes.length === 1 ? "" : "s"}...`;
  variantGrid.innerHTML = `
    <article class="variant-card">
      <div class="variant-copy">
        <h3>Gathering market signals and generating copy&hellip;</h3>
        <p>The agent pipeline is running. Multi-location batches may take a moment on the free-tier route.</p>
      </div>
    </article>
  `;
}

async function openTrace(requestId, zipCode) {
  traceTitle.textContent = `${zipCode} · ${requestId}`;
  traceEvents.innerHTML = `<p>Loading trace...</p>`;
  traceModal.showModal();
  const response = await fetch(`/api/trace?request_id=${encodeURIComponent(requestId)}&zip_code=${encodeURIComponent(zipCode)}`);
  const data = await response.json();

  if (!response.ok) {
    traceEvents.innerHTML = `<div class="trace-event"><pre>${data.error || "Trace could not be loaded."}</pre></div>`;
    return;
  }

  traceEvents.innerHTML = data.events
    .map(
      (event) => `
        <article class="trace-event">
          <div class="trace-event-header">
            <strong>${escapeHtml(event.step)}</strong>
            <span>${escapeHtml(event.timestamp)}</span>
          </div>
          <pre>${escapeHtml(JSON.stringify(event.payload, null, 2))}</pre>
        </article>
      `
    )
    .join("");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const payload = {
    corporate_prompt: fields.corporatePrompt.value.trim(),
    zip_codes: parseZipCodes(fields.zipCodes.value),
    brand_guardrails: fields.brandGuardrails.value.trim(),
    target_variants: Number(fields.targetVariants.value || 4),
  };

  renderLoadingState(payload);
  loadingIndicator.textContent = "Activating campaign...";
  generateButton.textContent = "Activating...";
  generateButton.disabled = true;

  try {
    const response = await fetch("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Generation failed.");
    }

    renderResults(data);
    loadingIndicator.textContent = "Activation complete.";
  } catch (error) {
    resultsSection.classList.remove("hidden");
    batchSummary.textContent = "";
    variantGrid.innerHTML = `<article class="variant-card"><div class="variant-copy"><h3>Activation failed</h3><p>${escapeHtml(error.message)}</p></div></article>`;
    loadingIndicator.textContent = "Request failed.";
  } finally {
    generateButton.textContent = "Activate Campaign";
    generateButton.disabled = false;
  }
});

closeTrace.addEventListener("click", () => traceModal.close());
traceModal.addEventListener("click", (event) => {
  if (event.target === traceModal) {
    traceModal.close();
  }
});

loadStatus().catch((error) => {
  statusBar.innerHTML = badge("Status", "Failed to load", false);
  runtimeNotes.innerHTML = `<div class="runtime-chip">${escapeHtml(error.message)}</div>`;
});
