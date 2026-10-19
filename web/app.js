const listEl = document.getElementById("story-list");
const audio = document.getElementById("player");

let catalog = [];
let activeId = null;

function icon(playing) {
  return playing ? "⏸" : "▶";
}

function setStatus(card, message) {
  const el = card.querySelector(".story-status");
  if (el) el.textContent = message;
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
    listEl.innerHTML = `<p class="error">목록을 불러오지 못했어요. 서버를 다시 실행해 주세요.<br><small>${err.message}</small></p>`;
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

    main.append(title, status, toggle, text);
    card.append(btn, main);
    listEl.appendChild(card);
  }
}

function togglePlayback(story, card, btn) {
  if (!story.audioUrl) return;

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
  if (audio.src !== new URL(story.audioUrl, location.href).href) {
    audio.src = story.audioUrl;
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

loadCatalog();
