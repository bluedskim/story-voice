// Buffer-aware playback start for the story player.
//
// Calling audio.play() before enough data is buffered lets the browser start
// the clock, stall, and resume — the first syllables sound clipped. We prime
// the element muted (keeps the user-gesture unlock on iOS), wait until it can
// play through, then rewind to the requested position and play unmuted.

const HAVE_FUTURE_DATA = 3;
const HAVE_ENOUGH_DATA = 4;

export function waitUntilPlayable(el, { softTimeoutMs = 3000, hardTimeoutMs = 20000 } = {}) {
  if (el.readyState >= HAVE_ENOUGH_DATA) return Promise.resolve();
  return new Promise((resolve, reject) => {
    let settled = false;
    let soft = false;
    const timers = [];
    const cleanup = () => {
      timers.forEach((t) => clearTimeout(t));
      el.removeEventListener("canplaythrough", onThrough);
      el.removeEventListener("canplay", onCanPlay);
      el.removeEventListener("error", onError);
    };
    const finish = (fn) => {
      if (settled) return;
      settled = true;
      cleanup();
      fn();
    };
    const onThrough = () => finish(resolve);
    const onCanPlay = () => {
      if (soft) finish(resolve);
    };
    const onError = () => finish(() => reject(el.error || new Error("audio load error")));
    el.addEventListener("canplaythrough", onThrough);
    el.addEventListener("canplay", onCanPlay);
    el.addEventListener("error", onError);
    timers.push(
      setTimeout(() => {
        soft = true;
        if (el.readyState >= HAVE_FUTURE_DATA) finish(resolve);
      }, softTimeoutMs)
    );
    timers.push(setTimeout(() => finish(resolve), hardTimeoutMs));
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
    if (el.readyState >= HAVE_ENOUGH_DATA) {
      el.muted = false;
      await el.play();
      return true;
    }
    const startAt = Number.isFinite(el.currentTime) ? el.currentTime : 0;
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
      await waitUntilPlayable(el, opts);
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
    try {
      el.currentTime = startAt;
    } catch {
      /* not seekable yet; keep position */
    }
    el.muted = false;
    if (onLoading) onLoading(false);
    await el.play();
    return true;
  }

  return { start, cancel, isPriming: () => el.muted };
}
