/** @typedef {{ nickname: string, canWrite: boolean }} AuthUser */

let csrfToken = "";
let authUser = /** @type {AuthUser | null} */ (null);
let authEmailDevMode = false;
const listeners = new Set();

export function onAuthChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function notify() {
  listeners.forEach((fn) => fn(authUser));
}

export function getAuthUser() {
  return authUser;
}

export function canWrite() {
  return Boolean(authUser?.canWrite);
}

export function isAuthEmailDevMode() {
  return authEmailDevMode;
}

export function getCsrfToken() {
  return csrfToken;
}

export async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (csrfToken && options.method && options.method !== "GET") {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const res = await fetch(url, {
    ...options,
    headers,
    credentials: "same-origin",
  });
  return res;
}

export async function refreshAuthFromConfig() {
  const res = await fetch("/api/config", { cache: "no-store", credentials: "same-origin" });
  if (!res.ok) throw new Error("config");
  const data = await res.json();
  csrfToken = data.csrfToken || "";
  authEmailDevMode = Boolean(data.authEmailDevMode);
  authUser = data.user || null;
  notify();
  return data;
}

export async function refreshMe() {
  const res = await apiFetch("/api/auth/me");
  if (!res.ok) return null;
  const data = await res.json();
  authUser = data.user || null;
  notify();
  return authUser;
}

export async function login(loginId, password) {
  const res = await apiFetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loginId, password }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "로그인에 실패했어요.");
  authUser = data.user || null;
  await refreshAuthFromConfig();
  notify();
  return authUser;
}

export async function logout() {
  await apiFetch("/api/auth/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  authUser = null;
  await refreshAuthFromConfig();
  notify();
}

export async function sendVerificationCode(loginId) {
  const res = await apiFetch("/api/users/signup/send-verification", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ loginId }),
  });
  if (res.status === 204) return;
  const data = await res.json().catch(() => ({}));
  const err = new Error(data.error || "인증코드를 보내지 못했어요.");
  if (data.retryAfterSec) err.retryAfterSec = data.retryAfterSec;
  throw err;
}

export async function signup(payload) {
  const res = await apiFetch("/api/users/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "회원가입에 실패했어요.");
  return data;
}

export async function checkNickname(nickname) {
  const params = new URLSearchParams({ nickname });
  const res = await fetch(`/api/users/nickname-available?${params}`, { credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "닉네임을 확인하지 못했어요.");
  return data.available;
}

export function initAuthUi() {
  const bar = document.getElementById("auth-bar");
  const loginBtn = document.getElementById("auth-login-btn");
  const signupBtn = document.getElementById("auth-signup-btn");
  const logoutBtn = document.getElementById("auth-logout-btn");
  const userLabel = document.getElementById("auth-user-label");
  const loginModal = document.getElementById("modal-login");
  const signupModal = document.getElementById("modal-signup");

  function renderBar() {
    if (!bar) return;
    const loggedIn = Boolean(authUser);
    loginBtn.hidden = loggedIn;
    signupBtn.hidden = loggedIn;
    logoutBtn.hidden = !loggedIn;
    userLabel.hidden = !loggedIn;
    if (loggedIn) {
      userLabel.textContent = authUser.nickname;
    }
  }

  onAuthChange(renderBar);

  function openModal(el) {
    el.hidden = false;
    document.body.classList.add("modal-open");
  }
  function closeModal(el) {
    el.hidden = true;
    document.body.classList.remove("modal-open");
  }

  loginBtn?.addEventListener("click", () => openModal(loginModal));
  signupBtn?.addEventListener("click", () => openModal(signupModal));
  document.querySelectorAll("[data-close-modal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      closeModal(loginModal);
      closeModal(signupModal);
    });
  });

  document.getElementById("login-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = document.getElementById("login-error");
    err.textContent = "";
    try {
      await login(
        document.getElementById("login-email").value.trim(),
        document.getElementById("login-password").value
      );
      closeModal(loginModal);
    } catch (ex) {
      err.textContent = ex.message;
    }
  });

  const nickInput = document.getElementById("signup-nickname");
  const nickStatus = document.getElementById("signup-nickname-status");
  let nickTimer;
  nickInput?.addEventListener("input", () => {
    clearTimeout(nickTimer);
    nickTimer = setTimeout(async () => {
      const n = nickInput.value.trim();
      if (!n) {
        nickStatus.textContent = "";
        return;
      }
      try {
        const ok = await checkNickname(n);
        nickStatus.textContent = ok ? "사용할 수 있어요" : "이미 사용 중이에요";
        nickStatus.className = ok ? "auth-nick ok" : "auth-nick bad";
      } catch {
        nickStatus.textContent = "확인하지 못했어요";
        nickStatus.className = "auth-nick bad";
      }
    }, 400);
  });

  const sendCodeBtn = document.getElementById("signup-send-code");
  let signupCooldownTimer = null;

  function startSignupCooldown(seconds) {
    if (!sendCodeBtn) return;
    sendCodeBtn.disabled = true;
    let remaining = seconds;
    sendCodeBtn.textContent = `다시 보내기 (${remaining}초)`;
    if (signupCooldownTimer) clearInterval(signupCooldownTimer);
    signupCooldownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(signupCooldownTimer);
        signupCooldownTimer = null;
        sendCodeBtn.disabled = false;
        sendCodeBtn.textContent = "인증코드 보내기";
        return;
      }
      sendCodeBtn.textContent = `다시 보내기 (${remaining}초)`;
    }, 1000);
  }

  sendCodeBtn?.addEventListener("click", async () => {
    const err = document.getElementById("signup-error");
    const dev = document.getElementById("signup-dev-hint");
    err.textContent = "";
    dev.hidden = !authEmailDevMode;
    if (authEmailDevMode) {
      dev.textContent = "개발 모드: 인증코드는 서버 로그에 출력됩니다.";
    }
    try {
      await sendVerificationCode(document.getElementById("signup-email").value.trim());
      document.getElementById("signup-code-wrap").hidden = false;
      err.textContent = "인증코드를 보냈어요. 메일함을 확인해 주세요.";
      err.className = "auth-msg ok";
      startSignupCooldown(60);
    } catch (ex) {
      err.textContent = ex.message;
      err.className = "auth-msg error";
      if (ex.retryAfterSec) startSignupCooldown(ex.retryAfterSec);
    }
  });

  document.getElementById("signup-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const err = document.getElementById("signup-error");
    err.textContent = "";
    err.className = "auth-msg error";
    const pw = document.getElementById("signup-password").value;
    const pw2 = document.getElementById("signup-password2").value;
    if (pw !== pw2) {
      err.textContent = "비밀번호가 서로 달라요.";
      return;
    }
    try {
      await signup({
        loginId: document.getElementById("signup-email").value.trim(),
        nickname: document.getElementById("signup-nickname").value.trim(),
        password: pw,
        verificationCode: document.getElementById("signup-code").value.trim(),
      });
      closeModal(signupModal);
      openModal(loginModal);
      document.getElementById("login-email").value = document.getElementById("signup-email").value.trim();
      err.textContent = "";
      document.getElementById("login-error").textContent = "가입했어요. 로그인해 주세요.";
    } catch (ex) {
      err.textContent = ex.message;
    }
  });

  logoutBtn?.addEventListener("click", () => logout().catch(() => {}));
  document.getElementById("signup-to-login")?.addEventListener("click", () => {
    closeModal(signupModal);
    openModal(loginModal);
  });
  document.getElementById("login-to-signup")?.addEventListener("click", () => {
    closeModal(loginModal);
    openModal(signupModal);
  });

  renderBar();
}
