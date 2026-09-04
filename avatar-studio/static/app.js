/* Avatar Studio — frontend glue */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { jobId: null, pollTimer: null, active: false, history: [] };

/* ---------- tiny helpers ---------- */
function showStage(name) {
  ["idle", "busy", "done", "failed"].forEach((n) =>
    $(`stage-${n}`).classList.toggle("hidden", n !== name));
}
function showBanner(msg, kind) {
  const b = $("banner");
  b.textContent = msg;
  b.className = `banner ${kind}`;
}
function hideBanner() { $("banner").className = "banner hidden"; }

const SAMPLE =
  "Hello! I'm your AI presenter. Everything I say here is generated from " +
  "text — my lips move in real sync with these words, thanks to a " +
  "photo-realistic talking head engine. Type your own script and I'll say " +
  "it for you.";

/* ---------- init ---------- */
async function init() {
  $("sample").addEventListener("click", () => {
    $("text").value = SAMPLE;
    updateCount();
  });
  $("text").addEventListener("input", updateCount);
  $("generate").addEventListener("click", generate);
  $("again").addEventListener("click", () => {
    clearPoll();
    showStage("idle");
  });

  const txt = $("text");
  txt.value = SAMPLE;
  updateCount();

  await loadVoices();
  await health();
  await loadHistory();
}

function fileNameFor(text) {
  const slug = text.toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48)
    .replace(/-+$/g, "");
  return `${slug ? `avatar-${slug}` : "avatar"}.mp4`;
}

function updateCount() {
  $("chars").textContent = $("text").value.length;
}

async function health() {
  try {
    const h = await (await fetch("/api/health")).json();
    const pill = $("engine-pill");
    pill.classList.toggle("ok", h.engine_ready);
    pill.classList.toggle("bad", !h.engine_ready);
    pill.textContent = h.engine_ready
      ? `${h.engine}: ready`
      : `${h.engine}: setup needed`;
    $("text").maxLength = h.max_text;           // server owns the limit
    $("max-chars").textContent = h.max_text;
    if (!h.engine_ready && h.engine_hint) {
      showBanner(h.engine_hint, "warn");
    } else {
      hideBanner();
    }
  } catch {
    $("engine-pill").textContent = "server offline?";
  }
}

/* Finished renders survive server restarts — rebuild the gallery from them. */
async function loadHistory() {
  try {
    const list = await (await fetch("/api/history")).json();
    if (!list.length) return;
    state.history = list.map((j) => ({ url: j.video_url, text: j.text, voice: j.voice }));
    renderHistory();
  } catch {
    /* the gallery is optional; never block the page on it */
  }
}

async function loadVoices() {
  const list = await (await fetch("/api/voices")).json();
  const sel = $("voice");
  sel.innerHTML = "";
  list.forEach((v, i) => {
    const opt = document.createElement("option");
    opt.value = v.id;
    opt.textContent = `${v.label} — ${v.language} (${v.gender})`;
    if (i === 0) opt.selected = true;
    sel.appendChild(opt);
  });
}

/* ---------- render job ---------- */
async function generate() {
  const text = $("text").value.trim();
  if (!text) {
    showBanner("Write something for the avatar to say first.", "err");
    return;
  }
  hideBanner();
  clearPoll();

  $("generate").disabled = true;
  $("generate").textContent = "Working…";
  state.active = true;

  const voice = $("voice").value;

  let res;
  try {
    res = await fetch("/api/render", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, voice }),
    });
  } catch {
    fail("Could not reach the server. Is it running?");
    return;
  }

  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    fail(body.detail || `Server error ${res.status}`);
    return;
  }
  state.jobId = body.job_id;
  showStage("busy");
  setStageLabel("Generating neural speech…");
  pollJob();
}

function clearPoll() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = null;
  state.jobId = null;
  $("generate").disabled = false;
  $("generate").textContent = "✨ Generate avatar video";
  state.active = false;
}

function setStageLabel(t) { $("stage-label").textContent = t; }

async function pollJob() {
  if (!state.jobId) return;
  let res, job;
  try {
    res = await fetch(`/api/jobs/${state.jobId}`);
    job = await res.json();
  } catch {
    setStageLabel("Lost contact with the server — retrying…");
    state.pollTimer = setTimeout(pollJob, 3000);
    return;
  }

  if (!res.ok || !job.id) {
    // Unknown job: started before a restart, or already evicted.
    fail("This render started before the server restarted, so it is no " +
      "longer tracked. Click Generate again.");
    return;
  }

  if (job.status === "tts" || job.status === "rendering") {
    setStageLabel(job.message || "Working…");
    state.pollTimer = setTimeout(pollJob, 1500);
    return;
  }

  if (job.status === "succeeded") {
    finishOk(job);
    return;
  }
  fail(job.error || "The render failed.");
}

function finishOk(job) {
  clearPoll();
  showStage("done");
  $("player").src = job.video_url;
  $("download").href = job.video_url;
  $("download").setAttribute("download", fileNameFor(job.text));
  pushHistory(job);
}

function fail(message) {
  clearPoll();
  showStage("failed");
  $("error-text").textContent = message;
}

/* ---------- history ---------- */
function pushHistory(job) {
  state.history.unshift({
    url: job.video_url,
    text: job.text,
    voice: job.voice,
  });
  if (state.history.length > 6) state.history.length = 6;
  renderHistory();
}

function renderHistory() {
  const sec = $("history");
  sec.classList.remove("hidden");
  const grid = $("history-grid");
  grid.innerHTML = "";
  state.history.forEach((h) => {
    const item = document.createElement("div");
    item.className = "history-item";
    item.addEventListener("click", () => {
      $("player").src = h.url;
      showStage("done");
      $("download").href = h.url;
      $("download").setAttribute("download", fileNameFor(h.text));
    });
    const vid = document.createElement("video");
    vid.src = h.url;
    vid.muted = true;
    vid.preload = "metadata";
    const t = document.createElement("div");
    t.className = "htext";
    t.textContent = h.text;
    item.append(vid, t);
    grid.appendChild(item);
  });
}

init();
