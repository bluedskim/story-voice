import {
  apiFetch,
  canWrite,
  initAuthUi,
  onAuthChange,
  openAuthModal,
  refreshAuthFromConfig,
  notifyAuthChange,
} from "./auth.js";
import { showAlertModal, showPromptModal, openModal, closeModal } from "./modal.js";
import { createBufferedStarter } from "./playback.js";

const listEl = document.getElementById("story-list");
const voiceAuthGateEl = document.getElementById("voice-auth-gate");
const audio = document.getElementById("player");
const genStatusEl = document.getElementById("gen-status");
const genStatusTextEl = document.getElementById("gen-status-text");
const genConfirmModal = document.getElementById("modal-gen-confirm");
const genConfirmStoryEl = document.getElementById("gen-confirm-story");
const genConfirmAsrVerifyEl = document.getElementById("gen-confirm-asr-verify");
const genConfirmSubmitBtn = document.getElementById("gen-confirm-submit");
const genConfirmCancelBtn = document.getElementById("gen-confirm-cancel");
const genConfirmRolesEl = document.getElementById("gen-confirm-roles");
const genConfirmRolesListEl = document.getElementById("gen-confirm-roles-list");
const voiceSlotBarEl = document.getElementById("voice-slot-bar");
const voiceSlotSelectEl = document.getElementById("voice-slot-select");
const voiceSlotAddBtn = document.getElementById("voice-slot-add");
const voiceSlotLabelDisplayEl = document.getElementById("voice-slot-label-display");
const voiceSlotRenameBtn = document.getElementById("voice-slot-rename");

const recordScriptEl = document.getElementById("record-script");
const transcriptEl = document.getElementById("transcript");
const recordBtn = document.getElementById("record-btn");
const stopBtn = document.getElementById("stop-btn");
const fileInput = document.getElementById("file-input");
const previewEl = document.getElementById("preview");
const previewPlayerUi = document.getElementById("preview-player-ui");
const previewPlayBtn = document.getElementById("preview-play");
const previewCurrentEl = document.getElementById("preview-current");
const previewDurationEl = document.getElementById("preview-duration");
const previewSeekEl = document.getElementById("preview-seek");
const previewSavedHintEl = document.getElementById("preview-saved-hint");
const prepareVoiceBtn = document.getElementById("prepare-voice");
const prepareVoiceLabelEl = prepareVoiceBtn?.querySelector(".prepare-voice-label");
const voiceSectionVerifyEl = document.getElementById("voice-section-verify");
const saveVoiceBtn = document.getElementById("save-voice");
const voiceMsgEl = document.getElementById("voice-msg");
const voiceSectionSaveEl = document.getElementById("voice-section-save");
const voiceRecordingStatusEl = document.getElementById("voice-recording-status");
const recordBtnLabelEl = recordBtn.querySelector(".record-btn-label");
const voiceReviewEl = document.getElementById("voice-review");
const voiceMetaEl = document.getElementById("voice-meta");
const voiceMatchEl = document.getElementById("voice-match");
const matchRingEl = document.getElementById("match-ring");
const matchTextEl = document.getElementById("match-text");
const voiceRerecordHintEl = document.getElementById("voice-rerecord-hint");
const voiceSteps = document.querySelectorAll(".voice-step");

const VOICE_MIN_MATCH_PERCENT = 70;
let voiceCanSave = false;

const nowPlayingEl = document.getElementById("now-playing");
const npTitleEl = document.getElementById("np-title");
const npArtEl = document.getElementById("np-art");
const npCurrentEl = document.getElementById("np-current");
const npDurationEl = document.getElementById("np-duration");
const npSeekEl = document.getElementById("np-seek");
const npPlayBtn = document.getElementById("np-play");

const STORY_MOTIFS = {
  "ui-joeun-hyeongje": "🌾",
  "geum-dokki-eun-dokki": "🪓",
  "hokburi-yeonggam": "🎶",
  "horangi-wa-gotgam": "🐯",
  "eunhye-gapeun-kkachi": "🐦",
  "tokki-ui-gan": "🐰",
  "ureong-gaksi": "🐚",
  "cheong-gaeguri": "🐸",
  "gyeonu-wa-jiknyeo": "🌌",
  "namukkun-gwa-seonnyeo": "🦌",
  "gae-wa-goyangi-ui-guseul": "💎",
};

let catalog = [];
let hasPersonalVoice = false;
let activeId = null;
let activeStory = null;
let audioCacheBust = Date.now();
let pollTimer = null;
let durationCache = {};
let generationBusy = false;
/** @type {{ storyId: string, chunkIndex: number, chunkTotal: number } | null} */
let genCardState = null;
let seekDragging = false;
let playLoading = false;
let previewSeekDragging = false;
let prepareVoiceBusy = false;

const LOGIN_REQUIRED_MSG =
  "로그인이 필요해요. 로그인하면 내 목소리를 저장하고, 내 목소리로 이야기를 만들 수 있어요.";

function showVoiceBlockingAlert(message, { title = "목소리 저장" } = {}) {
  showAlertModal({
    title,
    message,
    buttons: [{ label: "확인", primary: true }],
  });
}

