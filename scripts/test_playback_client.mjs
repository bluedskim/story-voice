import assert from "node:assert/strict";
import { pathToFileURL, fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const { createBufferedStarter, waitUntilPlayable } = await import(
  pathToFileURL(join(__dirname, "../web/playback.js")).href
);

class FakeAudio extends EventTarget {
  constructor() {
    super();
    this.readyState = 0;
    this.paused = true;
    this.muted = false;
    this.currentTime = 0;
    this.log = [];
  }
  play() {
    this.paused = false;
    this.log.push(`play muted=${this.muted} t=${this.currentTime.toFixed(2)}`);
    return Promise.resolve();
  }
  pause() {
    this.paused = true;
    this.log.push("pause");
  }
  fire(type, readyState) {
    if (readyState !== undefined) this.readyState = readyState;
    this.dispatchEvent(new Event(type));
  }
}

// Buffered already: plays immediately, unmuted.
{
  const a = new FakeAudio();
  a.readyState = 4;
  await createBufferedStarter(a).start();
  assert.deepEqual(a.log, ["play muted=false t=0.00"]);
}

// Not buffered: muted prime, wait for canplaythrough, rewind, unmuted play.
{
  const a = new FakeAudio();
  const states = [];
  const p = createBufferedStarter(a).start({ onLoading: (on) => states.push(on) });
  assert.equal(a.muted, true);
  a.currentTime = 0.3; // clock advanced while priming muted
  setTimeout(() => a.fire("canplaythrough", 4), 5);
  assert.equal(await p, true);
  assert.equal(a.muted, false);
  assert.equal(a.currentTime, 0);
  assert.deepEqual(states, [true, false]);
  assert.deepEqual(a.log, ["play muted=true t=0.00", "pause", "play muted=false t=0.00"]);
}

// Cancel while loading: no unmuted play happens.
{
  const a = new FakeAudio();
  const s = createBufferedStarter(a);
  const p = s.start();
  s.cancel();
  a.pause();
  a.fire("canplaythrough", 4);
  assert.equal(await p, false);
  assert.equal(a.muted, false);
  assert.ok(!a.log.includes("play muted=false t=0.00"));
}

// Soft timeout accepts HAVE_FUTURE_DATA.
{
  const a = new FakeAudio();
  a.readyState = 3;
  const t0 = Date.now();
  await waitUntilPlayable(a, { softTimeoutMs: 20, hardTimeoutMs: 1000 });
  assert.ok(Date.now() - t0 < 500);
}

// Load error rejects.
{
  const a = new FakeAudio();
  const p = waitUntilPlayable(a, { softTimeoutMs: 1000, hardTimeoutMs: 2000 });
  a.fire("error");
  await assert.rejects(p);
}

console.log("ok");
