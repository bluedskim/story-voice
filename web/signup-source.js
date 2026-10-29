const STORAGE_KEY = "story_voice_signup_source";
export const SIGNUP_SOURCE_MAX_LEN = 64;

/** @param {string | null | undefined} raw */
export function normalizeSignupSource(raw) {
  if (raw == null || typeof raw !== "string") return null;
  let s = raw.trim().toLowerCase();
  if (!s) return null;
  let filtered = "";
  for (const ch of s) {
    if ((ch >= "a" && ch <= "z") || (ch >= "0" && ch <= "9") || ch === "_" || ch === "-") {
      filtered += ch;
    }
  }
  if (!filtered) return null;
  return filtered.slice(0, SIGNUP_SOURCE_MAX_LEN);
}

/** @param {URLSearchParams} params */
export function resolveSignupSourceFromParams(params) {
  const utm = params.get("utm_source");
  if (utm != null && utm.trim() !== "") return utm;
  const ref = params.get("ref");
  if (ref != null && ref.trim() !== "") return ref;
  return null;
}

/** First-touch capture from the landing URL; never overwrites an existing stored value. */
export function captureSignupSourceFromUrl() {
  try {
    const existing = localStorage.getItem(STORAGE_KEY);
    if (existing) return;
    const raw = resolveSignupSourceFromParams(new URLSearchParams(window.location.search));
    const normalized = normalizeSignupSource(raw);
    if (normalized) localStorage.setItem(STORAGE_KEY, normalized);
  } catch {
    /* ignore storage / URL errors */
  }
}

export function getStoredSignupSource() {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v || null;
  } catch {
    return null;
  }
}

export function clearStoredSignupSource() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
}
