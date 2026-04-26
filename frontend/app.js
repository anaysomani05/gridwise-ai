// GridWise AI — Dashboard logic (live-first, mock fallback for offline demo)
//
// Wire-up summary (must stay in sync with backend/main.py and agents/main.py):
//   POST {backendUrl}/optimize        -> OptimizeResponse  (see backend/schemas.py)
//                                     body may include instance_type (preset id) with
//                                     power_kw null, or power_kw alone for Custom hardware
//   POST {agentUrl}/explain           body = OptimizeResponse
//                                     -> { explanation_text, audio_available }
//   POST {agentUrl}/explain/audio     body = OptimizeResponse
//                                     -> { explanation_text, audio_b64, mime_type }
//   POST {backendUrl}/chat            -> proxy to agent (preferred when backend set)
//   POST {agentUrl}/chat              -> same contract if only agent URL configured
//   POST {backendUrl}/equivalencies   body = OptimizeResponse -> { equivalencies: [s,s,s] } (proxy)
//   POST {agentUrl}/equivalencies     same; if no URL, UI uses local ballpark lines from kg saved
//
// Defaults: if no settings are configured we point at localhost:8000 / :8001
// so the demo "just works" when both servers are running locally. Setting either
// URL to an empty string in the Connect data drawer falls back to mock data.

const STORE_KEY = "gridwise.settings.v1";

const DEFAULT_BACKEND_URL = "http://localhost:8000";
const DEFAULT_AGENT_URL = "http://localhost:8001";

/** Default duration_hours when user picks a workload preset (matches product spec). */
const WORKLOAD_DEFAULT_HOURS = {
  training: 12,
  llm_finetune: 4,
  batch_inference: 2,
  etl: 2,
  analytics: 1,
};

/** Dashboard instance presets first; must match backend/services/instance_types.py order of preset.* */
const DASHBOARD_PRESET_ORDER = [
  "preset.a100_pcie",
  "preset.a100_sxm",
  "preset.a100_node8",
  "preset.h100_node8",
  "preset.cluster_multinode",
  "preset.cpu_node",
];

/**
 * Offline mirror of GET /instance-types (shape: { name, power_kw, label, category }).
 * Kept in sync with backend/services/instance_types.py for demo-mode math.
 */
const FALLBACK_INSTANCE_TYPES_LIST = [
  { name: "preset.a100_pcie", power_kw: 0.3, label: "Single A100 GPU (PCIe)", category: "gpu" },
  { name: "preset.a100_sxm", power_kw: 0.4, label: "Single A100 GPU (SXM)", category: "gpu" },
  { name: "preset.a100_node8", power_kw: 6, label: "8× A100 node (full server)", category: "gpu" },
  { name: "preset.h100_node8", power_kw: 10, label: "8× H100 node (full server)", category: "gpu" },
  { name: "preset.cluster_multinode", power_kw: 32, label: "Multi-node training cluster", category: "training-cluster" },
  { name: "preset.cpu_node", power_kw: 0.5, label: "CPU-only compute node", category: "cpu" },
  { name: "cpu.small", power_kw: 0.05, label: "1 vCPU general-purpose VM", category: "cpu" },
  { name: "cpu.medium", power_kw: 0.15, label: "4 vCPU general-purpose VM", category: "cpu" },
  { name: "cpu.large", power_kw: 0.4, label: "16 vCPU general-purpose VM", category: "cpu" },
  { name: "cpu.xlarge", power_kw: 1.1, label: "64 vCPU compute node", category: "cpu" },
  { name: "gpu.t4", power_kw: 0.3, label: "1× NVIDIA T4 inference VM", category: "gpu" },
  { name: "gpu.l4", power_kw: 0.45, label: "1× NVIDIA L4 inference VM", category: "gpu" },
  { name: "gpu.a10", power_kw: 0.65, label: "1× NVIDIA A10 inference VM", category: "gpu" },
  { name: "gpu.a100.40g", power_kw: 1.2, label: "1× NVIDIA A100 40GB", category: "gpu" },
  { name: "gpu.a100.80g.x4", power_kw: 5, label: "4× NVIDIA A100 80GB training VM", category: "gpu" },
  { name: "gpu.h100.x1", power_kw: 2.2, label: "1× NVIDIA H100 SXM", category: "gpu" },
  { name: "gpu.h100.x8", power_kw: 12, label: "8× NVIDIA H100 SXM training VM", category: "gpu" },
  { name: "gpu.h100.x64", power_kw: 96, label: "8-node H100 cluster (64 GPUs)", category: "training-cluster" },
];