function showGenerationBlockingAlert(message, { title = "이야기 만들기" } = {}) {
  showAlertModal({
    title,
    message,
    buttons: [{ label: "확인", primary: true }],
  });
}

function warnLoginRequired() {
  if (canWrite()) return false;
  showAlertModal({
    title: "로그인이 필요해요",
    message: LOGIN_REQUIRED_MSG,
    buttons: [
      {
        label: "로그인",
        primary: true,
        onClick: () => openAuthModal("login"),
      },
      {
        label: "회원가입",
        onClick: () => openAuthModal("signup"),
      },
      { label: "닫기" },
    ],
  });
  return true;
}

let initialAuthUiSynced = false;

let mediaRecorder = null;
let recordChunks = [];
let pendingBlob = null;
let pendingToken = null;
let voiceReferenceBust = 0;
let voiceSlots = [];
let activeVoiceSlotId = 1;
let genRoleAssignment = {};
let previewObjectUrl = null;

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

function storyTitleForId(id) {
  return catalog.find((s) => s.id === id)?.title || id || "이야기";
}

function genProgressPercent(chunkIndex, chunkTotal) {
  const total = chunkTotal || 1;
  const current = chunkIndex || 0;
  return Math.min(100, Math.round((current / total) * 100));
}

function clearGenCardProgress() {
  genCardState = null;
  document.querySelectorAll(".story-gen-progress").forEach((el) => el.remove());
  document.querySelectorAll(".story-status[data-gen-hidden]").forEach((el) => {
    el.hidden = false;
    el.removeAttribute("data-gen-hidden");
  });
}

function mountStoryGenProgress(card, state) {
  const { storyId, chunkIndex, chunkTotal } = state;
  const title = storyTitleForId(storyId);
  const chunk =
    chunkTotal > 0 ? ` · ${chunkIndex}/${chunkTotal}번째` : "";
  const statusEl = card.querySelector(".story-status");
  if (statusEl && !statusEl.hidden) {
    statusEl.hidden = true;
    statusEl.dataset.genHidden = "1";
  }
  let wrap = card.querySelector(".story-gen-progress");
  if (!wrap) {
    wrap = document.createElement("div");
    wrap.className = "story-gen-progress gen-status is-busy";
    wrap.setAttribute("role", "status");
    const textEl = document.createElement("p");
    textEl.className = "gen-status-text";
    const progEl = document.createElement("div");
    progEl.className = "gen-progress";
    const barEl = document.createElement("div");
    barEl.className = "gen-progress-bar";
    progEl.appendChild(barEl);
    wrap.append(textEl, progEl);
    if (statusEl) {
      statusEl.insertAdjacentElement("afterend", wrap);
    } else {
      card.querySelector(".story-actions")?.insertAdjacentElement("beforebegin", wrap);
    }
  }
  wrap.querySelector(".gen-status-text").textContent = `만드는 중: ${title}${chunk}`;
  wrap.querySelector(".gen-progress-bar").style.width = `${genProgressPercent(chunkIndex, chunkTotal)}%`;
}

function syncGenCardProgressUi() {
  document.querySelectorAll(".story-gen-progress").forEach((el) => {
    const card = el.closest(".story-card");
    if (!genCardState || !card || card.dataset.id !== genCardState.storyId) {
      el.remove();
    }
  });
  if (!genCardState) {
    document.querySelectorAll(".story-status[data-gen-hidden]").forEach((el) => {
      el.hidden = false;
      el.removeAttribute("data-gen-hidden");
    });
    return;
  }
  const card = document.querySelector(
    `.story-card[data-id="${CSS.escape(genCardState.storyId)}"]`
  );
  if (card) {
    genStatusEl.hidden = true;
    genStatusTextEl.textContent = "";
    genStatusEl.classList.remove("is-busy");
    mountStoryGenProgress(card, genCardState);
    return;
  }
  const { storyId, chunkIndex, chunkTotal } = genCardState;
  const title = storyTitleForId(storyId);
  const chunk =
    chunkTotal > 0 ? ` · ${chunkIndex}/${chunkTotal}번째` : "";
  showGenStatus(`만드는 중: ${title}${chunk}`, false);
}

function setGenCardProgress(storyId, chunkIndex, chunkTotal) {
  genCardState = { storyId, chunkIndex, chunkTotal };
  syncGenCardProgressUi();
}

function storyBadgeLabel(story) {
  if (!story.hasAudio) return "준비 중";
  if (story.audioSource === "personal") return "내 목소리";
  return "기본 낭독";
}

function storyStatusMessage(story) {
  if (!story.hasAudio) {
    return "기본 낭독을 준비하는 중이에요. 잠시만 기다려 주세요.";
  }
  if (story.audioSource === "personal") {
    return "내 목소리로 재생할 준비됐어요";
  }
  return "기본 낭독으로 들을 수 있어요. 내 목소리는 목소리 탭에서 저장 후 만들 수 있어요.";
}

function regenButtonLabel(story) {
  return story.hasPersonalAudio ? "내 목소리로 다시 만들기" : "내 목소리로 만들기";
}

function storyIdsFromRecentJob(last) {
  if (last?.storyIds?.length) return last.storyIds;
  if (last?.currentStoryId) return [last.currentStoryId];
  return [];
}

