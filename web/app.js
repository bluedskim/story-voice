const listEl = document.getElementById("story-list");
const audio = document.getElementById("player");
const genStatusEl = document.getElementById("gen-status");
const regenAllBtn = document.getElementById("regen-all");

const recordScriptEl = document.getElementById("record-script");
const transcriptEl = document.getElementById("transcript");
const recordBtn = document.getElementById("record-btn");
const stopBtn = document.getElementById("stop-btn");
const fileInput = document.getElementById("file-input");
const previewEl = document.getElementById("preview");
const prepareVoiceBtn = document.getElementById("prepare-voice");
const saveVoiceBtn = document.getElementById("save-voice");
const voiceMsgEl = document.getElementById("voice-msg");
const voiceReviewEl = document.getElementById("voice-review");
const voiceMetaEl = document.getElementById("voice-meta");
const voiceMatchEl = document.getElementById("voice-match");

let catalog = [];
let activeId = null;
let audioCacheBust = Date.now();
let pollTimer = null;

let mediaRecorder = null;
let recordChunks = [];
let pendingBlob = null;
let pendingToken = null;

function icon(playing) {
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

async function loadConfig() {
  const res = await fetch("/api/config", { cache: "no-store" });
  if (!res.ok) throw new Error("config");
  const data = await res.json();
  recordScriptEl.value = data.recordScript || "";
}

async function loadCatalog() {
  listEl.innerHTML = '<p class="loading">이야기를 불러오는 중…</p>';
  try {
    const res = await fetch("catalog.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`catalog.json ${res.status}`);
    const data = await res.json();
    catalog = data.stories || [];
    render();
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

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "play-btn";
    btn.setAttribute("aria-label", story.hasAudio ? `${story.title} 재생` : "오디오 없음");
    btn.disabled = !story.hasAudio;
    btn.textContent = icon(false);

    const main = document.createElement("div");
    main.className = "story-main";

    const title = document.createElement("h2");
    title.className = "story-title";
    title.textContent = story.title;

    const status = document.createElement("p");
    status.className = "story-status";
    status.textContent = story.hasAudio ? "재생할 준비됐어요" : "아직 녹음이 없어요";

    const regen = document.createElement("button");
    regen.type = "button";
    regen.className = "btn-secondary regen-btn";
    regen.textContent = "다시 만들기";
    regen.addEventListener("click", () => enqueueStory(story.id));

    const actions = document.createElement("div");
    actions.className = "story-actions";
    actions.append(regen);

    if (story.hasAudio && story.audioUrl) {
      const download = document.createElement("a");
      download.className = "btn-secondary regen-btn";
      download.href = `${story.audioUrl.split("?")[0]}?download=1`;
      download.textContent = "다운로드";
      download.setAttribute("aria-label", `${story.title} 오디오 다운로드`);
      actions.append(download);
    }

    const toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "toggle-text";
    toggle.textContent = "글 보기";

    const text = document.createElement("div");
    text.className = "story-text";
    text.textContent = story.text || "";

    toggle.addEventListener("click", () => {
      const open = text.classList.toggle("is-open");
      toggle.textContent = open ? "글 숨기기" : "글 보기";
    });

    btn.addEventListener("click", () => togglePlayback(story, card, btn));

    main.append(title, status, actions, toggle, text);
    card.append(btn, main);
    listEl.appendChild(card);
  }
}

function togglePlayback(story, card, btn) {
  const url = storyAudioUrl(story);
  if (!url) return;

  if (activeId === story.id && !audio.paused) {
    audio.pause();
    btn.textContent = icon(false);
    card.classList.remove("is-active");
    setStatus(card, "일시정지");
    return;
  }

  document.querySelectorAll(".story-card").forEach((c) => {
    c.classList.remove("is-active");
    const b = c.querySelector(".play-btn");
    if (b) b.textContent = icon(false);
  });

  activeId = story.id;
  card.classList.add("is-active");
  const nextSrc = new URL(url, location.href).href;
  if (audio.src !== nextSrc) {
    audio.src = url;
  }
  audio.play().catch(() => setStatus(card, "재생할 수 없어요"));
  btn.textContent = icon(true);
  setStatus(card, "재생 중…");
}

audio.addEventListener("ended", () => {
  const card = document.querySelector(`.story-card[data-id="${activeId}"]`);
  if (!card) return;
  const btn = card.querySelector(".play-btn");
  if (btn) btn.textContent = icon(false);
  card.classList.remove("is-active");
  setStatus(card, "끝났어요. 좋은 꿈 꾸세요.");
});

audio.addEventListener("pause", () => {
  if (audio.ended) return;
  const card = document.querySelector(`.story-card[data-id="${activeId}"]`);
  if (!card) return;
  const btn = card.querySelector(".play-btn");
  if (btn && audio.paused) btn.textContent = icon(false);
});

async function enqueueStory(id) {
  const res = await fetch(`/api/generation/story/${id}`, { method: "POST" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showGenStatus(data.error || "요청하지 못했어요.", true);
    return;
  }
  showGenStatus("만드는 중…");
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

function showGenStatus(text, isError = false) {
  genStatusEl.hidden = !text;
  genStatusEl.textContent = text;
  genStatusEl.classList.toggle("is-error", isError);
}

async function pollGeneration() {
  const res = await fetch("/api/generation/status", { cache: "no-store" });
  if (!res.ok) return;
  const data = await res.json();
  const running = data.running;
  if (running) {
    const chunk =
      running.chunkTotal > 0
        ? ` (${running.chunkIndex}/${running.chunkTotal}번째)`
        : "";
    showGenStatus(
      `생성 중: ${running.currentStoryId || ""}${chunk}`
    );
    return;
  }
  if (data.queued?.length) {
    showGenStatus(`대기 중… (${data.queued.length}개)`);
    return;
  }
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
}

function setupTabs() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
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
  voiceMatchEl.textContent = "";
}

function onAudioReady() {
  prepareVoiceBtn.disabled = false;
  resetVoiceReview();
  voiceMsgEl.textContent = "미리 듣고 ‘받아쓰기 확인’을 눌러 주세요.";
  voiceMsgEl.classList.remove("is-error");
}

async function startRecording() {
  voiceMsgEl.textContent = "";
  voiceMsgEl.classList.remove("is-error");
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
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  recordBtn.disabled = false;
  stopBtn.disabled = true;
}

function onFileSelected(file) {
  if (!file) return;
  pendingBlob = file;
  previewEl.src = URL.createObjectURL(file);
  onAudioReady();
  voiceMsgEl.textContent = `${file.name} — 미리 듣고 ‘받아쓰기 확인’을 눌러 주세요.`;
}

function voiceFormData() {
  const form = new FormData();
  const ext = pendingBlob.type.includes("mp4") ? "recording.m4a" : "recording.webm";
  form.append("audio", pendingBlob, ext);
  return form;
}

async function prepareVoice() {
  if (!pendingBlob) return;
  prepareVoiceBtn.disabled = true;
  voiceMsgEl.textContent = "받아쓰는 중… (잠시만요)";
  voiceMsgEl.classList.remove("is-error");
  const res = await fetch("/api/voice/prepare", { method: "POST", body: voiceFormData() });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    voiceMsgEl.textContent = data.error || "받아쓰기에 실패했어요.";
    voiceMsgEl.classList.add("is-error");
    prepareVoiceBtn.disabled = false;
    return;
  }
  pendingToken = data.pendingToken;
  transcriptEl.value = data.transcript || "";
  voiceMetaEl.textContent = `녹음 길이: ${data.durationSec}초 · 최대 약 ${data.limits?.maxCharsForDuration ?? "?"}자`;
  const pct = data.scriptMatchPercent ?? 0;
  voiceMatchEl.textContent = `대본 일치: 약 ${pct}% (자동 받아쓰기 vs 녹음 대본)`;
  voiceMatchEl.classList.toggle("is-warn", pct < 70);
  voiceReviewEl.hidden = false;
  voiceMsgEl.textContent = "받아쓰기를 확인하고 필요하면 고친 뒤 저장해 주세요.";
  prepareVoiceBtn.disabled = false;
}

async function saveVoice() {
  if (!pendingToken) {
    voiceMsgEl.textContent = "먼저 ‘받아쓰기 확인’을 해 주세요.";
    voiceMsgEl.classList.add("is-error");
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
    voiceMsgEl.classList.add("is-error");
    saveVoiceBtn.disabled = false;
    return;
  }
  let msg = `저장했어요 (${data.durationSec}초). 이야기를 다시 만들 수 있어요.`;
  if (data.editWarning) {
    msg += ` ${data.editWarning}`;
  }
  voiceMsgEl.textContent = msg;
  voiceMsgEl.classList.remove("is-error");
  pendingBlob = null;
  pendingToken = null;
  prepareVoiceBtn.disabled = true;
  saveVoiceBtn.disabled = false;
  voiceReviewEl.hidden = true;
}

recordBtn.addEventListener("click", () => {
  startRecording().catch(() => {
    voiceMsgEl.textContent = "마이크를 사용할 수 없어요.";
    voiceMsgEl.classList.add("is-error");
  });
});
stopBtn.addEventListener("click", stopRecording);
fileInput.addEventListener("change", () => onFileSelected(fileInput.files?.[0]));
prepareVoiceBtn.addEventListener("click", prepareVoice);
saveVoiceBtn.addEventListener("click", saveVoice);
regenAllBtn.addEventListener("click", enqueueAll);

setupTabs();
loadConfig().catch(() => {});
loadCatalog();
pollGeneration();