/** name -> power_kw for buildSmartMock; rebuilt when /instance-types succeeds. */
let instancePowerKwByName = Object.fromEntries(FALLBACK_INSTANCE_TYPES_LIST.map((i) => [i.name, i.power_kw]));

let CHART = null;
// Holds the most recent optimize response. Null until the user clicks Optimize;
// renderOptimize() sets it, and onExplain() reads it to feed the agent layer.
let CURRENT_OPTIMIZE = null;

const LAST_RUN_KEY = "gridwise.lastRun.v1";
/** @type {{ role: string, content: string }[]} */
let CHAT_HISTORY = [];

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

// ---- Talk to agent: chat + last-run memory
function loadLastRun() {
  try {
    return JSON.parse(localStorage.getItem(LAST_RUN_KEY) || "null");
  } catch {
    return null;
  }
}

/** Slim POST /optimize payload for chat + what-if math (caps timeseries size). */
function compactOptimizeForChat(opt) {
  if (!opt || typeof opt !== "object") return null;
  const ts = Array.isArray(opt.timeseries) ? opt.timeseries : [];
  const maxPts = 168;
  let slimTs = ts;
  if (ts.length > maxPts) {
    const step = Math.ceil(ts.length / maxPts);
    slimTs = ts.filter((_, i) => i % step === 0);
  }
  return {
    request: opt.request,
    provider: opt.provider,
    signal_type: opt.signal_type,
    baseline: opt.baseline,
    optimized: opt.optimized,
    metrics: opt.metrics,
    reasoning: opt.reasoning,
    timeseries: slimTs,
    data_source: opt.data_source,
    optimization_note: opt.optimization_note,
    data_quality: opt.data_quality,
  };
}

/** Last optimization digest: in-memory run wins; else restore from localStorage after refresh. */
function chatLastOptimizePayload() {
  if (CURRENT_OPTIMIZE) return compactOptimizeForChat(CURRENT_OPTIMIZE);
  try {
    const lr = JSON.parse(localStorage.getItem(LAST_RUN_KEY) || "null");
    return lr?.optimize_digest || null;
  } catch {
    return null;
  }
}

function persistLastRun(opt) {
  try {
    const payload = buildPayload();
    localStorage.setItem(
      LAST_RUN_KEY,
      JSON.stringify({
        at: new Date().toISOString(),
        request: payload,
        region: payload.region,
        percent_reduction: opt.metrics?.percent_reduction,
        co2_saved_kg: opt.metrics?.co2_saved_kg,
        mode: "carbon",
        optimize_digest: compactOptimizeForChat(opt),
      }),
    );
  } catch (e) {
    console.warn("persistLastRun", e);
  }
}