/** @returns {boolean} true if the card was updated in the DOM */
function patchStoryCardInPlace(story) {
  const card = document.querySelector(
    `.story-card[data-id="${CSS.escape(story.id)}"]`
  );
  if (!card) return false;

  card.classList.toggle("is-missing", !story.hasAudio);
  card.classList.toggle(
    "is-default-audio",
    Boolean(story.hasAudio && story.audioSource === "default")
  );

  const badge = card.querySelector(".story-badge");
  if (badge) badge.textContent = storyBadgeLabel(story);

  const statusEl = card.querySelector(".story-status");
  const keepStatus =
    activeId === story.id && (!audio.paused || playLoading);
  if (statusEl && !statusEl.hidden && !keepStatus) {
    statusEl.textContent = storyStatusMessage(story);
  }

  const playBtn = card.querySelector(".play-btn");
  if (playBtn) {
    playBtn.disabled = !story.hasAudio;
    playBtn.setAttribute(
      "aria-label",
      story.hasAudio ? `${story.title} 재생` : "오디오 없음"
    );
  }

  const regenBtn = card.querySelector(".story-actions button.regen-btn");
  if (regenBtn) {
    regenBtn.textContent = regenButtonLabel(story);
  }

  const actions = card.querySelector(".story-actions");
  if (actions && story.hasAudio && story.audioUrl) {
    let download = actions.querySelector("a.regen-btn");
    if (!download) {
      download = document.createElement("a");
      download.className = "btn btn-secondary regen-btn";
      download.textContent = "다운로드";
      actions.append(download);
    }
    download.href = `${story.audioUrl.split("?")[0]}?download=1`;
    download.setAttribute("aria-label", `${story.title} 오디오 다운로드`);
  }

  if (activeId === story.id) {
    activeStory = story;
    const url = storyAudioUrl(story);
    const playing = !audio.paused || playLoading;
    if (url && !playing) {
      const nextSrc = new URL(url, location.href).href;
      if (audio.src !== nextSrc) {
        audio.src = url;
      }
    }
  }

  syncNowPlayingUi();
  return true;
}

function applyPersonalGenerationToCatalog(storyId) {
  const story = catalog.find((s) => s.id === storyId);
  if (!story) return null;
  story.hasAudio = true;
  story.hasPersonalAudio = true;
  story.audioSource = "personal";
  if (!story.audioUrl) story.audioUrl = `/audio/${storyId}.m4a`;
  return story;
}

async function applyGenerationDone(last) {
  const storyIds = storyIdsFromRecentJob(last);
  if (!storyIds.length) {
    await loadCatalog({ showLoading: false });
    return;
  }
  let needFullReload = false;
  for (const id of storyIds) {
    const story = applyPersonalGenerationToCatalog(id);
    if (!story) {
      needFullReload = true;
      continue;
    }
    if (!patchStoryCardInPlace(story)) {
      needFullReload = true;
      continue;
    }
    delete durationCache[story.id];
    probeDuration(story);
  }
  if (needFullReload) {
    await loadCatalog({ showLoading: false });
  }
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

function setRecordingUi(active) {
  document.getElementById("panel-voice")?.classList.toggle("is-recording", active);
  recordBtn.classList.toggle("is-recording", active);
  stopBtn.classList.toggle("is-recording-stop", active);
  if (voiceRecordingStatusEl) voiceRecordingStatusEl.hidden = !active;
  if (recordBtnLabelEl) recordBtnLabelEl.textContent = active ? "녹음 중…" : "녹음";
}

function syncVoiceSections() {
  const hasAudio = Boolean(pendingBlob);
  const hasPrepared = Boolean(pendingToken);
  if (voiceSectionVerifyEl) voiceSectionVerifyEl.hidden = !hasAudio;
  if (voiceSectionSaveEl) voiceSectionSaveEl.hidden = !hasPrepared;
}

function setAppBusy(busy) {
  generationBusy = busy;
  document.body.classList.toggle("is-app-busy", busy);
  if (busy) {
    prepareVoiceBtn.disabled = true;
    recordBtn.disabled = true;
    stopBtn.disabled = true;
  } else {
    updateWriteGates();
  }
}

function applyConfigData(data) {
  recordScriptEl.value = data.recordScript || "";
  hasPersonalVoice = Boolean(data.hasPersonalVoice);
  voiceSlots = Array.isArray(data.voiceSlots) ? data.voiceSlots : [];
  if (data.voiceReferenceVersion) {
    voiceReferenceBust = data.voiceReferenceVersion;
  }
  syncVoiceSlotLabelsEverywhere();
  updateWriteGates();
  syncSavedVoicePreview();
}

function applyVoiceSlotsFromServer(slots) {
  if (!Array.isArray(slots)) return;
  voiceSlots = slots;
  syncVoiceSlotLabelsEverywhere();
}

function syncVoiceSlotLabelsEverywhere() {
  renderVoiceSlotUi();
  if (!genConfirmRolesListEl) return;
  genConfirmRolesListEl.querySelectorAll(".gen-role-select").forEach((sel) => {
    for (const opt of sel.options) {
      const sid = Number(opt.value);
      const slot = voiceSlots.find((s) => s.id === sid);
      if (slot) opt.textContent = slot.label || `목소리 ${sid}`;
    }
  });
}

function renderVoiceSlotUi() {
  if (!voiceSlotBarEl || !voiceSlotSelectEl) return;
  const show = canWrite();
  voiceSlotBarEl.hidden = !show;
  if (!show) return;
  if (!voiceSlots.length && hasPersonalVoice) {
    voiceSlots = [{ id: 1, label: "내 목소리", hasReference: true, referenceVersion: voiceReferenceBust }];
  }
  voiceSlotSelectEl.innerHTML = "";
  for (const slot of voiceSlots) {
    const opt = document.createElement("option");
    opt.value = String(slot.id);
    const suffix = slot.hasReference ? "" : " (비어 있음)";
    opt.textContent = `${slot.label || "내 목소리"}${suffix}`;
    voiceSlotSelectEl.appendChild(opt);
  }
  if (!voiceSlots.some((s) => s.id === activeVoiceSlotId)) {
    activeVoiceSlotId = voiceSlots[0]?.id || 1;
  }
  voiceSlotSelectEl.value = String(activeVoiceSlotId);
  const current = voiceSlots.find((s) => s.id === activeVoiceSlotId);
  if (voiceSlotLabelDisplayEl && current) {
    voiceSlotLabelDisplayEl.textContent = current.label || "내 목소리";
  }
  if (voiceSlotRenameBtn) {
    voiceSlotRenameBtn.disabled = !current;
  }
  if (voiceSlotAddBtn) {
    voiceSlotAddBtn.disabled = voiceSlots.length >= (dataMaxVoiceSlots() || 4);
  }
}

function dataMaxVoiceSlots() {
  return 4;
}

voiceSlotSelectEl?.addEventListener("change", () => {
  activeVoiceSlotId = Number(voiceSlotSelectEl.value) || 1;
  syncVoiceSlotLabelsEverywhere();
  syncSavedVoicePreview();
});

async function renameActiveVoiceSlot() {
  if (!canWrite()) return;
  const current = voiceSlots.find((s) => s.id === activeVoiceSlotId);
  if (!current) return;
  const label = await showPromptModal({
    title: "목소리 이름",
    message: "이 목소리를 구분할 이름을 입력해 주세요.",
    defaultValue: current.label || "내 목소리",
    maxLength: 20,
  });
  if (label == null) return;
  const res = await apiFetch("/api/voice/slots/label", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ slotId: activeVoiceSlotId, label }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showVoiceBlockingAlert(data.error || "이름을 바꾸지 못했어요.");
    return;
  }
  applyVoiceSlotsFromServer(data.slots);
}

