/** @typedef {{ label: string, primary?: boolean, onClick?: () => void }} AlertButton */

/** @type {HTMLDialogElement | null} */
let alertModal = null;
/** @type {HTMLElement | null} */
let alertTitleEl = null;
/** @type {HTMLElement | null} */
let alertMessageEl = null;
/** @type {HTMLElement | null} */
let alertActionsEl = null;

/** @type {HTMLDialogElement | null} */
let promptModal = null;
/** @type {HTMLElement | null} */
let promptTitleEl = null;
/** @type {HTMLElement | null} */
let promptMessageEl = null;
/** @type {HTMLInputElement | null} */
let promptInputEl = null;
/** @type {HTMLElement | null} */
let promptErrorEl = null;
/** @type {HTMLButtonElement | null} */
let promptConfirmBtn = null;
/** @type {HTMLButtonElement | null} */
let promptCancelBtn = null;
/** @type {((value: string | null) => void) | null} */
let promptResolve = null;

function anyModalVisible() {
  return Boolean(document.querySelector(".auth-modal:not([hidden])"));
}

export function openModal(el) {
  if (!el) return;
  el.hidden = false;
  document.body.classList.add("modal-open");
}

export function closeModal(el) {
  if (!el) return;
  el.hidden = true;
  if (!anyModalVisible()) {
    document.body.classList.remove("modal-open");
  }
}

function ensureAlertElements() {
  if (alertModal) return;
  alertModal = document.getElementById("modal-alert");
  alertTitleEl = document.getElementById("alert-modal-title");
  alertMessageEl = document.getElementById("alert-modal-message");
  alertActionsEl = document.getElementById("alert-modal-actions");
  if (!alertModal || alertModal.dataset.bound) return;
  alertModal.dataset.bound = "1";
  alertModal.addEventListener("click", (e) => {
    if (e.target === alertModal) closeModal(alertModal);
  });
}

/**
 * @param {{ title?: string, message: string, buttons?: AlertButton[] }} opts
 */
export function showAlertModal({ title = "알림", message, buttons }) {
  ensureAlertElements();
  if (!alertModal || !alertTitleEl || !alertMessageEl || !alertActionsEl) return;

  alertTitleEl.textContent = title;
  alertMessageEl.textContent = message;
  alertActionsEl.replaceChildren();

  const list = buttons?.length ? buttons : [{ label: "닫기" }];
  for (const btn of list) {
    const el = document.createElement("button");
    el.type = "button";
    el.className = `btn btn-wide ${btn.primary ? "btn-primary" : "btn-secondary"}`;
    el.textContent = btn.label;
    el.addEventListener("click", () => {
      closeModal(alertModal);
      btn.onClick?.();
    });
    alertActionsEl.appendChild(el);
  }

  openModal(alertModal);
}

export function initAlertModal() {
  ensureAlertElements();
}

function ensurePromptElements() {
  if (promptModal) return;
  promptModal = document.getElementById("modal-prompt");
  promptTitleEl = document.getElementById("prompt-modal-title");
  promptMessageEl = document.getElementById("prompt-modal-message");
  promptInputEl = document.getElementById("prompt-modal-input");
  promptErrorEl = document.getElementById("prompt-modal-error");
  promptConfirmBtn = document.getElementById("prompt-modal-confirm");
  promptCancelBtn = document.getElementById("prompt-modal-cancel");
  if (!promptModal || promptModal.dataset.bound) return;
  promptModal.dataset.bound = "1";
  promptModal.addEventListener("click", (e) => {
    if (e.target === promptModal) finishPrompt(null);
  });
  promptCancelBtn?.addEventListener("click", () => finishPrompt(null));
  promptConfirmBtn?.addEventListener("click", () => submitPrompt());
  promptInputEl?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      submitPrompt();
    }
    if (e.key === "Escape") {
      e.preventDefault();
      finishPrompt(null);
    }
  });
}

function finishPrompt(value) {
  if (!promptModal) return;
  closeModal(promptModal);
  const resolve = promptResolve;
  promptResolve = null;
  resolve?.(value);
}

function submitPrompt() {
  if (!promptInputEl) return;
  const value = promptInputEl.value.trim();
  if (!value) {
    if (promptErrorEl) {
      promptErrorEl.textContent = "이름을 입력해 주세요.";
      promptErrorEl.hidden = false;
    }
    promptInputEl.focus();
    return;
  }
  if (promptInputEl.maxLength > 0 && value.length > promptInputEl.maxLength) {
    if (promptErrorEl) {
      promptErrorEl.textContent = `이름은 ${promptInputEl.maxLength}자 이하여야 해요.`;
      promptErrorEl.hidden = false;
    }
    return;
  }
  finishPrompt(value);
}

/**
 * @param {{ title?: string, message?: string, defaultValue?: string, confirmLabel?: string, maxLength?: number }} opts
 * @returns {Promise<string | null>}
 */
export function showPromptModal({
  title = "이름",
  message = "",
  defaultValue = "",
  confirmLabel = "저장",
  maxLength = 20,
} = {}) {
  ensurePromptElements();
  if (!promptModal || !promptTitleEl || !promptInputEl || !promptConfirmBtn) {
    return Promise.resolve(null);
  }
  return new Promise((resolve) => {
    promptResolve = resolve;
    promptTitleEl.textContent = title;
    if (promptMessageEl) {
      promptMessageEl.textContent = message;
      promptMessageEl.hidden = !message;
    }
    if (promptErrorEl) {
      promptErrorEl.textContent = "";
      promptErrorEl.hidden = true;
    }
    promptInputEl.value = defaultValue;
    promptInputEl.maxLength = maxLength;
    if (promptConfirmBtn) promptConfirmBtn.textContent = confirmLabel;
    openModal(promptModal);
    promptInputEl.focus();
    promptInputEl.select();
  });
}
