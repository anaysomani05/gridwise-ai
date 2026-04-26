// GridWise AI — Dashboard logic (live-first, mock fallback for offline demo)
//
// Wire-up summary (must stay in sync with backend/main.py and agents/main.py):
//   POST {backendUrl}/optimize        -> OptimizeResponse  (see backend/schemas.py)
//   POST {agentUrl}/explain           body = OptimizeResponse
//                                     -> { explanation_text, audio_available }
//   POST {agentUrl}/explain/audio     body = OptimizeResponse
//                                     -> { explanation_text, audio_b64, mime_type }
//
// Defaults: if no settings are configured we point at localhost:8000 / :8001
// so the demo "just works" when both servers are running locally. Setting either
// URL to an empty string in the Connect APIs drawer falls back to mock data.

const STORE_KEY = "gridwise.settings.v1";

const DEFAULT_BACKEND_URL = "http://localhost:8000";
const DEFAULT_AGENT_URL = "http://localhost:8001";

let CHART = null;
// Holds the most recent optimize response. Null until the user clicks Optimize;
// renderOptimize() sets it, and onExplain() reads it to feed the agent layer.
let CURRENT_OPTIMIZE = null;

// ---- helpers
const $ = (id) => document.getElementById(id);

function loadSettings() {
  let s = {};
  try { s = JSON.parse(localStorage.getItem(STORE_KEY) || "{}"); }
  catch { s = {}; }
  // Apply defaults only if the key was never set. An explicit empty string
  // (saved from the drawer) means "force demo mode" and is preserved.
  if (typeof s.backendUrl === "undefined") s.backendUrl = DEFAULT_BACKEND_URL;
  if (typeof s.agentUrl === "undefined")   s.agentUrl   = DEFAULT_AGENT_URL;
  return s;
}
function saveSettings(s) { localStorage.setItem(STORE_KEY, JSON.stringify(s)); }

function fmtIso(ts) {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${hh}:${mm} UTC`;
}
function fmtWindow(a, b) { return `${fmtIso(a)} – ${fmtIso(b)}`; }

// Render an ISO start/end pair as a compact hour window like "18:00 – 23:00 UTC".
// We deliberately source these strings from opt.baseline / opt.optimized rather
// than reasoning.dirtiest_hours_avoided / reasoning.cleaner_hours_used, so the
// two evidence cards are guaranteed to agree with the recommendation card above
// (single source of truth: the same fields drive both).
function windowToHourRange(startIso, endIso) {
  if (!startIso || !endIso) return "—";
  const s = new Date(startIso);
  const e = new Date(endIso);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return "—";
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(s.getUTCHours())}:00 – ${pad(e.getUTCHours())}:00 UTC`;
}

// Human-friendly window string used in the "Why this schedule?" header. Matches
// the format the Gemma prompt used to produce in prose ("Sat Apr 25, 7:00 PM –
// 11:00 PM UTC" for same-day, "Sat Apr 25, 11:00 PM → Sun Apr 26, 4:00 AM UTC"
// when the window crosses midnight) so the dashboard reads consistently with
// any cached/older explanation text.
function formatHumanWindow(startIso, endIso) {
  if (!startIso || !endIso) return "—";
  const s = new Date(startIso);
  const e = new Date(endIso);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return "—";

  const DAY = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  const fmtTime = (d) => {
    const h24 = d.getUTCHours();
    const h12 = h24 % 12 || 12;
    const ampm = h24 < 12 ? "AM" : "PM";
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    return `${h12}:${mm} ${ampm}`;
  };
  const fmtDate = (d) => `${DAY[d.getUTCDay()]} ${MON[d.getUTCMonth()]} ${d.getUTCDate()}`;

  const sameDay =
    s.getUTCFullYear() === e.getUTCFullYear() &&
    s.getUTCMonth() === e.getUTCMonth() &&
    s.getUTCDate() === e.getUTCDate();

  if (sameDay) return `${fmtDate(s)}, ${fmtTime(s)} – ${fmtTime(e)} UTC`;
  return `${fmtDate(s)}, ${fmtTime(s)} → ${fmtDate(e)}, ${fmtTime(e)} UTC`;
}