voiceSlotRenameBtn?.addEventListener("click", () => {
  renameActiveVoiceSlot();
});

voiceSlotAddBtn?.addEventListener("click", async () => {
  if (warnLoginRequired()) return;
  const label = await showPromptModal({
    title: "새 목소리",
    message: "추가할 목소리의 이름을 입력해 주세요.",
    defaultValue: "내 목소리",
    maxLength: 20,
  });
  if (label == null) return;
  const res = await apiFetch("/api/voice/slots", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showVoiceBlockingAlert(data.error || "목소리를 추가하지 못했어요.");
    return;
  }
  if (data.slot) {
    voiceSlots.push(data.slot);
    activeVoiceSlotId = data.slot.id;
    syncVoiceSlotLabelsEverywhere();
  }
});

async function loadConfig() {
  const data = await refreshAuthFromConfig({ notify: false });
  applyConfigData(data);
  if (!initialAuthUiSynced) {
    initialAuthUiSynced = true;
    notifyAuthChange();
  }
}

function updateWriteGates() {
  const allowed = canWrite();
  document.body.classList.toggle("can-write", allowed);
  if (voiceAuthGateEl) {
    voiceAuthGateEl.hidden = allowed;
  }
  if (genConfirmAsrVerifyEl) {
    genConfirmAsrVerifyEl.disabled = generationBusy || !allowed;
  }
  if (!allowed) {
    recordBtn.disabled = true;
    prepareVoiceBtn.disabled = true;
    stopBtn.disabled = true;
  } else if (!generationBusy && !prepareVoiceBusy && (!mediaRecorder || mediaRecorder.state === "inactive")) {
    recordBtn.disabled = false;
    if (pendingBlob) prepareVoiceBtn.disabled = false;
  }
  document.querySelectorAll(".regen-btn").forEach((btn) => {
    if (btn.tagName !== "BUTTON") return;
    btn.disabled = generationBusy || (canWrite() && !hasPersonalVoice);
  });
}

onAuthChange(() => {
  loadConfig().catch(() => {});
  loadCatalog({ showLoading: false }).catch(() => {});
});

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

let catalogLoadSeq = 0;

