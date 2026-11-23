// Buffer-aware playback start for the story player.
//
// Calling audio.play() before enough data is buffered lets the browser start
// the clock, stall, and resume — the first syllables sound clipped. We prime
// the element muted (keeps the user-gesture unlock on iOS), wait until it can
// play through, then rewind to the requested position and play unmuted.

const HAVE_FUTURE_DATA = 3;
const HAVE_ENOUGH_DATA = 4;

export function bufferedContains(el, time) {
  const b = el.buffered;
  if (!b || !b.length) return false;
  const t = Number.isFinite(time) ? time : 0;
  for (let i = 0; i < b.length; i++) {
    if (t >= b.start(i) && t <= b.end(i)) return true;
  }
  return false;
}

function seekTo(el, time) {
  const t = Number.isFinite(time) && time > 0 ? time : 0;
  try {
    el.currentTime = t;
  } catch {
    return Promise.resolve();
  }
  if (t === 0 && el.currentTime === 0) return Promise.resolve();
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      el.removeEventListener("seeked", onSeeked);
      clearTimeout(timer);
      resolve();
    };
    const onSeeked = () => finish();
    el.addEventListener("seeked", onSeeked);
    const timer = setTimeout(finish, 1500);
  });
}

export function waitUntilPlayable(
  el,
  { atTime = 0, softTimeoutMs = 3000, hardTimeoutMs = 20000 } = {}
) {
  const readyAtStart = () =>
    el.readyState >= HAVE_ENOUGH_DATA && bufferedContains(el, atTime);
  if (readyAtStart()) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    let soft = false;
    const timers = [];
    const cleanup = () => {
      timers.forEach((t) => clearTimeout(t));
      el.removeEventListener("canplaythrough", onThrough);
      el.removeEventListener("canplay", onCanPlay);
      el.removeEventListener("progress", onProgress);
      el.removeEventListener("error", onError);
    };
    const maybeResolve = () => {
      if (el.readyState >= HAVE_ENOUGH_DATA && bufferedContains(el, atTime)) {
        finish(resolve);
        return true;
      }
      return false;
    };
    const finish = (fn) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };
    const onThrough = () => finish(resolve);
    const onCanPlay = () => {
      if (soft && maybeResolve()) return;
      if (el.readyState >= HAVE_ENOUGH_DATA) maybeResolve();
    };
    const onProgress = () => {
      if (soft && maybeResolve()) return;
    };
    const onError = () => finish(() => reject(el.error || new Error("audio load error")));
    el.addEventListener("canplaythrough", onThrough);
    el.addEventListener("canplay", onCanPlay);
    el.addEventListener("progress", onProgress);
    el.addEventListener("error", onError);
    timers.push(
      setTimeout(() => {
        soft = true;
        if (maybeResolve()) return;
        if (el.readyState >= HAVE_FUTURE_DATA && bufferedContains(el, atTime)) {
          finish(resolve);
        }
      }, softTimeoutMs)
    );
    timers.push(
      setTimeout(() => {
        if (maybeResolve()) return;
        finish(resolve);
      }, hardTimeoutMs)
    );
  });
}

export function createBufferedStarter(el, opts = {}) {
  let seq = 0;

  function cancel() {
    seq += 1;
    el.muted = false;
  }

  async function start({ onLoading } = {}) {
    const mySeq = ++seq;
    const startAt = Number.isFinite(el.currentTime) ? el.currentTime : 0;
    const nearStart = startAt <= 0.05;
    const canPlayImmediately =
      !nearStart &&
      el.readyState >= HAVE_ENOUGH_DATA &&
      bufferedContains(el, startAt);
    if (canPlayImmediately) {
      el.muted = false;
      await el.play();
      return true;
    }
    if (onLoading) onLoading(true);
    el.muted = true;
    // Unlock playback inside the user gesture; audio is muted while buffering.
    let primed;
    try {
      primed = Promise.resolve(el.play()).catch(() => null);
    } catch {
      primed = Promise.resolve(null);
    }
    try {
      await waitUntilPlayable(el, { ...opts, atTime: startAt });
      await primed;
    } catch (err) {
      if (mySeq === seq) {
        el.muted = false;
        if (onLoading) onLoading(false);
      }
      throw err;
    }
    if (mySeq !== seq) return false;
    el.pause();
    await seekTo(el, startAt);
    el.muted = false;
    if (onLoading) onLoading(false);
    await el.play();
    return true;
  }

  return { start, cancel, isPriming: () => el.muted };
}