function setText(id, val) { const el = $(id); if (el) el.textContent = val; }

// The two date/time inputs are <input type="datetime-local">, which yields a
// naive string like "2026-04-25T18:00" with no timezone. We treat what the
// user picks as already-UTC (matching the field labels), so we just append
// seconds + "Z" to produce the ISO-8601 UTC string the backend expects.
function localToUtcIso(localStr) {
  if (!localStr) return "";
  // Tolerate values that already include seconds or a "Z" suffix.
  if (/Z$/.test(localStr)) return localStr;
  const withSeconds = localStr.length === 16 ? `${localStr}:00` : localStr;
  return `${withSeconds}Z`;
}

function updateModeBadge() {
  const s = loadSettings();
  const live = !!(s.backendUrl || s.agentUrl);
  const el = $("modeBadge");
  if (!el) return;
  el.textContent = live ? "Live" : "Demo";
}

// ---- chart
function renderChart(opt) {
  const ctx = $("mainChart");
  if (!ctx) return;
  const series = opt.timeseries || [];
  const labels = series.map((p) => fmtIso(p.timestamp));
  const carbon = series.map((p) => Number(p.signal) || 0);

  const tsToIdx = new Map(series.map((p, i) => [p.timestamp, i]));
  const inRange = (t, a, b) => {
    const x = new Date(t).getTime();
    return x >= new Date(a).getTime() && x <= new Date(b).getTime();
  };

  const baseMask = series.map((p) => (opt.baseline && inRange(p.timestamp, opt.baseline.start, opt.baseline.end) ? Number(p.signal) : null));
  const optMask  = series.map((p) => (opt.optimized && inRange(p.timestamp, opt.optimized.start, opt.optimized.end) ? Number(p.signal) : null));

  const data = {
    labels,
    datasets: [
      {
        label: "Carbon",
        data: carbon,
        borderColor: "#0f172a",
        backgroundColor: "rgba(15,23,42,0.04)",
        borderWidth: 2.4,
        tension: 0.35,
        pointRadius: 0,
        fill: true,
      },
      {
        label: "Baseline window",
        data: baseMask,
        borderColor: "rgba(249,115,22,0.0)",
        backgroundColor: "rgba(249,115,22,0.22)",
        borderWidth: 0,
        tension: 0.35,
        pointRadius: 0,
        fill: true,
      },
      {
        label: "Optimized window",
        data: optMask,
        borderColor: "rgba(20,184,166,0.0)",
        backgroundColor: "rgba(20,184,166,0.28)",
        borderWidth: 0,
        tension: 0.35,
        pointRadius: 0,
        fill: true,
      },
    ],
  };

  if (CHART) CHART.destroy();
  CHART = new Chart(ctx, {
    type: "line",
    data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0b1220",
          padding: 10,
          callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${ctx.parsed.y ?? "—"}` },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#94a3b8", font: { size: 11 } } },
        y: { grid: { color: "rgba(2,6,23,0.05)" }, ticks: { color: "#94a3b8", font: { size: 11 } }, title: { display: true, text: "gCO₂e/kWh", color: "#64748b" } },
      },
    },
  });
}

// ---- render result blocks
function renderOptimize(opt) {
  CURRENT_OPTIMIZE = opt;
  const b = opt.baseline || {};
  const o = opt.optimized || {};
  const m = opt.metrics || {};

  setText("optimizedWindow", o.start && o.end ? fmtWindow(o.start, o.end) : "—");
  setText("baselineWindow", b.start && b.end ? fmtWindow(b.start, b.end) : "—");
  setText("startAfterEcho", localToUtcIso($("startAfter").value) || (opt.request && opt.request.start_after) || "—");

  setText("co2Saved", (m.co2_saved_kg ?? 0).toFixed(1));
  setText("reductionPct", (m.percent_reduction ?? 0).toFixed(1));
  setText("providerName", opt.provider || "—");
  setText("signalType", opt.signal_type || "—");

  setText("baselineKg", (b.emissions_kg ?? 0).toFixed(1));
  setText("optimizedKg", (o.emissions_kg ?? 0).toFixed(1));
  setText("kgAvoided", (m.co2_saved_kg ?? 0).toFixed(1));
  setText("pctReduction", (m.percent_reduction ?? 0).toFixed(1));

  const met = !!m.deadline_met;
  const badge = $("metDeadline");
  if (badge) {
    badge.textContent = met ? "Deadline met" : "Deadline missed";
    badge.className = `pill ${met ? "bg-teal-50 text-teal-700" : "bg-rose-50 text-rose-700"}`;
  }

  renderChart(opt);
  renderTimeShift(opt);
  renderReasoningBoxes(opt);

  // Reset the explanation paragraph immediately so the previous run's text
  // doesn't sit next to the new chart/KPIs while we wait for /explain. The
  // onExplain() handler will overwrite this with the loading state and then
  // the real Gemma output.
  setText("explainText", "Generating explanation…");

  $("rawJson").textContent = JSON.stringify(opt, null, 2);
}

// Two-row "Original time / Optimised time" header that sits above the Gemma
// prose. Sourced from opt.baseline / opt.optimized so it always agrees with
// the recommendation card and updates the instant /optimize returns — no
// waiting on the agent round-trip. When baseline == optimized we collapse the
// second row into a short "Same as original" hint instead of repeating the
// window, because seeing the identical line twice always reads as a bug.
function renderTimeShift(opt) {
  const block = $("timeShift");
  if (!block) return;
  const b = opt.baseline || {};
  const o = opt.optimized || {};
  const sameWindow = b.start === o.start && b.end === o.end;

  const originalStr = formatHumanWindow(b.start, b.end);
  const optimisedStr = sameWindow
    ? "Same as original — no cleaner window in this range"
    : formatHumanWindow(o.start, o.end);

  const labelCls = "text-ink2 font-medium";
  const valueCls = "text-slate-800";
  const optimisedValueCls = sameWindow ? "text-slate-500 italic" : valueCls;

  block.innerHTML =
    `<div class="${labelCls}">Original time</div>` +
    `<div class="${valueCls}">${originalStr}</div>` +
    `<div class="${labelCls}">Optimised time</div>` +
    `<div class="${optimisedValueCls}">${optimisedStr}</div>`;
}

// The two evidence cards under "Why this schedule?". Driven from the same
// baseline/optimized fields the recommendation card uses so they cannot drift
// out of sync. When the optimizer can't beat ASAP (b == o), both cards show
// the same window — that's the truthful signal that no shift was available.
function renderReasoningBoxes(opt) {
  const block = $("reasoningBlock");
  if (!block) return;
  const b = opt.baseline || {};
  const o = opt.optimized || {};
  const sameWindow = b.start === o.start && b.end === o.end;

  const items = [
    {
      k: "Dirtiest hours avoided",
      v: windowToHourRange(b.start, b.end),
      hint: sameWindow ? "no cleaner window available" : null,
    },
    {
      k: "Cleaner hours used",
      v: windowToHourRange(o.start, o.end),
      hint: sameWindow ? "same as baseline — no shift" : null,
    },
  ];

  block.innerHTML = "";
  for (const it of items) {
    const card = document.createElement("div");
    card.className = "kpi";
    const hintHtml = it.hint
      ? `<div class="mt-1 text-[11px] text-slate-500">${it.hint}</div>`
      : "";
    card.innerHTML =
      `<div class="label">${it.k}</div>` +
      `<div class="mt-1 text-sm font-semibold tracking-tight">${it.v}</div>` +
      hintHtml;
    block.appendChild(card);
  }
}

function renderExplain(exp) {
  const text = (exp && (exp.text_explanation || exp.text)) || "No explanation available.";
  setText("explainText", text);

  const audio = exp && exp.audio;
  const audioBlock = $("audioBlock");
  const audioLink = $("audioLink");
  if (audio && audio.url) {
    audioLink.href = audio.url;
    audioBlock.classList.remove("hidden");
  } else {
    audioBlock.classList.add("hidden");
  }
}

// ---- API calls
// Matches backend/schemas.py::OptimizeRequest. duration_hours is an int.
function buildPayload() {
  return {
    region: $("region").value,
    job_name: $("jobName").value || "job",
    duration_hours: Math.max(1, Math.round(Number($("durationHours").value) || 1)),
    power_kw: Number($("powerKw").value) || 1,
    start_after: localToUtcIso($("startAfter").value),
    deadline: localToUtcIso($("deadline").value),
  };
}

// Build a smart mock result from whatever the user entered in the form.
// This lets the demo "work" with any inputs while backend is offline.
function buildSmartMock(payload) {
  const startAfter = new Date(payload.start_after || "2026-04-25T18:00:00Z");
  const deadline   = new Date(payload.deadline   || "2026-04-26T08:00:00Z");
  const durH       = Number(payload.duration_hours) || 4;
  const powerKw    = Number(payload.power_kw)       || 12;

  // Generate 24-hour synthetic carbon curve anchored to startAfter
  const hours = [];
  for (let i = 0; i < 24; i++) {
    const t = new Date(startAfter.getTime() + i * 3600000);
    const h = t.getUTCHours();
    // Sinusoidal: peaks ~19:00 UTC, troughs ~03:00 UTC
    const signal = Math.round(350 + 90 * Math.sin((h - 3) * Math.PI / 12));
    hours.push({ ts: t, signal });
  }

  // Baseline: starts at startAfter
  const baselineSlice = hours.slice(0, durH);
  const baselineAvg   = baselineSlice.reduce((s, h) => s + h.signal, 0) / durH;
  const baselineKg    = parseFloat(((baselineAvg * powerKw * durH) / 1e6 * 1000).toFixed(2)); // gCO2->kg

  // Find lowest-emission contiguous window of durH hours that finishes before deadline
  let bestStart = 0, bestSum = Infinity;
  for (let i = 0; i <= hours.length - durH; i++) {
    const windowEnd = new Date(hours[i].ts.getTime() + durH * 3600000);
    if (windowEnd > deadline) break;
    const sum = hours.slice(i, i + durH).reduce((s, h) => s + h.signal, 0);
    if (sum < bestSum) { bestSum = sum; bestStart = i; }
  }
  const optSlice   = hours.slice(bestStart, bestStart + durH);
  const optAvg     = bestSum / durH;
  const optKg      = parseFloat(((optAvg * powerKw * durH) / 1e6 * 1000).toFixed(2));
  const savedKg    = parseFloat((baselineKg - optKg).toFixed(2));
  const pctSaved   = parseFloat((savedKg / baselineKg * 100).toFixed(1));

  const toIso = (d) => d.toISOString();

  return {
    request: payload,
    provider: "demo_model",
    signal_type: "carbon_intensity",
    baseline: {
      start:        toIso(startAfter),
      end:          toIso(new Date(startAfter.getTime() + durH * 3600000)),
      emissions_kg: baselineKg,
    },
    optimized: {
      start:        toIso(hours[bestStart].ts),
      end:          toIso(new Date(hours[bestStart].ts.getTime() + durH * 3600000)),
      emissions_kg: optKg,
    },
    metrics: {
      co2_saved_kg:      savedKg,
      percent_reduction: pctSaved,
      deadline_met:      true,
    },
    timeseries: hours.map((h) => ({ timestamp: toIso(h.ts), signal: h.signal })),
    reasoning: {
      baseline_avg_signal: Math.round(baselineAvg),
      optimized_avg_signal: Math.round(optAvg),
      dirtiest_hours_avoided: baselineSlice.filter(h => h.signal > optAvg + 20).map(h => `${String(h.ts.getUTCHours()).padStart(2,"0")}:00`),
      cleaner_hours_used: optSlice.filter(h => h.signal < baselineAvg).map(h => `${String(h.ts.getUTCHours()).padStart(2,"0")}:00`),
    },
  };
}

async function callOptimize() {
  const s = loadSettings();
  const payload = buildPayload();
  setText("reqStatus", "Optimizing...");
  if (!s.backendUrl) {
    await new Promise((r) => setTimeout(r, 320));
    setText("reqStatus", "Demo mode");
    return buildSmartMock(payload);
  }
  try {
    const url = `${s.backendUrl.replace(/\/$/, "")}/optimize`;
    const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    setText("reqStatus", "Live - backend ok");
    return data;
  } catch (e) {
    setText("reqStatus", `Backend unavailable - using demo`);
    return buildSmartMock(payload);
  }
}

function buildSmartExplain(opt) {
  const m = opt.metrics || {};
  const b = opt.baseline || {};
  const o = opt.optimized || {};
  const r = opt.reasoning || {};
  const pct  = (m.percent_reduction ?? 0).toFixed(1);
  const kg   = (m.co2_saved_kg ?? 0).toFixed(1);
  const bAvg = r.baseline_avg_signal || "higher";
  const oAvg = r.optimized_avg_signal || "lower";
  const bStart = fmtIso(b.start || "");
  const oStart = fmtIso(o.start || "");
  return {
    text_explanation:
      `Running at ${bStart} would overlap higher-carbon grid conditions (avg ${bAvg} gCO2/kWh). ` +
      `GridWise identified a cleaner window starting at ${oStart} (avg ${oAvg} gCO2/kWh) that still meets the deadline, ` +
      `cutting estimated emissions by ${pct}% and avoiding approximately ${kg} kg CO2 — same work, smarter timing.`
  };
}

// Decode a base-64 string into an audio Blob URL the <a href> can play directly.
function audioB64ToObjectUrl(b64, mime = "audio/mpeg") {
  try {
    const bin = atob(b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return URL.createObjectURL(new Blob([bytes], { type: mime }));
  } catch (e) {
    console.warn("audio decode failed", e);
    return null;
  }
}

// Calls the agent layer. Body is the full OptimizeResponse — agents/main.py
// validates against the OptimizeResponse pydantic model, so any other shape 422s.
async function callExplain(opt) {
  const s = loadSettings();
  if (!s.agentUrl) {
    await new Promise((r) => setTimeout(r, 200));
    return buildSmartExplain(opt);
  }

  const base = s.agentUrl.replace(/\/$/, "");
  const url = s.includeAudio ? `${base}/explain/audio` : `${base}/explain`;

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opt),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    // Agent contract: { explanation_text, audio_available }  (or audio_b64 + mime_type for /explain/audio)
    const out = { text_explanation: data.explanation_text || "" };
    if (data.audio_b64) {
      const objUrl = audioB64ToObjectUrl(data.audio_b64, data.mime_type || "audio/mpeg");
      if (objUrl) out.audio = { url: objUrl };
    }
    return out;
  } catch (e) {
    console.warn("explain failed", e);
    return buildSmartExplain(opt);
  }
}

// Pull the canonical zone list from the backend so the region dropdown stays in
// sync with what the optimizer actually supports. Returns null on any failure
// (no backend configured, network error, non-2xx) — the caller leaves the
// hardcoded HTML options in place so the demo still works offline.
async function callRegions() {
  const s = loadSettings();
  if (!s.backendUrl) return null;
  try {
    const url = `${s.backendUrl.replace(/\/$/, "")}/regions`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return Array.isArray(data.regions) && data.regions.length ? data.regions : null;
  } catch (e) {
    console.warn("regions failed", e);
    return null;
  }
}

// Replace the <select id="region"> options with the live list, grouped by country.
// Preserves the user's current selection when the same code is still offered.
async function refreshRegions() {
  const regions = await callRegions();
  const sel = $("region");
  if (!sel || !regions) return; // keep the hardcoded fallback options

  const previous = sel.value;

  // Group by country in server order so geographic sections stay together.
  const groups = new Map();
  for (const r of regions) {
    const key = r.country || "Other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(r);
  }

  sel.innerHTML = "";
  for (const [country, rs] of groups) {
    const og = document.createElement("optgroup");
    og.label = country;
    for (const r of rs) {
      const opt = document.createElement("option");
      opt.value = r.code;
      opt.textContent = r.label || r.code;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }

  if (previous && [...sel.options].some((o) => o.value === previous)) {
    sel.value = previous;
  }
}

// ---- handlers
// Re-entry guard. Optimize auto-chains into Explain, so if the user spam-clicks
// Optimize we don't want to fire two parallel /explain round-trips at the
// agent. The flag is reset in the onExplain() finally block so a failed call
// doesn't lock the UI.
let EXPLAIN_IN_FLIGHT = false;

async function onOptimize() {
  const opt = await callOptimize();
  renderOptimize(opt);

  // Auto-explain: as soon as the optimizer returns, kick off the Gemma
  // explanation so the user sees the "why" without a second click. There is
  // no manual "Explain with AI" button anymore — Optimize is the single
  // entry point and Explain is part of the same flow.
  await onExplain();
}

async function onExplain() {
  if (EXPLAIN_IN_FLIGHT) return;
  EXPLAIN_IN_FLIGHT = true;

  // Make the loading state visible immediately — the Gemma round-trip can
  // take a couple of seconds and an empty card looks broken.
  setText("explainText", "Generating explanation…");

  try {
    const exp = await callExplain(CURRENT_OPTIMIZE);
    renderExplain(exp);
  } finally {
    EXPLAIN_IN_FLIGHT = false;
  }
}

function openDrawer() {
  $("drawer").classList.remove("hidden");
  const s = loadSettings();
  $("backendUrl").value = s.backendUrl ?? "";
  $("agentUrl").value = s.agentUrl ?? "";
  $("includeAudio").checked = !!s.includeAudio;
}
function closeDrawer() { $("drawer").classList.add("hidden"); }

function bind() {
  $("optimizeBtn").addEventListener("click", onOptimize);
  $("optimizeTopBtn").addEventListener("click", onOptimize);
  $("settingsBtn").addEventListener("click", openDrawer);
  $("closeDrawer").addEventListener("click", closeDrawer);
  $("drawerBackdrop").addEventListener("click", closeDrawer);
  $("saveSettings").addEventListener("click", () => {
    saveSettings({
      backendUrl: $("backendUrl").value.trim(),
      agentUrl: $("agentUrl").value.trim(),
      includeAudio: $("includeAudio").checked,
    });
    updateModeBadge();
    closeDrawer();
    // New backend URL might support a different region set — re-pull it.
    refreshRegions();
  });
  $("resetSettings").addEventListener("click", () => {
    // Explicitly empty (not undefined) → loadSettings() preserves it as "demo mode".
    saveSettings({ backendUrl: "", agentUrl: "", includeAudio: false });
    updateModeBadge();
    closeDrawer();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  bind();
  updateModeBadge();
  // No on-load mock render — the result/chart/explain cards keep their static
  // empty-state copy from app.html until the user clicks "Optimize schedule".
  // Populate the region dropdown from /regions; keeps frontend and backend in sync.
  // Falls back silently to the hardcoded HTML <option>s if the backend is offline.
  refreshRegions();
});