async function loadCatalog({ showLoading = true } = {}) {
  const seq = ++catalogLoadSeq;
  if (showLoading) {
    listEl.innerHTML = '<p class="loading">이야기를 불러오는 중…</p>';
  }
  try {
    const res = await apiFetch("/api/catalog", { cache: "no-store" });
    if (!res.ok) throw new Error(`/api/catalog ${res.status}`);
    const data = await res.json();
    if (seq !== catalogLoadSeq) return;
    catalog = data.stories || [];
    hasPersonalVoice = Boolean(data.hasPersonalVoice);
    render();
    syncSavedVoicePreview();
    catalog.forEach(probeDuration);
  } catch (err) {
    if (seq !== catalogLoadSeq) return;
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
    else if (story.audioSource === "default") card.classList.add("is-default-audio");

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
    badge.textContent = storyBadgeLabel(story);
    const dur = document.createElement("span");
    dur.className = "story-duration";
    dur.dataset.id = story.id;
    dur.textContent = durationCache[story.id] ? formatTime(durationCache[story.id]) : "—:—";
    meta.append(badge, dur);

    const status = document.createElement("p");
    status.className = "story-status";
    status.textContent = storyStatusMessage(story);

    const regen = document.createElement("button");
    regen.type = "button";
    regen.className = "btn btn-secondary regen-btn";
    regen.textContent = regenButtonLabel(story);
    regen.addEventListener("click", () => openGenerationConfirm(story));
    regen.disabled = generationBusy || (canWrite() && !hasPersonalVoice);
    if (!hasPersonalVoice && canWrite()) {
      regen.title = "목소리 탭에서 내 목소리를 먼저 저장해 주세요";
    } else {
      regen.removeAttribute("title");
    }

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
    if (activeId === story.id) {
      card.classList.add("is-active");
    }

    listEl.appendChild(card);
  }
  syncNowPlayingUi();
  syncGenCardProgressUi();
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
  npPlayBtn.textContent = playLoading ? "…" : playIcon(!audio.paused);
  npPlayBtn.classList.toggle("is-loading", playLoading);
  document.querySelectorAll(".play-btn").forEach((b) => {
    const card = b.closest(".story-card");
    if (!card) return;
    const isActive = card.dataset.id === activeId;
    const loading = isActive && playLoading;
    b.textContent = loading ? "…" : playIcon(isActive && !audio.paused);
    b.classList.toggle("is-loading", loading);
  });
}

const playStarter = createBufferedStarter(audio);

function setPlayLoading(on) {
  playLoading = on;
  const card = activeId ? document.querySelector(`.story-card[data-id="${activeId}"]`) : null;
  if (card && on) setStatus(card, "불러오는 중…");
  syncNowPlayingUi();
}

function startActivePlayback(card) {
  playStarter.start({ onLoading: setPlayLoading }).catch(() => {
    setPlayLoading(false);
    if (card) setStatus(card, "재생할 수 없어요");
  });
}

