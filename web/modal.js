/** @typedef {{ label: string, primary?: boolean, onClick?: () => void }} AlertButton */

/** @type {HTMLDialogElement | null} */
let alertModal = null;
/** @type {HTMLElement | null} */
let alertTitleEl = null;
/** @type {HTMLElement | null} */
let alertMessageEl = null;
/** @type {HTMLElement | null} */
let alertActionsEl = null;

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
