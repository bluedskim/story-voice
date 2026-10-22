const listEl = document.getElementById("story-list");
const audio = document.getElementById("player");
const genStatusEl = document.getElementById("gen-status");
const genStatusTextEl = document.getElementById("gen-status-text");
const genProgressEl = document.getElementById("gen-progress");
const genProgressBarEl = document.getElementById("gen-progress-bar");
const regenAllBtn = document.getElementById("regen-all");

const recordScriptEl = document.getElementById("record-script");
const transcriptEl = document.getElementById("transcript");
const recordBtn = document.getElementById("record-btn");
const stopBtn = document.getElementById("stop-btn");
const fileInput = document.getElementById("file-input");
const previewEl = document.getElementById("preview");
const previewPlayerUi = document.getElementById("preview-player-ui");
const previewPlayBtn = document.getElementById("preview-play");
const previewTimeEl = document.getElementById("preview-time");
const prepareVoiceBtn = document.getElementById("prepare-voice");
const saveVoiceBtn = document.getElementById("save-voice");
const voiceMsgEl = document.getElementById("voice-msg");
const voiceReviewEl = document.getElementById("voice-review");
const voiceMetaEl = document.getElementById("voice-meta");
const voiceMatchEl = document.getElementById("voice-match");
const matchRingEl = document.getElementById("match-ring");
const matchTextEl = document.getElementById("match-text");
const voiceSteps = document.querySelectorAll(".voice-step");

const nowPlayingEl = document.getElementById("now-playing");
const npTitleEl = document.getElementById("np-title");
const npArtEl = document.getElementById("np-art");
const npCurrentEl = document.getElementById("np-current");
const npDurationEl = document.getElementById("np-duration");
const npSeekEl = document.getElementById("np-seek");
const npPlayBtn = document.getElementById("np-play");

const STORY_MOTIFS = {
  "ui-joeun-hyeongje": "🌾",
  "san-gol-halmeoni-gage": "🏡",
  "bambyeol-ui-norae": "⭐",
};

let catalog = [];
let activeId = null;
let activeStory = null;
let audioCacheBust = Date.now();
let pollTimer = null;
let durationCache = {};
let generationBusy = false;
let seekDragging = false;

let mediaRecorder = null;
let recordChunks = [];
let pendingBlob = null;
let pendingToken = null;

function motifFor(id) {
  return STORY_MOTIFS[id] || "📖";
}