function togglePlayback(story, card, btn) {
  const url = storyAudioUrl(story);
  if (!url) return;

  if (activeId === story.id && (!audio.paused || playLoading)) {
    playStarter.cancel();
    playLoading = false;
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
  startActivePlayback(card);
  syncNowPlayingUi();
}

audio.addEventListener("timeupdate", syncNowPlayingUi);
audio.addEventListener("playing", () => {
  if (audio.muted) return; // still priming while buffering
  const card = activeId ? document.querySelector(`.story-card[data-id="${activeId}"]`) : null;
  if (card) setStatus(card, "재생 중…");
  npPlayBtn.classList.remove("is-buffering");
  syncNowPlayingUi();
});
audio.addEventListener("waiting", () => {
  if (audio.muted) return;
  npPlayBtn.classList.add("is-buffering");
});
audio.addEventListener("loadedmetadata", syncNowPlayingUi);
audio.addEventListener("ended", () => {
  const card = document.querySelector(`.story-card[data-id="${activeId}"]`);
  if (card) {
    setStatus(card, "끝났어요.");
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
  const card = document.querySelector(`.story-card[data-id="${activeId}"]`);
  if (playLoading) {
    playStarter.cancel();
    playLoading = false;
    audio.pause();
  } else if (audio.paused) {
    startActivePlayback(card);
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

function generationRequestBody(asrVerify, assignments) {
  const payload = { asrVerify: Boolean(asrVerify) };
  if (assignments && Object.keys(assignments).length) {
    payload.assignments = assignments;
  }
  return JSON.stringify(payload);
}

async function openGenerationConfirm(story) {
  if (warnLoginRequired()) return;
  if (!genConfirmModal || !genConfirmStoryEl || !genConfirmAsrVerifyEl) {
    enqueueStory(story.id, false, {});
    return;
  }
  genConfirmStoryEl.textContent = `「${story.title}」을(를) 저장한 목소리로 낭독을 만들어요.`;
  genConfirmAsrVerifyEl.disabled = generationBusy;
  genRoleAssignment = {};
  if (genConfirmRolesEl && genConfirmRolesListEl) {
    genConfirmRolesEl.hidden = true;
    genConfirmRolesListEl.innerHTML = "";
    try {
      const res = await apiFetch(`/api/stories/${story.id}/voice-roles`);
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.showRolePicker && data.roles?.length) {
        genConfirmRolesEl.hidden = false;
        const slots = (data.slots || []).filter((s) => s.hasReference);
        const assignment = data.assignment || {};
        genRoleAssignment = { ...assignment };
        for (const role of data.roles) {
          const row = document.createElement("label");
          row.className = "gen-role-row";
          const span = document.createElement("span");
          span.className = "gen-role-label";
          span.textContent = role.label;
          const sel = document.createElement("select");
          sel.className = "field-input gen-role-select";
          sel.dataset.roleKey = role.key;
          for (const slot of slots) {
            const opt = document.createElement("option");
            opt.value = String(slot.id);
            opt.textContent = slot.label || `목소리 ${slot.id}`;
            sel.appendChild(opt);
          }
          const chosen = assignment[role.key] || assignment.narrator || slots[0]?.id;
          if (chosen) sel.value = String(chosen);
          sel.addEventListener("change", () => {
            genRoleAssignment[role.key] = Number(sel.value);
          });
          genRoleAssignment[role.key] = Number(sel.value);
          row.appendChild(span);
          row.appendChild(sel);
          genConfirmRolesListEl.appendChild(row);
        }
      }
    } catch {
      /* single-voice fallback */
    }
  }
  openModal(genConfirmModal);
  genConfirmModal.dataset.storyId = story.id;
  genConfirmSubmitBtn?.focus();
}

async function enqueueStory(id, asrVerify = false, assignments = null) {
  if (warnLoginRequired()) return;
  const bodyAssignments =
    assignments && Object.keys(assignments).length ? assignments : genRoleAssignment;
  const res = await apiFetch(`/api/generation/story/${id}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: generationRequestBody(asrVerify, bodyAssignments),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showGenerationBlockingAlert(data.error || "요청하지 못했어요.");
    return;
  }
  showGenStatus("");
  setGenCardProgress(id, 0, 1);
  startPolling();
}

function showGenStatus(text, isError = false) {
  genStatusEl.hidden = !text;
  genStatusTextEl.textContent = text;
  genStatusEl.classList.toggle("is-error", isError);
  genStatusEl.classList.toggle("is-busy", false);
}

async function pollGeneration() {
  const res = await fetch("/api/generation/status", { cache: "no-store" });
  if (!res.ok) return;
  const data = await res.json();
  const running = data.running;
  if (running) {
    setAppBusy(true);
    setGenCardProgress(
      running.currentStoryId,
      running.chunkIndex || 0,
      running.chunkTotal || 1
    );
    return;
  }
  if (data.queued?.length) {
    setAppBusy(true);
    clearGenCardProgress();
    showGenStatus(`대기 중… (${data.queued.length}개)`, false);
    return;
  }
  setAppBusy(false);
  const last = data.recent?.[0];
  if (last?.state === "failed") {
    clearGenCardProgress();
    showGenerationBlockingAlert(last.error || "실패했어요.");
    stopPolling();
    return;
  }
  if (last?.state === "done") {
    clearGenCardProgress();
    audioCacheBust = Date.now();
    showGenStatus("새 목소리로 만들었어요.");
    await applyGenerationDone(last);
    stopPolling();
    setTimeout(() => showGenStatus(""), 4000);
    return;
  }
  stopPolling();
  clearGenCardProgress();
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

function revokePreviewObjectUrl() {
  if (previewObjectUrl) {
    URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = null;
  }
}

function savedVoicePreviewUrl() {
  const bust = voiceReferenceBust || Date.now();
  const slot = activeVoiceSlotId || 1;
  const current = voiceSlots.find((s) => s.id === slot);
  const ver = current?.referenceVersion || bust;
  return `/api/voice/reference.wav?slot=${slot}&v=${ver}`;
}

function syncPreviewSavedHint() {
  const showSaved =
    Boolean(previewEl.src) &&
    !pendingBlob &&
    hasPersonalVoice &&
    canWrite() &&
    !previewObjectUrl;
  if (previewSavedHintEl) previewSavedHintEl.hidden = !showSaved;
}

function resetPreviewSeekUi() {
  if (previewCurrentEl) previewCurrentEl.textContent = "0:00";
  if (previewDurationEl) previewDurationEl.textContent = "0:00";
  if (previewSeekEl) previewSeekEl.value = "0";
}

function syncPreviewUi() {
  if (!previewEl.src) return;
  previewPlayBtn.textContent = playIcon(!previewEl.paused);
  const dur = Number.isFinite(previewEl.duration) ? previewEl.duration : 0;
  if (previewCurrentEl) previewCurrentEl.textContent = formatTime(previewEl.currentTime);
  if (previewDurationEl) previewDurationEl.textContent = formatTime(dur);
  if (!previewSeekDragging && previewSeekEl && dur > 0) {
    previewSeekEl.value = String(Math.round((previewEl.currentTime / dur) * 1000));
  }
}

function setPreviewToPending(blob) {
  revokePreviewObjectUrl();
  previewObjectUrl = URL.createObjectURL(blob);
  previewEl.src = previewObjectUrl;
  previewPlayerUi.hidden = false;
  resetPreviewSeekUi();
  syncPreviewSavedHint();
  previewEl.load();
}

function setPreviewToSavedReference(bust) {
  revokePreviewObjectUrl();
  if (bust) voiceReferenceBust = bust;
  previewEl.src = savedVoicePreviewUrl();
  previewPlayerUi.hidden = false;
  resetPreviewSeekUi();
  syncPreviewSavedHint();
  previewEl.load();
}

function syncSavedVoicePreview() {
  if (pendingBlob) {
    syncPreviewSavedHint();
    return;
  }
  if (!hasPersonalVoice || !canWrite()) {
    revokePreviewObjectUrl();
    previewEl.removeAttribute("src");
    previewPlayerUi.hidden = true;
    syncPreviewSavedHint();
    return;
  }
  setPreviewToSavedReference(voiceReferenceBust);
}

function setPrepareVoiceBusy(busy) {
  prepareVoiceBusy = busy;
  prepareVoiceBtn.classList.toggle("is-busy", busy);
  prepareVoiceBtn.setAttribute("aria-busy", busy ? "true" : "false");
  voiceSectionVerifyEl?.classList.toggle("is-preparing", busy);
  if (prepareVoiceLabelEl) {
    prepareVoiceLabelEl.textContent = busy ? "발음 검증 중…" : "발음 검증";
  }
  if (busy) {
    recordBtn.disabled = true;
    stopBtn.disabled = true;
  } else if (!generationBusy) {
    updateWriteGates();
  }
}

function resetVoiceReview() {
  pendingToken = null;
  voiceCanSave = false;
  voiceReviewEl.hidden = true;
  transcriptEl.value = "";
  voiceMetaEl.textContent = "";
  matchTextEl.textContent = "";
  matchRingEl.style.setProperty("--pct", "0%");
  matchRingEl.dataset.label = "";
  voiceMatchEl.hidden = true;
  voiceMatchEl.classList.remove("is-warn");
  voiceRerecordHintEl.hidden = true;
  saveVoiceBtn.disabled = false;
  syncVoiceSections();
  setVoiceStep(1);
}

function onAudioReady() {
  if (!generationBusy) prepareVoiceBtn.disabled = false;
  resetVoiceReview();
  syncVoiceSections();
  previewPlayerUi.hidden = false;
  voiceMsgEl.textContent = "미리 듣고 ‘발음 검증’을 눌러 주세요.";
  voiceMsgEl.className = "voice-msg";
  setVoiceStep(1);
}

async function startRecording() {
  if (warnLoginRequired()) return;
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
    setPreviewToPending(pendingBlob);
    onAudioReady();
  };
  mediaRecorder.start();
  recordBtn.disabled = true;
  stopBtn.disabled = false;
  setRecordingUi(true);
  voiceMsgEl.textContent = "녹음 중… 멈춤을 누르면 녹음이 끝납니다.";
  voiceMsgEl.className = "voice-msg is-recording";
  setVoiceStep(1);
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== "inactive") {
    mediaRecorder.stop();
  }
  setRecordingUi(false);
  recordBtn.disabled = generationBusy;
  stopBtn.disabled = true;
}

function onFileSelected(file) {
  if (!file) return;
  if (warnLoginRequired()) return;
  pendingBlob = file;
  setPreviewToPending(file);
  onAudioReady();
  voiceMsgEl.textContent = `${file.name} — 미리 듣고 ‘발음 검증’을 눌러 주세요.`;
}

previewPlayBtn.addEventListener("click", () => {
  if (!previewEl.src) return;
  if (previewEl.paused) previewEl.play();
  else previewEl.pause();
  syncPreviewUi();
});

previewEl.addEventListener("timeupdate", syncPreviewUi);
previewEl.addEventListener("loadedmetadata", syncPreviewUi);
previewEl.addEventListener("ended", syncPreviewUi);
previewEl.addEventListener("pause", syncPreviewUi);

previewSeekEl?.addEventListener("input", () => {
  previewSeekDragging = true;
  const dur = previewEl.duration;
  if (!Number.isFinite(dur)) return;
  const t = (Number(previewSeekEl.value) / 1000) * dur;
  if (previewCurrentEl) previewCurrentEl.textContent = formatTime(t);
});

previewSeekEl?.addEventListener("change", () => {
  const dur = previewEl.duration;
  if (Number.isFinite(dur)) {
    previewEl.currentTime = (Number(previewSeekEl.value) / 1000) * dur;
  }
  previewSeekDragging = false;
  syncPreviewUi();
});

function voiceFormData() {
  const form = new FormData();
  const ext = pendingBlob.type.includes("mp4") ? "recording.m4a" : "recording.webm";
  form.append("audio", pendingBlob, ext);
  form.append("slotId", String(activeVoiceSlotId || 1));
  return form;
}

async function prepareVoice() {
  if (warnLoginRequired()) return;
  if (!pendingBlob || generationBusy || prepareVoiceBusy) return;
  setPrepareVoiceBusy(true);
  prepareVoiceBtn.disabled = true;
  voiceMsgEl.textContent = "발음 검증 중… 받아쓰고 대본과 비교하는 중입니다. 잠시만 기다려 주세요.";
  voiceMsgEl.className = "voice-msg is-busy";
  try {
    const res = await apiFetch("/api/voice/prepare", { method: "POST", body: voiceFormData() });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showVoiceBlockingAlert(data.error || "받아쓰기에 실패했어요.");
      return;
    }
    pendingToken = data.pendingToken;
    transcriptEl.value = data.transcript || "";
    voiceMetaEl.textContent = `녹음 ${data.durationSec}초 · 이 길이에는 보통 ${data.limits?.maxCharsForDuration ?? "?"}자 이하`;
    const pct = data.scriptMatchPercent ?? 0;
    voiceCanSave = pct >= VOICE_MIN_MATCH_PERCENT;
    matchRingEl.style.setProperty("--pct", `${pct}%`);
    matchRingEl.dataset.label = `${pct}`;
    matchTextEl.textContent = `대본 일치 약 ${pct}% (녹음 대본 vs 자동 인식)`;
    const lowMatch = pct < VOICE_MIN_MATCH_PERCENT;
    voiceMatchEl.hidden = false;
    voiceMatchEl.classList.toggle("is-warn", lowMatch);
    voiceRerecordHintEl.hidden = !lowMatch;
    saveVoiceBtn.disabled = lowMatch;
    voiceReviewEl.hidden = false;
    syncVoiceSections();
    voiceMsgEl.textContent = lowMatch
      ? "대본과 녹음이 맞지 않아요. 같은 대본으로 다시 녹음해 주세요."
      : "대본 일치가 충분해요. ‘이 목소리로 저장’을 눌러 주세요.";
    voiceMsgEl.className = lowMatch ? "voice-msg is-warn" : "voice-msg";
    setVoiceStep(2);
  } finally {
    setPrepareVoiceBusy(false);
    if (!generationBusy && pendingBlob) prepareVoiceBtn.disabled = false;
  }
}

async function saveVoice() {
  if (warnLoginRequired()) return;
  if (!pendingToken) {
    showVoiceBlockingAlert("먼저 ‘발음 검증’을 해 주세요.");
    return;
  }
  if (!voiceCanSave) {
    showVoiceBlockingAlert("대본과 녹음이 맞지 않아요. 같은 대본으로 다시 녹음해 주세요.");
    return;
  }
  saveVoiceBtn.disabled = true;
  voiceMsgEl.textContent = "저장하는 중…";
  const res = await apiFetch("/api/voice/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pendingToken, transcript: transcriptEl.value }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showVoiceBlockingAlert(data.error || "저장하지 못했어요.");
    saveVoiceBtn.disabled = !voiceCanSave;
    return;
  }
  const msg = `저장했어요 (${data.durationSec}초). 이야기를 다시 만들 수 있어요.`;
  voiceMsgEl.className = "voice-msg";
  voiceMsgEl.textContent = msg;
  hasPersonalVoice = true;
  pendingBlob = null;
  pendingToken = null;
  const sid = data.slotId || activeVoiceSlotId || 1;
  const label =
    voiceSlots.find((s) => s.id === sid)?.label?.trim() ||
    voiceSlotLabelDisplayEl?.textContent?.trim() ||
    "내 목소리";
  const bust = data.referenceVersion || Date.now();
  const entry = {
    id: sid,
    label,
    hasReference: true,
    referenceVersion: bust,
  };
  const idx = voiceSlots.findIndex((s) => s.id === sid);
  if (idx >= 0) voiceSlots[idx] = { ...voiceSlots[idx], ...entry };
  else voiceSlots.push(entry);
  activeVoiceSlotId = sid;
  syncVoiceSlotLabelsEverywhere();
  prepareVoiceBtn.disabled = true;
  saveVoiceBtn.disabled = false;
  voiceReviewEl.hidden = true;
  syncVoiceSections();
  setPreviewToSavedReference(bust);
  syncPreviewSavedHint();
  setVoiceStep(3);
}

recordBtn.addEventListener("click", () => {
  startRecording().catch(() => {
    setRecordingUi(false);
    showVoiceBlockingAlert("마이크를 사용할 수 없어요.", { title: "녹음" });
  });
});
stopBtn.addEventListener("click", stopRecording);
fileInput.addEventListener("change", () => onFileSelected(fileInput.files?.[0]));
prepareVoiceBtn.addEventListener("click", prepareVoice);
saveVoiceBtn.addEventListener("click", saveVoice);

function setupGenerationConfirmModal() {
  if (!genConfirmModal || genConfirmModal.dataset.bound) return;
  genConfirmModal.dataset.bound = "1";
  genConfirmModal.addEventListener("click", (event) => {
    if (event.target === genConfirmModal) closeModal(genConfirmModal);
  });
  genConfirmCancelBtn?.addEventListener("click", () => closeModal(genConfirmModal));
  genConfirmSubmitBtn?.addEventListener("click", () => {
    const id = genConfirmModal.dataset.storyId;
    const asrVerify = Boolean(genConfirmAsrVerifyEl?.checked);
    const assignments = { ...genRoleAssignment };
    closeModal(genConfirmModal);
    if (id) enqueueStory(id, asrVerify, assignments);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || genConfirmModal.hidden) return;
    closeModal(genConfirmModal);
  });
}

setupGenerationConfirmModal();
setupTabs();
initAuthUi();
if (location.hash === "#voice") {
  document.querySelector('.tab[data-tab="voice"]')?.click();
}
setVoiceStep(1);
syncVoiceSections();
loadConfig().catch(() => {});
loadCatalog();
pollGeneration();
