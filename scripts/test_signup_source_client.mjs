import assert from "node:assert/strict";
import { pathToFileURL } from "node:url";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const modUrl = pathToFileURL(join(__dirname, "../web/signup-source.js")).href;

class MemoryStorage {
  constructor() {
    this.data = new Map();
  }
  getItem(key) {
    return this.data.has(key) ? this.data.get(key) : null;
  }
  setItem(key, value) {
    this.data.set(key, String(value));
  }
  removeItem(key) {
    this.data.delete(key);
  }
}

globalThis.localStorage = new MemoryStorage();
globalThis.window = { location: { search: "" } };

const {
  captureSignupSourceFromUrl,
  getStoredSignupSource,
  clearStoredSignupSource,
  resolveSignupSourceFromParams,
  normalizeSignupSource,
} = await import(modUrl);

assert.equal(normalizeSignupSource("Foo-Bar"), "foo-bar");
assert.equal(
  resolveSignupSourceFromParams(new URLSearchParams("utm_source=a&ref=b")),
  "a",
);
assert.equal(
  resolveSignupSourceFromParams(new URLSearchParams("ref=b")),
  "b",
);
assert.equal(
  resolveSignupSourceFromParams(new URLSearchParams("src=ignored&ref=b")),
  "b",
);

window.location.search = "?ref=Friend_Link";
captureSignupSourceFromUrl();
assert.equal(getStoredSignupSource(), "friend_link");

window.location.search = "?utm_source=other";
captureSignupSourceFromUrl();
assert.equal(getStoredSignupSource(), "friend_link");

clearStoredSignupSource();
assert.equal(getStoredSignupSource(), null);

console.log("OK: signup_source client tests");
