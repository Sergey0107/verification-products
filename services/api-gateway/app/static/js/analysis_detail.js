const table = document.querySelector(".table");
const modal = document.querySelector("[data-comment-modal]");
const form = document.querySelector("[data-comment-form]");
const statusPill = document.querySelector("[data-comment-status]");
const saveResultsButton = document.querySelector("[data-save-user-results]");

const fields = {
  characteristic: document.querySelector('[data-field="characteristic"]'),
  tzValue: document.querySelector('[data-field="tz_value"]'),
  passportValue: document.querySelector('[data-field="passport_value"]'),
};

let activeRowId = null;
let activeRow = null;
const pendingUserResults = new Map();

const openModal = (row) => {
  activeRowId = row.getAttribute("data-row-id");
  activeRow = row;
  if (fields.characteristic) {
    fields.characteristic.textContent = row.getAttribute("data-characteristic") || "";
  }
  if (fields.tzValue) {
    fields.tzValue.textContent = row.getAttribute("data-tz-value") || "";
  }
  if (fields.passportValue) {
    fields.passportValue.textContent = row.getAttribute("data-passport-value") || "";
  }
  if (form) {
    const comment = row.getAttribute("data-comment") || "";
    const textarea = form.querySelector("textarea");
    if (textarea) {
      textarea.value = comment;
    }
  }
  if (statusPill) {
    statusPill.hidden = true;
  }
  if (modal) {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }
};

const closeModal = () => {
  if (modal) {
    modal.hidden = true;
    document.body.style.overflow = "";
  }
  activeRowId = null;
  activeRow = null;
};

if (modal) {
  const closeTargets = modal.querySelectorAll("[data-close]");
  closeTargets.forEach((target) => target.addEventListener("click", closeModal));
}

if (table) {
  table.addEventListener("click", (event) => {
    const button = event.target.closest("[data-open-comment]");
    if (!button) return;
    const row = button.closest("[data-row-id]");
    if (!row) return;
    openModal(row);
  });

  table.addEventListener("change", async (event) => {
    const checkbox = event.target.closest("[data-user-result]");
    if (!checkbox) return;
    const row = checkbox.closest("[data-row-id]");
    if (!row) return;
    const rowId = row.getAttribute("data-row-id");
    if (!rowId) return;
    pendingUserResults.set(rowId, checkbox.checked);
    if (saveResultsButton) {
      saveResultsButton.disabled = pendingUserResults.size === 0;
    }
  });
}

if (form) {
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!activeRowId) return;
    const formData = new FormData(form);
    const comment = formData.get("comment");
    if (!comment) return;
    const response = await fetch(`/api/comparison-rows/${activeRowId}/comment`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ comment }),
    });
    if (response.ok) {
      if (activeRow) {
        activeRow.setAttribute("data-comment", comment);
      }
      if (statusPill) {
        statusPill.hidden = false;
        setTimeout(() => {
          if (statusPill) statusPill.hidden = true;
        }, 1200);
      }
      setTimeout(closeModal, 200);
    }
  });
}

if (saveResultsButton) {
  saveResultsButton.addEventListener("click", async () => {
    if (pendingUserResults.size === 0) return;
    const entries = Array.from(pendingUserResults.entries());
    await Promise.all(
      entries.map(([rowId, value]) =>
        fetch(`/api/comparison-rows/${rowId}/user-result`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ user_result: value }),
        })
      )
    );
    pendingUserResults.clear();
    saveResultsButton.disabled = true;
  });
}

window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeModal();
  }
});