function formatTime(sec) {
  if (!Number.isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function playIcon(playing) {
  return playing ? "⏸" : "▶";
}

function setStatus(card, message) {
  const el = card.querySelector(".story-status");
  if (el) el.textContent = message;
}

function storyAudioUrl(story) {
  if (!story.audioUrl) return null;
  const base = story.audioUrl.split("?")[0];
  return `${base}?v=${audioCacheBust}`;
}

function setVoiceStep(step) {
  voiceSteps.forEach((el) => {
    const n = Number(el.dataset.step);
    el.classList.toggle("is-active", n === step);
    el.classList.toggle("is-done", n < step);
  });
}

function setAppBusy(busy) {
  generationBusy = busy;
  document.body.classList.toggle("is-app-busy", busy);
  if (busy) {
    prepareVoiceBtn.disabled = true;
    recordBtn.disabled = true;
    stopBtn.disabled = true;
  } else if (!mediaRecorder || mediaRecorder.state === "inactive") {
    recordBtn.disabled = false;
    stopBtn.disabled = true;
    if (pendingBlob) prepareVoiceBtn.disabled = false;
  }
}

async function loadConfig() {
  const res = await fetch("/api/config", { cache: "no-store" });
  if (!res.ok) throw new Error("config");
  const data = await res.json();
  recordScriptEl.value = data.recordScript || "";
}

function probeDuration(story) {
  if (!story.hasAudio || durationCache[story.id]) return;
  const url = storyAudioUrl(story);
  if (!url) return;
  const probe = new Audio();
  probe.preload = "metadata";
  probe.src = url;
  probe.addEventListener(
    "loadedmetadata",
    () => {
      if (Number.isFinite(probe.duration)) {
        durationCache[story.id] = probe.duration;
        const el = document.querySelector(`.story-duration[data-id="${story.id}"]`);
        if (el) el.textContent = formatTime(probe.duration);
      }
    },
    { once: true }
  );
}

async function loadCatalog() {
  listEl.innerHTML = '<p class="loading">이야기를 불러오는 중…</p>';
  try {
    const res = await fetch("catalog.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`catalog.json ${res.status}`);
    const data = await res.json();
    catalog = data.stories || [];
    render();
    catalog.forEach(probeDuration);
  } catch (err) {
    listEl.innerHTML = `<p class="error">목록을 불러오지 못했어요.<br><small>${err.message}</small></p>`;
  }
}

function render() {
  listEl.innerHTML = "";
  for (const story of catalog) {
    const card = document.createElement("article");
    card.className = "story-card";
    card.dataset.id = story.id;
    if (!story.hasAudio) card.classList.add("is-missing");

    const motif = document.createElement("div");
    motif.className = "story-motif";
    motif.setAttribute("aria-hidden", "true");
    motif.textContent = motifFor(story.id);

    const main = document.createElement("div");
    main.className = "story-main";

    const title = document.createElement("h2");
    title.className = "story-title";
    title.textContent = story.title;

    const meta = document.createElement("p");
    meta.className = "story-meta";
    const badge = document.createElement("span");
    badge.className = "story-badge";
    badge.textContent = story.hasAudio ? "듣을 수 있어요" : "만들기 전";
    const dur = document.createElement("span");
    dur.className = "story-duration";
    dur.dataset.id = story.id;
    dur.textContent = durationCache[story.id] ? formatTime(durationCache[story.id]) : "—:—";
    meta.append(badge, dur);

    const status = document.createElement("p");
    status.className = "story-status";
    status.textContent = story.hasAudio ? "재생할 준비됐어요" : "목소리 저장 후 만들어 주세요";

    const regen = document.createElement("button");
    regen.type = "button";
    regen.className = "btn btn-secondary regen-btn";
    regen.textContent = "다시 만들기";
    regen.addEventListener("click", () => enqueueStory(story.id));

    const actions = document.createElement("div");
    actions.className = "story-actions";
    actions.append(regen);

    if (story.hasAudio && story.audioUrl) {
      const download = document.createElement("a");
      download.className = "btn btn-secondary regen-btn";
      download.href = `${story.audioUrl.split("?")[0]}?download=1`;
      download.textContent = "다운로드";
      download.setAttribute("aria-label", `${story.title} 오디오 다운로드`);
      actions.append(download);
    }

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "toggle-text";
    toggle.textContent = "글 보기";
    toggle.setAttribute("aria-expanded", "false");

    const text = document.createElement("div");
    text.className = "story-text";
    text.textContent = story.text || "";
    text.id = `story-text-${story.id}`;

    toggle.addEventListener("click", () => {
      const open = text.classList.toggle("is-open");
      toggle.textContent = open ? "글 숨기기" : "글 보기";
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "play-btn";
    btn.setAttribute("aria-label", story.hasAudio ? `${story.title} 재생` : "오디오 없음");
    btn.disabled = !story.hasAudio;
    btn.textContent = playIcon(false);
    btn.addEventListener("click", () => togglePlayback(story, card, btn));

    main.append(title, meta, status, actions, toggle, text);
    card.append(motif, main, btn);
    listEl.appendChild(card);
  }
}

function showNowPlaying(story) {
  nowPlayingEl.hidden = false;
  npTitleEl.textContent = story.title;
  npArtEl.textContent = motifFor(story.id);
}

function syncNowPlayingUi() {
  if (!activeStory) return;
  npCurrentEl.textContent = formatTime(audio.currentTime);
  const dur = Number.isFinite(audio.duration) ? audio.duration : 0;
  npDurationEl.textContent = formatTime(dur);
  if (!seekDragging && dur > 0) {
    npSeekEl.value = String(Math.round((audio.currentTime / dur) * 1000));
  }
  npPlayBtn.textContent = playIcon(!audio.paused);
  document.querySelectorAll(".play-btn").forEach((b) => {
    const card = b.closest(".story-card");
    if (!card) return;
    const isActive = card.dataset.id === activeId;
    b.textContent = playIcon(isActive && !audio.paused);
  });
}

function togglePlayback(story, card, btn) {
  const url = storyAudioUrl(story);
  if (!url) return;

  if (activeId === story.id && !audio.paused) {
    audio.pause();
    card.classList.remove("is-active");
    setStatus(card, "일시정지");
    syncNowPlayingUi();
    return;
  }

  document.querySelectorAll(".story-card").forEach((c) => {
    c.classList.remove("is-active");
  });

  activeId = story.id;
  activeStory = story;
  card.classList.add("is-active");
  const nextSrc = new URL(url, location.href).href;
  if (audio.src !== nextSrc) {
    audio.src = url;
  }
  showNowPlaying(story);
  audio.play().catch(() => setStatus(card, "재생할 수 없어요"));
  setStatus(card, "재생 중…");
  syncNowPlayingUi();
}

audio.addEventListener("timeupdate", syncNowPlayingUi);
audio.addEventListener("loadedmetadata", syncNowPlayingUi);
audio.addEventListener("ended", () => {
  const card = document.querySelector(`.story-card[data-id="${activeId}"]`);
  if (card) {
    setStatus(card, "끝났어요. 좋은 꿈 꾸세요.");
    card.classList.remove("is-active");
  }
  syncNowPlayingUi();
});

audio.addEventListener("pause", () => {
  if (audio.ended) return;
  syncNowPlayingUi();
});

npPlayBtn.addEventListener("click", () => {
  if (!activeStory) return;
  if (audio.paused) {
    audio.play();
  } else {
    audio.pause();
  }
  syncNowPlayingUi();
});

npSeekEl.addEventListener("input", () => {
  seekDragging = true;
  const dur = audio.duration;
  if (!Number.isFinite(dur)) return;
  const t = (Number(npSeekEl.value) / 1000) * dur;
  npCurrentEl.textContent = formatTime(t);
});

npSeekEl.addEventListener("change", () => {
  const dur = audio.duration;
  if (Number.isFinite(dur)) {
    audio.currentTime = (Number(npSeekEl.value) / 1000) * dur;
  }
  seekDragging = false;
  syncNowPlayingUi();
});

async function enqueueStory(id) {
  const res = await fetch(`/api/generation/story/${id}`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showGenStatus(data.error || "요청하지 못했어요.", true);
    return;
  }
  showGenStatus("이야기를 만드는 중…");
  startPolling();
}

async function enqueueAll() {
  const res = await fetch("/api/generation/all", { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showGenStatus(data.error || "요청하지 못했어요.", true);
    return;
  }
  showGenStatus("전체 이야기를 만드는 중…");
  startPolling();
}

function showGenStatus(text, isError = false, progress = null) {
  genStatusEl.hidden = !text;
  genStatusTextEl.textContent = text;
  genStatusEl.classList.toggle("is-error", isError);
  genStatusEl.classList.toggle("is-busy", Boolean(progress));
  if (progress && progress.total > 0) {
    genProgressEl.hidden = false;
    const pct = Math.min(100, Math.round((progress.current / progress.total) * 100));
    genProgressBarEl.style.width = `${pct}%`;
  } else {
    genProgressEl.hidden = true;
    genProgressBarEl.style.width = "0%";
  }
}

async function pollGeneration() {
  const res = await fetch("/api/generation/status", { cache: "no-store" });
  if (!res.ok) return;
  const data = await res.json();
  const running = data.running;
  if (running) {
    setAppBusy(true);
    const chunk =
      running.chunkTotal > 0
        ? ` · ${running.chunkIndex}/${running.chunkTotal}번째`
        : "";
    const title =
      catalog.find((s) => s.id === running.currentStoryId)?.title || running.currentStoryId;
    showGenStatus(`만드는 중: ${title || "이야기"}${chunk}`, false, {
      current: running.chunkIndex || 0,
      total: running.chunkTotal || 1,
    });
    return;
  }
  if (data.queued?.length) {
    setAppBusy(true);
    showGenStatus(`대기 중… (${data.queued.length}개)`, false);
    return;
  }
  setAppBusy(false);
  const last = data.recent?.[0];
  if (last?.state === "failed") {
    showGenStatus(last.error || "실패했어요.", true);
    stopPolling();
    return;
  }
  if (last?.state === "done") {
    audioCacheBust = Date.now();
    showGenStatus("새 목소리로 만들었어요.");
    await loadCatalog();
    stopPolling();
    setTimeout(() => showGenStatus(""), 4000);
    return;
  }
  stopPolling();
  showGenStatus("");
}

function startPolling() {
  if (pollTimer) return;
  pollTimer = setInterval(pollGeneration, 1500);
  pollGeneration();
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
  setAppBusy(false);
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => {
        const on = t === tab;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      document.getElementById("panel-stories").hidden = name !== "stories";
      document.getElementById("panel-voice").hidden = name !== "voice";
    });
  });
}

function pickRecorderMime() {
  const types = ["audio/mp4", "audio/aac", "audio/webm;codecs=opus", "audio/webm"];
  return types.find((t) => MediaRecorder.isTypeSupported(t)) || "";
}

function resetVoiceReview() {
  pendingToken = null;
  voiceReviewEl.hidden = true;
  transcriptEl.value = "";
  voiceMetaEl.textContent = "";
  matchTextEl.textContent = "";
  matchRingEl.style.setProperty("--pct", "0%");
  matchRingEl.dataset.label = "";
  voiceMatchEl.classList.remove("is-warn");
  setVoiceStep(1);
}

function onAudioReady() {
  if (!generationBusy) prepareVoiceBtn.disabled = false;
  resetVoiceReview();
  previewPlayerUi.hidden = false;
  voiceMsgEl.textContent = "미리 듣고 ‘받아쓰기 확인’을 눌러 주세요.";
  voiceMsgEl.className = "voice-msg";
  setVoiceStep(1);
}

async function startRecording() {
  voiceMsgEl.textContent = "";
  voiceMsgEl.className = "voice-msg";
  resetVoiceReview();
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const mime = pickRecorderMime();
  recordChunks = [];
  mediaRecorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
  mediaRecorder.ondataavailable = (e) => {
    if (e.data.size) recordChunks.push(e.data);
  };
  mediaRecorder.onstop = () => {
    stream.getTracks().forEach((t) => t.stop());
    const type = mediaRecorder.mimeType || "audio/mp4";
    pendingBlob = new Blob(recordChunks, { type });
    previewEl.src = URL.createObjectURL(pendingBlob);
    onAudioReady();
  };
  mediaRecorder.start();
  recordBtn.disabled = true;
  stopBtn.disabled = false;
  voiceMsgEl.textContent = "녹음 중…";
  setVoiceStep(1);
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  recordBtn.disabled = generationBusy;
  stopBtn.disabled = true;
}

function onFileSelected(file) {
  if (!file) return;
  pendingBlob = file;
  previewEl.src = URL.createObjectURL(file);
  onAudioReady();
  voiceMsgEl.textContent = `${file.name} — 미리 듣고 ‘받아쓰기 확인’을 눌러 주세요.`;
}

previewPlayBtn.addEventListener("click", () => {
  if (!previewEl.src) return;
  if (previewEl.paused) previewEl.play();
  else previewEl.pause();
  previewPlayBtn.textContent = playIcon(!previewEl.paused);
});

previewEl.addEventListener("timeupdate", () => {
  previewTimeEl.textContent = formatTime(previewEl.currentTime);
});

function voiceFormData() {
  const form = new FormData();
  const ext = pendingBlob.type.includes("mp4") ? "recording.m4a" : "recording.webm";
  form.append("audio", pendingBlob, ext);
  return form;
}

async function prepareVoice() {
  if (!pendingBlob || generationBusy) return;
  prepareVoiceBtn.disabled = true;
  voiceMsgEl.textContent = "받아쓰는 중… (잠시만요)";
  voiceMsgEl.className = "voice-msg";
  const res = await fetch("/api/voice/prepare", { method: "POST", body: voiceFormData() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    voiceMsgEl.textContent = data.error || "받아쓰기에 실패했어요.";
    voiceMsgEl.className = "voice-msg is-error";
    if (!generationBusy) prepareVoiceBtn.disabled = false;
    return;
  }
  pendingToken = data.pendingToken;
  transcriptEl.value = data.transcript || "";
  voiceMetaEl.textContent = `녹음 ${data.durationSec}초 · 이 길이에는 보통 ${data.limits?.maxCharsForDuration ?? "?"}자 이하`;
  const pct = data.scriptMatchPercent ?? 0;
  matchRingEl.style.setProperty("--pct", `${pct}%`);
  matchRingEl.dataset.label = `${pct}`;
  matchTextEl.textContent = `대본 일치 약 ${pct}% (자동 받아쓰기 vs 녹음 대본)`;
  voiceMatchEl.classList.toggle("is-warn", pct < 70);
  voiceReviewEl.hidden = false;
  voiceMsgEl.textContent = "받아쓰기를 확인하고 필요하면 고친 뒤 저장해 주세요.";
  voiceMsgEl.className = "voice-msg";
  if (!generationBusy) prepareVoiceBtn.disabled = false;
  setVoiceStep(2);
}

async function saveVoice() {
  if (!pendingToken) {
    voiceMsgEl.textContent = "먼저 ‘받아쓰기 확인’을 해 주세요.";
    voiceMsgEl.className = "voice-msg is-error";
    return;
  }
  saveVoiceBtn.disabled = true;
  voiceMsgEl.textContent = "저장하는 중…";
  const res = await fetch("/api/voice/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pendingToken, transcript: transcriptEl.value }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    voiceMsgEl.textContent = data.error || "저장하지 못했어요.";
    voiceMsgEl.className = "voice-msg is-error";
    saveVoiceBtn.disabled = false;
    return;
  }
  let msg = `저장했어요 (${data.durationSec}초). 이야기를 다시 만들 수 있어요.`;
  voiceMsgEl.className = "voice-msg";
  if (data.editWarning) {
    msg += ` ${data.editWarning}`;
    voiceMsgEl.className = "voice-msg is-warn";
  }
  voiceMsgEl.textContent = msg;
  pendingBlob = null;
  pendingToken = null;
  prepareVoiceBtn.disabled = true;
  saveVoiceBtn.disabled = false;
  voiceReviewEl.hidden = true;
  previewPlayerUi.hidden = true;
  setVoiceStep(3);
}

recordBtn.addEventListener("click", () => {
  startRecording().catch(() => {
    voiceMsgEl.textContent = "마이크를 사용할 수 없어요.";
    voiceMsgEl.className = "voice-msg is-error";
  });
});
stopBtn.addEventListener("click", stopRecording);
fileInput.addEventListener("change", () => onFileSelected(fileInput.files?.[0]));
prepareVoiceBtn.addEventListener("click", prepareVoice);
saveVoiceBtn.addEventListener("click", saveVoice);
regenAllBtn.addEventListener("click", enqueueAll);

setupTabs();
if (location.hash === "#voice") {
  document.querySelector('.tab[data-tab="voice"]')?.click();
}
setVoiceStep(1);
loadConfig().catch(() => {});
loadCatalog();
pollGeneration();