function utcIsoToDatetimeLocal(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${y}-${m}-${day}T${hh}:${mm}`;
}

function shiftDatetimeLocal(inputId, hours) {
  const el = $(inputId);
  if (!el || !el.value) return;
  const iso = localToUtcIso(el.value);
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return;
  d.setTime(d.getTime() + hours * 3600000);
  el.value = utcIsoToDatetimeLocal(d.toISOString());
}

function applyTightDeadlineNearNow() {
  const startEl = $("startAfter");
  const durEl = $("durationHours");
  const deadEl = $("deadline");
  if (!startEl || !durEl || !deadEl || !startEl.value) return;
  const startIso = localToUtcIso(startEl.value);
  const dur = Math.max(1, Math.round(Number(durEl.value) || 1));
  const d = new Date(startIso);
  if (Number.isNaN(d.getTime())) return;
  d.setUTCHours(d.getUTCHours() + dur + 2);
  deadEl.value = utcIsoToDatetimeLocal(d.toISOString());
}

function collectFormState() {
  const regionSel = $("region");
  const codes = regionSel ? [...regionSel.options].map((o) => o.value).filter(Boolean) : [];
  return {
    region: regionSel?.value,
    duration_hours: Math.round(Number($("durationHours")?.value) || 1),
    job_name: $("jobName")?.value,
    mode: "carbon",
    instance_preset: $("instancePreset")?.value,
    power_kw: $("powerKw")?.value,
    start_after_local: $("startAfter")?.value,
    deadline_local: $("deadline")?.value,
    available_regions_sample: codes.slice(0, 48),
  };
}

function applyChatPatch(patch) {
  if (!patch || typeof patch !== "object") return;
  const r = $("region");
  if (patch.region && r) {
    const v = String(patch.region);
    if ([...r.options].some((o) => o.value === v)) r.value = v;
  }
  const ext = Number(patch.deadline_extend_hours);
  if (Number.isFinite(ext) && ext !== 0) shiftDatetimeLocal("deadline", ext);
  const sh = Number(patch.deadline_shorten_hours);
  if (Number.isFinite(sh) && sh > 0) shiftDatetimeLocal("deadline", -sh);
  const st = Number(patch.start_shift_hours);
  if (Number.isFinite(st) && st !== 0) shiftDatetimeLocal("startAfter", st);
  const dh = Number(patch.duration_hours);
  if (Number.isFinite(dh) && dh > 0) $("durationHours").value = String(Math.max(1, Math.round(dh)));
}

function appendChatBubble(role, text, opts = {}) {
  const skipHistory = !!opts.skipHistory;
  const box = $("chatMessages");
  if (!box) return;
  const wrap = document.createElement("div");
  wrap.className = role === "user" ? "flex justify-end" : "flex justify-start";
  const bubble = document.createElement("div");
  bubble.className =
    role === "user"
      ? "max-w-[92%] rounded-2xl rounded-br-md bg-ink text-white text-sm px-4 py-2.5 leading-relaxed whitespace-pre-wrap break-words"
      : "max-w-[92%] rounded-2xl rounded-bl-md bg-white border border-black/10 text-sm px-4 py-2.5 leading-relaxed text-slate-800 shadow-sm whitespace-pre-wrap break-words";
  bubble.textContent = text;
  wrap.appendChild(bubble);
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
  if (!skipHistory && (role === "user" || role === "assistant")) {
    CHAT_HISTORY.push({ role, content: text });
    while (CHAT_HISTORY.length > 14) CHAT_HISTORY.shift();
  }
}

function buildWelcomeMessage() {
  const lr = loadLastRun();
  if (!lr || !lr.region) {
    return (
      "Hi — I'm here to chat about your job and the last optimization: trade-offs like “what if we start an hour earlier?” " +
      "Run Optimize on the Dashboard first so I have numbers; then ask away or use a quick action. " +
      "Open Dashboard anytime for the timeline and full form."
    );
  }
  const pct = lr.percent_reduction != null ? Number(lr.percent_reduction).toFixed(1) : "—";
  const kg = lr.co2_saved_kg != null ? Number(lr.co2_saved_kg).toFixed(1) : "—";
  return (
    `Welcome back. Last run was in ${lr.region}: about ${pct}% less CO₂ than baseline (${kg} kg saved). ` +
    "Ask how moving the recommended window earlier or later would change emissions, or tell me a new goal."
  );
}

function ensureAgentWelcome() {
  const box = $("chatMessages");
  if (!box || box.dataset.welcomeDone === "1") return;
  if (box.childElementCount > 0) return;
  appendChatBubble("assistant", buildWelcomeMessage(), { skipHistory: true });
  box.dataset.welcomeDone = "1";
}

function heuristicChatReply(userText) {
  const t = userText.toLowerCase();
  const patch = {};
  let message = "";
  let suggest_optimize = true;

  const zoneMatch = userText.match(/\b([A-Z]{2}(?:-[A-Z0-9]+)+)\b/);
  if (zoneMatch) patch.region = zoneMatch[1];

  if (/same|again|rerun|repeat/i.test(t)) {
    message = "Re-running with your saved fields unchanged.";
    suggest_optimize = true;
  } else if (/maximize|max.*carbon|reduce emission|as clean|as much as possible|lowest carbon/i.test(t)) {
    patch.deadline_extend_hours = 12;
    message = "Deadline widened by 12 hours so the backend can search for cleaner windows (carbon-only optimization).";
  } else if (/balance.*carbon|carbon.*cost|both|balanced|cost.?optim/i.test(t)) {
    message =
      "This app only optimizes for lowest grid carbon. I can still widen your deadline or shift your search window—say “more flexibility” if you want that.";
    suggest_optimize = false;
  } else if (/aggressive|widen|more flex|more time/i.test(t)) {
    patch.deadline_extend_hours = 24;
    message = "Extended the deadline by 24 hours for a wider search.";
  } else if (/close|tight|soon|minimal delay|asap|near now/i.test(t)) {
    applyTightDeadlineNearNow();
    message = "Tightened the deadline to just after your job duration — less flexibility, closer to “run soon”.";
  } else {
    message =
      "I'll pass that to the optimizer with your current fields. Name a region clearly if you want to switch zones (e.g. US-CAL-CISO).";
    suggest_optimize = true;
  }

  return { assistant_message: message, patch, suggest_optimize };
}

async function callAgentChatApi(userTextForHeuristic) {
  const s = loadSettings();
  const last = loadLastRun();
  const last_run = last
    ? {
        region: last.region,
        percent_reduction: last.percent_reduction,
        co2_saved_kg: last.co2_saved_kg,
        mode: last.mode,
        at: last.at,
      }
    : null;

  // Prefer optimizer backend POST /chat (proxy → agent) when backendUrl is set,
  // so the chatbot uses the same base URL as POST /optimize.
  const useBackend = !!s.backendUrl;
  const base = useBackend
    ? s.backendUrl.replace(/\/$/, "")
    : (s.agentUrl || "").replace(/\/$/, "");
  if (!base) {
    return heuristicChatReply(userTextForHeuristic);
  }

  const url = `${base}/chat`;
  const messages = [...CHAT_HISTORY];

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages,
        last_run,
        last_optimize: chatLastOptimizePayload(),
        form_state: collectFormState(),
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return {
      assistant_message: data.assistant_message || "",
      patch: data.patch || {},
      suggest_optimize: !!data.suggest_optimize,
    };
  } catch (e) {
    console.warn("chat failed", e);
    return heuristicChatReply(userTextForHeuristic);
  }
}

/** After the latest user line is in CHAT_HISTORY, fetch assistant reply and optional auto-optimize. */
async function finishChatTurn(userTextForHeuristic) {
  const typing = document.createElement("div");
  typing.id = "chatTyping";
  typing.className = "text-xs text-slate-500 px-1";
  typing.textContent = "Thinking…";
  $("chatMessages")?.appendChild(typing);

  let out;
  try {
    out = await callAgentChatApi(userTextForHeuristic);
  } finally {
    $("chatTyping")?.remove();
  }

  applyChatPatch(out.patch || {});
  appendChatBubble("assistant", out.assistant_message || "Done.");
  if (out.suggest_optimize) {
    appendChatBubble("assistant", "Running optimize on your backend now…", { skipHistory: true });
    await onOptimize();
  }
}

async function handleChatSend() {
  const input = $("chatInput");
  if (!input) return;
  const raw = input.value.trim();
  if (!raw) return;
  input.value = "";
  appendChatBubble("user", raw);
  await finishChatTurn(raw);
}

async function handleQuickAction(action) {
  const labels = {
    same_setup: "Run the same setup again",
    max_carbon: "Maximize carbon savings",
    aggressive: "Be more aggressive",
    close_now: "Keep it close to now",
    what_if_earlier:
      "If we start the optimized window one hour earlier than the recommendation, how much worse would CO₂ be vs the current optimized slot?",
  };
  const label = labels[action] || action;
  appendChatBubble("user", label);

  if (action === "what_if_earlier") {
    await finishChatTurn(label);
    return;
  }

  if (action === "same_setup") {
    appendChatBubble("assistant", "Re-running with the same parameters.", { skipHistory: true });
    await onOptimize();
    return;
  }
  if (action === "max_carbon") {
    shiftDatetimeLocal("deadline", 12);
    appendChatBubble("assistant", "+12h on the deadline for a wider carbon search. Optimizing…", { skipHistory: true });
    await onOptimize();
    return;
  }
  if (action === "aggressive") {
    shiftDatetimeLocal("deadline", 24);
    appendChatBubble("assistant", "+24h on the deadline for a wider search. Optimizing…", { skipHistory: true });
    await onOptimize();
    return;
  }
  if (action === "close_now") {
    applyTightDeadlineNearNow();
    appendChatBubble("assistant", "Deadline pulled tight after start + duration. Optimizing…", { skipHistory: true });
    await onOptimize();
    return;
  }
}

function maybeAppendAgentRunSummary(opt) {
  if (getTabFromUrl() !== "agent") return;
  const m = opt.metrics || {};
  const req = opt.request || {};
  const kg = (m.co2_saved_kg ?? 0).toFixed(1);
  const pct = (m.percent_reduction ?? 0).toFixed(1);
  const ex = ($("explainText") && $("explainText").textContent) || "";
  const line1 = `Run complete: ${kg} kg CO₂ saved (${pct}% vs baseline) in ${req.region || "your zone"}.`;
  const line2 = ex ? `Summary: ${ex}` : "";
  appendChatBubble("assistant", line2 ? `${line1}\n\n${line2}` : line1);
}

function bindAgentChatUi() {
  const chips = $("chatChips");
  if (chips) {
    chips.addEventListener("click", (e) => {
      const btn = e.target.closest("[data-chat-action]");
      if (!btn) return;
      handleQuickAction(btn.getAttribute("data-chat-action"));
    });
  }
  const send = $("chatSendBtn");
  if (send) send.addEventListener("click", () => handleChatSend());
  const inp = $("chatInput");
  if (inp) {
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleChatSend();
      }
    });
  }
  const link = $("linkDashboardFromChat");
  if (link) link.addEventListener("click", () => setAppTab("dashboard", { push: true }));
}

/** @returns {"dashboard" | "agent"} */
function getTabFromUrl() {
  try {
    const t = new URLSearchParams(window.location.search).get("tab");
    if (t === "agent" || t === "dashboard") return t;
  } catch {
    /* ignore */
  }
  return "dashboard";
}

/**
 * @param {"dashboard" | "agent"} tab
 * @param {{ push?: boolean }} [opts]
 */
const _AGENT_MAIN_FILL = ["flex", "flex-col", "min-h-[calc(100dvh-4rem)]"];
const _AGENT_PAGE_INTRO_SHRINK = ["shrink-0"];
const _AGENT_CHAT_GROW = ["flex-1", "min-h-0"];

function setAppTab(tab, opts = {}) {
  const push = !!opts.push;
  const appMain = $("appMain");
  const pageIntro = $("pageIntro");
  const topRow = $("topRow");
  const agentPanel = $("agentChatPanel");
  const title = $("pageTitle");
  const sub = $("pageSubtitle");
  const bd = $("tabBtnDashboard");
  const ba = $("tabBtnAgent");

  if (tab === "agent") {
    _AGENT_MAIN_FILL.forEach((c) => appMain?.classList.add(c));
    _AGENT_PAGE_INTRO_SHRINK.forEach((c) => pageIntro?.classList.add(c));
    _AGENT_CHAT_GROW.forEach((c) => agentPanel?.classList.add(c));
    if (topRow) {
      topRow.classList.add("hidden");
      topRow.classList.remove("flex", "flex-col", "flex-col-reverse");
      topRow.classList.add("grid", "lg:grid-cols-2", "gap-6");
    }
    if (agentPanel) agentPanel.classList.remove("hidden");
  } else {
    _AGENT_MAIN_FILL.forEach((c) => appMain?.classList.remove(c));
    _AGENT_PAGE_INTRO_SHRINK.forEach((c) => pageIntro?.classList.remove(c));
    _AGENT_CHAT_GROW.forEach((c) => agentPanel?.classList.remove(c));
    if (topRow) {
      topRow.classList.remove("hidden");
      topRow.classList.add("grid", "lg:grid-cols-2", "gap-6");
    }
    if (agentPanel) agentPanel.classList.add("hidden");
  }

  for (const el of document.querySelectorAll(".tab-dashboard-only")) {
    if (tab === "agent") el.classList.add("hidden");
    else el.classList.remove("hidden");
  }

  if (title) title.textContent = tab === "agent" ? "Talk to agent" : "Dashboard";
  if (sub) {
    sub.textContent =
      tab === "agent"
        ? "Chat about the run you just optimized—trade-offs like moving the window earlier—and get answers grounded in your timeline data when the agent is connected."
        : "Pick a job, see the cleanest run window, and read why.";
  }

  const active = "px-3 py-1.5 rounded-full text-xs sm:text-sm font-semibold bg-ink text-white";
  const idle =
    "px-3 py-1.5 rounded-full text-xs sm:text-sm font-semibold text-slate-600 hover:text-ink hover:bg-slate-50";
  if (bd) bd.className = tab === "dashboard" ? active : idle;
  if (ba) ba.className = tab === "agent" ? active : idle;

  const url = new URL(window.location.href);
  url.searchParams.set("tab", tab);
  if (push) window.history.pushState({ tab }, "", url.toString());
  else window.history.replaceState({ tab }, "", url.toString());

  if (tab === "agent") ensureAgentWelcome();

  if (CHART && tab === "dashboard") {
    requestAnimationFrame(() => {
      try {
        CHART.resize();
      } catch {
        /* ignore */
      }
    });
  }
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

// Two-row "Baseline / Recommended window" header above the Gemma prose.
// Sourced from opt.baseline / opt.optimized so it always agrees with
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
    ? "Same as baseline — no cleaner slot in this search range"
    : formatHumanWindow(o.start, o.end);

  const labelCls = "text-ink2 font-medium";
  const valueCls = "text-slate-800";
  const optimisedValueCls = sameWindow ? "text-slate-500 italic" : valueCls;

  block.innerHTML =
    `<div class="${labelCls}">Baseline (if you ran ASAP)</div>` +
    `<div class="${valueCls}">${originalStr}</div>` +
    `<div class="${labelCls}">Recommended window</div>` +
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
  const base = {
    region: $("region").value,
    job_name: $("jobName").value || "job",
    duration_hours: Math.max(1, Math.round(Number($("durationHours").value) || 1)),
    start_after: localToUtcIso($("startAfter").value),
    deadline: localToUtcIso($("deadline").value),
  };
  const inst = $("instancePreset") && $("instancePreset").value;
  if (inst === "__custom__") {
    base.power_kw = Number($("powerKw").value) || 1;
  } else if (inst) {
    base.instance_type = inst;
    base.power_kw = null;
  } else {
    base.power_kw = Number($("powerKw").value) || 1;
  }
  return base;
}

function effectivePowerKwFromPayload(payload) {
  if (payload.instance_type != null && payload.instance_type !== "") {
    const p = instancePowerKwByName[payload.instance_type];
    if (p != null) return Number(p);
  }
  return Number(payload.power_kw) || 1;
}

// Build a smart mock result from whatever the user entered in the form.
// This lets the demo "work" with any inputs while backend is offline.
function buildSmartMock(payload) {
  const startAfter = new Date(payload.start_after || "2026-04-25T18:00:00Z");
  const deadline   = new Date(payload.deadline   || "2026-04-26T08:00:00Z");
  const durH       = Number(payload.duration_hours) || 4;
  const powerKw    = effectivePowerKwFromPayload(payload);

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

/** Short hedged “why” lines for demo /explain when the agent is offline (not sent to Gemma). */
const DEMO_REGION_WHY = {
  "US-CAL-CISO":
    "California often sees solar-rich midday and steeper emissions when gas peakers and imports ramp after sunset, so evening and overnight buckets can carry more carbon than afternoon shoulder hours.",
  "US-TEX-ERCO":
    "ERCOT frequently has strong overnight wind while daytime demand pulls on gas, which can make late-afternoon slices dirtier than the small hours.",
  "US-MIDA-PJM":
    "PJM spans many plants and ties; hourly carbon often tracks demand peaks and whichever marginal units are setting the tone that hour.",
  "US-MIDW-MISO":
    "MISO shows similar demand-driven swings across coal, gas, and wind in the Midwest footprint.",
  "US-NW-PACW":
    "The Pacific Northwest mixes hydro with regional thermal resources; the hourly curve still shifts with river conditions and load.",
  IN: "Country-level India averages many states; intensity often tracks evening load when thermal plants carry more marginal generation.",
  "IN-NO": "Northern India often peaks on hot afternoons and evenings when cooling and industry load are high.",
  "IN-SO": "Southern India shows a similar demand-driven ramp, with late night often calmer than early evening.",
  "AU-NSW":
    "NSW can show strong solar midday with higher marginal emissions in the early evening when gas turbines pick up.",
  DE: "Germany couples large wind and solar with thermal reserves; the curve reflects when renewables are scarce versus abundant.",
  FR: "France is nuclear-heavy, so the signal is usually flatter — small shifts here are often about demand and imports, not a dramatic fuel swap.",
};

function buildSmartExplain(opt) {
  const m = opt.metrics || {};
  const b = opt.baseline || {};
  const o = opt.optimized || {};
  const r = opt.reasoning || {};
  const req = opt.request || {};
  const pct = (m.percent_reduction ?? 0).toFixed(1);
  const kg = (m.co2_saved_kg ?? 0).toFixed(1);
  const bAvg = r.baseline_avg_signal;
  const oAvg = r.optimized_avg_signal;
  const region = req.region || "this grid";
  const saved = Number(m.co2_saved_kg) || 0;
  const sameWindow = b.start === o.start && b.end === o.end;

  if (sameWindow || saved <= 0) {
    return {
      text_explanation:
        `Across ${region}, the carbon-intensity curve in your search window does not contain a cleaner contiguous run than starting at the earliest allowed time, ` +
        `so the optimizer keeps the baseline window. ` +
        `Typical averages sit near ${bAvg ?? "—"} gCO₂e/kWh here — widening the deadline or choosing a zone with a wider daily swing usually unlocks more flexibility.`,
    };
  }

  const dirty = (r.dirtiest_hours_avoided || []).slice(0, 6).join(", ");
  const clean = (r.cleaner_hours_used || []).slice(0, 6).join(", ");
  const dataSentence =
    dirty || clean
      ? `The schedule moves work away from the highest-carbon UTC hours flagged in this run (${dirty || "n/a"}) and into cleaner buckets (${clean || "n/a"}). `
      : "The schedule targets a contiguous slice whose average carbon is lower than starting immediately. ";

  const why =
    DEMO_REGION_WHY[region] ||
    `For ${region}, the demo curve suggests those hours simply carry a lower marginal emissions factor than the baseline slice. `;

  return {
    text_explanation:
      `${dataSentence}` +
      `${why} ` +
      `Average grid carbon goes from ${bAvg ?? "—"} to ${oAvg ?? "—"} gCO₂e/kWh, saving ${kg} kg CO₂ — a ${pct}% improvement for this job length and power draw. ` +
      `Same workload; the win is timing the draw when the grid is less carbon-intense.`,
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

function syncCustomPowerVisibility() {
  const wrap = $("customPowerWrap");
  const sel = $("instancePreset");
  if (!wrap || !sel) return;
  if (sel.value === "__custom__") wrap.classList.remove("hidden");
  else wrap.classList.add("hidden");
}

function onWorkloadChange() {
  const w = $("workloadPreset").value;
  const h = WORKLOAD_DEFAULT_HOURS[w] ?? 4;
  $("durationHours").value = String(h);
}

function onInstanceChange() {
  syncCustomPowerVisibility();
}

async function callInstanceTypes() {
  const s = loadSettings();
  if (!s.backendUrl) return null;
  try {
    const url = `${s.backendUrl.replace(/\/$/, "")}/instance-types`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return Array.isArray(data.instance_types) && data.instance_types.length ? data.instance_types : null;
  } catch (e) {
    console.warn("instance-types failed", e);
    return null;
  }
}

async function refreshInstanceTypes() {
  const sel = $("instancePreset");
  if (!sel) return;

  const previous = sel.value;
  let items = await callInstanceTypes();
  if (!items) items = FALLBACK_INSTANCE_TYPES_LIST.slice();

  instancePowerKwByName = {};
  for (const it of items) instancePowerKwByName[it.name] = it.power_kw;

  const customOpt = document.createElement("option");
  customOpt.value = "__custom__";
  customOpt.textContent = "Custom (enter kW)";

  sel.innerHTML = "";
  sel.appendChild(customOpt);

  const presetSet = new Set(DASHBOARD_PRESET_ORDER);
  for (const name of DASHBOARD_PRESET_ORDER) {
    const it = items.find((x) => x.name === name);
    if (!it) continue;
    const opt = document.createElement("option");
    opt.value = it.name;
    opt.textContent = it.label;
    sel.appendChild(opt);
  }

  const legacy = items
    .filter((it) => !presetSet.has(it.name))
    .sort((a, b) => a.name.localeCompare(b.name));
  if (legacy.length) {
    const og = document.createElement("optgroup");
    og.label = "Advanced (legacy SKUs)";
    for (const it of legacy) {
      const opt = document.createElement("option");
      opt.value = it.name;
      opt.textContent = it.label;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }

  const prefer = "preset.a100_node8";
  if (previous && previous !== "__custom__" && [...sel.options].some((o) => o.value === previous)) {
    sel.value = previous;
  } else if ([...sel.options].some((o) => o.value === prefer)) {
    sel.value = prefer;
  }
  syncCustomPowerVisibility();
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

/** Ballpark fun lines when the agent is offline (aligned with agents/services/equivalency_service.py). */
function localFunEquivalencies(opt) {
  const kg = Number(opt?.metrics?.co2_saved_kg);
  const x = Number.isFinite(kg) ? kg : 0;
  if (x <= 0) {
    return [
      "This run did not beat the baseline on CO₂ — try widening the deadline or another zone.",
      "No extra fun savings to show until the optimizer finds a cleaner window.",
      "Same job; timing did not land on a lower-carbon slice this time.",
    ];
  }
  const miles = Math.max(1, x / 0.35);
  const phones = Math.max(10, Math.round(x / 0.034));
  const weeks = Math.max(0.5, x / (0.025 * 0.42 * 24 * 7));
  return [
    `Roughly enough avoided CO₂ as skipping ~${miles.toFixed(0)} miles of average car driving (ballpark).`,
    `About the same order of magnitude as ~${phones} smartphone full charges from the grid (illustrative).`,
    `In the ballpark of running a modest laptop (~25 W) for ~${weeks.toFixed(1)} weeks at a typical grid factor — not exact science.`,
  ];
}

function setFunEquivLoading() {
  const ul = $("funEquivList");
  if (!ul) return;
  ul.innerHTML = "";
  const li = document.createElement("li");
  li.className = "text-sm text-slate-500";
  li.textContent = "Generating fun equivalencies…";
  ul.appendChild(li);
}

function renderFunEquivs(lines) {
  const ul = $("funEquivList");
  if (!ul) return;
  ul.innerHTML = "";
  const arr = Array.isArray(lines) ? lines : [];
  const three = arr.slice(0, 3);
  while (three.length < 3) three.push("Illustrative comparison — connect the agent for AI-phrased lines.");
  for (const line of three) {
    const li = document.createElement("li");
    li.className = "flex gap-3 items-start";
    const dot = document.createElement("span");
    dot.className = "text-teal-600 font-bold shrink-0 select-none";
    dot.textContent = "•";
    const span = document.createElement("span");
    span.className = "text-[15px] leading-snug text-slate-800";
    span.textContent = line;
    li.appendChild(dot);
    li.appendChild(span);
    ul.appendChild(li);
  }
}

async function callEquivalencies(opt) {
  const s = loadSettings();
  const useBackend = !!s.backendUrl;
  const base = useBackend ? s.backendUrl.replace(/\/$/, "") : (s.agentUrl || "").replace(/\/$/, "");
  if (!base) {
    renderFunEquivs(localFunEquivalencies(opt));
    return;
  }
  try {
    const res = await fetch(`${base}/equivalencies`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(opt),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const arr = Array.isArray(data.equivalencies) ? data.equivalencies.map((x) => String(x || "").trim()).filter(Boolean) : [];
    if (arr.length >= 3) renderFunEquivs(arr);
    else renderFunEquivs(localFunEquivalencies(opt));
  } catch (e) {
    console.warn("equivalencies failed", e);
    renderFunEquivs(localFunEquivalencies(opt));
  }
}

async function onOptimize() {
  const opt = await callOptimize();
  renderOptimize(opt);
  persistLastRun(opt);

  // Auto-explain + fun equivalencies in parallel (both POST the same OptimizeResponse).
  setFunEquivLoading();
  await Promise.all([onExplain(), callEquivalencies(opt)]);
  maybeAppendAgentRunSummary(opt);
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
  const d = $("drawer");
  if (!d) return;
  d.classList.remove("hidden");
  const s = loadSettings();
  const bu = $("backendUrl");
  const au = $("agentUrl");
  const ia = $("includeAudio");
  if (bu) bu.value = s.backendUrl ?? "";
  if (au) au.value = s.agentUrl ?? "";
  if (ia) ia.checked = !!s.includeAudio;
}

function closeDrawer() {
  const d = $("drawer");
  if (d) d.classList.add("hidden");
}

/** If URL contains `?settings=1`, open Connect data once then remove the param. */
function consumeOpenSettingsParam() {
  try {
    const u = new URL(window.location.href);
    if (u.searchParams.get("settings") !== "1") return;
    u.searchParams.delete("settings");
    window.history.replaceState({}, "", u.toString());
    openDrawer();
  } catch {
    /* ignore */
  }
}

function bind() {
  $("optimizeBtn").addEventListener("click", onOptimize);

  const connectBtn = $("connectDataBtn");
  if (connectBtn) connectBtn.addEventListener("click", openDrawer);
  const closeD = $("closeDrawer");
  if (closeD) closeD.addEventListener("click", closeDrawer);
  const backdrop = $("drawerBackdrop");
  if (backdrop) backdrop.addEventListener("click", closeDrawer);

  const saveBtn = $("saveSettings");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      saveSettings({
        backendUrl: $("backendUrl").value.trim(),
        agentUrl: $("agentUrl").value.trim(),
        includeAudio: !!$("includeAudio").checked,
      });
      updateModeBadge();
      closeDrawer();
      await refreshRegions();
      await refreshInstanceTypes();
    });
  }
  const resetBtn = $("resetSettings");
  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      saveSettings({ backendUrl: "", agentUrl: "", includeAudio: false });
      updateModeBadge();
      const bu = $("backendUrl");
      const au = $("agentUrl");
      const ia = $("includeAudio");
      if (bu) bu.value = "";
      if (au) au.value = "";
      if (ia) ia.checked = false;
      closeDrawer();
      await refreshRegions();
      await refreshInstanceTypes();
    });
  }

  const bd = $("tabBtnDashboard");
  const ba = $("tabBtnAgent");
  if (bd) bd.addEventListener("click", () => setAppTab("dashboard", { push: true }));
  if (ba) ba.addEventListener("click", () => setAppTab("agent", { push: true }));

  const wp = $("workloadPreset");
  if (wp) wp.addEventListener("change", onWorkloadChange);
  const ip = $("instancePreset");
  if (ip) ip.addEventListener("change", onInstanceChange);
}

window.addEventListener("popstate", () => {
  setAppTab(getTabFromUrl(), { push: false });
});

document.addEventListener("DOMContentLoaded", async () => {
  bind();
  bindAgentChatUi();
  consumeOpenSettingsParam();
  setAppTab(getTabFromUrl(), { push: false });
  updateModeBadge();
  // No on-load mock render — the result/chart/explain cards keep their static
  // empty-state copy from app.html until the user clicks "Optimize schedule".
  await refreshInstanceTypes();
  await refreshRegions();
});
