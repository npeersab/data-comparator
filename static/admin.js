// Data Comparator — admin page.
// Manages saved connections (create / edit / delete). The compare page only
// consumes these by id, so it never sees credentials. Reuses the existing
// /api/connections CRUD endpoints.

let connections = []; // cache of public saved connections
let editingId = null; // id being edited, or null for a new connection
let pendingDeleteId = null; // id awaiting delete confirmation
let pendingDeleteName = null; // name of the connection awaiting deletion

// ---- DOM refs ----
const els = {
  form: document.getElementById("conn-form"),
  name: document.getElementById("f-name"),
  dialect: document.getElementById("f-dialect"),
  username: document.getElementById("f-username"),
  password: document.getElementById("f-password"),
  host: document.getElementById("f-host"),
  port: document.getElementById("f-port"),
  save: document.getElementById("f-save"),
  test: document.getElementById("f-test"),
  modalStatus: document.getElementById("f-status"),
  title: document.getElementById("modal-title"),
  modal: document.getElementById("conn-modal"),
  panel: document.getElementById("modal-panel"),
  close: document.getElementById("modal-close"),
  tbody: document.querySelector("#conn-table tbody"),
  empty: document.getElementById("list-empty"),
  status: document.getElementById("status"),
  confirmModal: document.getElementById("confirm-modal"),
  confirmPanel: document.getElementById("confirm-panel"),
  confirmMessage: document.getElementById("confirm-message"),
  confirmClose: document.getElementById("confirm-close"),
  confirmCancel: document.getElementById("confirm-cancel"),
  confirmDelete: document.getElementById("confirm-delete"),
};

function setStatus(msg, kind = "info") {
  els.status.hidden = false;
  els.status.className = `status ${kind}`;
  els.status.textContent = msg;
}
function clearStatus() {
  els.status.hidden = true;
}

// ---- Dialect select ----
function initDialectSelect() {
  return fetch("/api/dialects")
    .then((r) => r.json())
    .then((data) => {
      els.dialect.innerHTML = "";
      data.dialects.forEach((d) => {
        const opt = document.createElement("option");
        opt.value = d;
        opt.textContent = d;
        els.dialect.appendChild(opt);
      });
      els.dialect.value = data.dialects.includes("postgresql")
        ? "postgresql"
        : data.dialects[0];
      return data;
    });
}

// ---- Modal ----
let lastFocused = null;

function openModal(mode, cfg) {
  editingId = mode === "edit" ? cfg.id : null;
  els.title.textContent = mode === "edit" ? "Edit connection" : "New connection";
  els.save.textContent = mode === "edit" ? "Update connection" : "Save connection";
  els.form.reset();
  els.host.value = "localhost";
  lastFocused = document.activeElement;

  // Populate dialects first, then apply field values so the edit dialect
  // selection lands on a real option.
  initDialectSelect().then(() => {
    if (mode === "edit") {
      els.name.value = cfg.name;
      els.dialect.value = cfg.dialect;
      els.username.value = cfg.username || "";
      els.password.value = cfg.password || "";
      els.host.value = cfg.host || "localhost";
      els.port.value = cfg.port ?? "";
    }
  });

  els.modal.hidden = false;
  document.body.style.overflow = "hidden";
  els.close.focus();
}

function closeModal() {
  els.modal.hidden = true;
  editingId = null;
  document.body.style.overflow = "";
  if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
}

function fillForm(cfg) {
  openModal("edit", cfg);
}

els.form.addEventListener("submit", (e) => {
  e.preventDefault();
  const name = els.name.value.trim();
  if (!name) {
    setStatus("A name is required.", "error");
    els.name.focus();
    return;
  }
  const portText = els.port.value.trim();
  const payload = {
    name,
    dialect: els.dialect.value,
    username: els.username.value,
    password: els.password.value,
    host: els.host.value,
    port: portText ? Number(portText) : null,
  };
  // Create goes through the upsert endpoint; an edit targets the preset by id,
  // so renaming a connection in place does not create a duplicate row.
  const url = editingId ? `/api/connections/${editingId}` : "/api/connections";
  const method = editingId ? "PUT" : "POST";

  fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(async (r) => {
      if (!r.ok) {
        const detail = await r
          .json()
          .then((j) => j.detail)
          .catch(() => null);
        throw new Error(detail || "Save failed");
      }
      clearStatus();
      closeModal();
      refreshList();
    })
    .catch((err) => setStatus(err.message || String(err), "error"));
});

// Show a result banner inside the modal (the opaque backdrop hides the
// page-level status). kind is "success" or "error".
function showStatus(msg, kind) {
  els.modalStatus.hidden = false;
  els.modalStatus.className = `status ${kind}`;
  els.modalStatus.textContent = msg;
}
function clearStatus() {
  els.modalStatus.hidden = true;
  els.modalStatus.className = "status";
}

// Validate the live form fields against the server without saving.
function testConnection() {
  const portText = els.port.value.trim();
  const payload = {
    dialect: els.dialect.value,
    username: els.username.value,
    password: els.password.value,
    host: els.host.value,
    port: portText ? Number(portText) : null,
  };
  els.test.disabled = true;
  clearStatus();
  fetch("/api/connections/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
    .then(async (r) => {
      const result = await r
        .json()
        .catch(() => ({ ok: false, error: "Request failed" }));
      if (!result.ok) throw new Error(result.error || "Connection test failed");
      showStatus("Connection successful.", "success");
    })
    .catch((err) => showStatus(err.message || String(err), "error"))
    .finally(() => {
      els.test.disabled = false;
      els.test.focus();
    });
}
els.test.addEventListener("click", testConnection);

// ---- Modal wiring ----
document
  .getElementById("add-connection")
  .addEventListener("click", () => openModal("new"));
els.close.addEventListener("click", closeModal);
// Clicking the backdrop (outside the panel) closes the modal.
els.modal.addEventListener("click", (e) => {
  if (!els.panel.contains(e.target)) closeModal();
});
// Escape closes either modal.
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!els.modal.hidden) closeModal();
    if (!els.confirmModal.hidden) cancelDelete();
  }
});

// Delete confirmation modal wiring.
els.confirmClose.addEventListener("click", cancelDelete);
els.confirmCancel.addEventListener("click", cancelDelete);
els.confirmDelete.addEventListener("click", performDelete);
// Clicking the backdrop (outside the panel) cancels.
els.confirmModal.addEventListener("click", (e) => {
  if (!els.confirmPanel.contains(e.target)) cancelDelete();
});

// ---- List ----
function refreshList() {
  fetch("/api/connections")
    .then((r) => r.json())
    .then((list) => {
      connections = list;
      renderList(list);
    });
}

function renderList(list) {
  els.tbody.innerHTML = "";
  els.empty.hidden = list.length > 0;
  list.forEach((c) => {
    const tr = document.createElement("tr");

    const tdName = document.createElement("td");
    tdName.textContent = c.name;
    tr.appendChild(tdName);

    const tdDialect = document.createElement("td");
    tdDialect.textContent = c.dialect;
    tr.appendChild(tdDialect);

    const tdHost = document.createElement("td");
    tdHost.textContent = c.port ? `${c.host}:${c.port}` : c.host;
    tr.appendChild(tdHost);

    const tdDb = document.createElement("td");
    const dbs = c.databases || [];
    tdDb.textContent = dbs.length ? String(dbs.length) : "—";
    tdDb.title = dbs.length ? dbs.join(", ") : "Not enumerated yet";
    tr.appendChild(tdDb);

    const tdActions = document.createElement("td");
    tdActions.className = "actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-outline btn-sm";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => loadForEdit(c.id));

    const refreshBtn = document.createElement("button");
    refreshBtn.type = "button";
    refreshBtn.className = "btn btn-outline btn-sm";
    refreshBtn.textContent = "Refresh Databases";
    refreshBtn.addEventListener("click", () => refreshDatabases(c.id));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn btn-destructive btn-sm";
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", () => confirmDelete(c.id, c.name));

    tdActions.appendChild(editBtn);
    tdActions.appendChild(refreshBtn);
    tdActions.appendChild(delBtn);
    tr.appendChild(tdActions);
    els.tbody.appendChild(tr);
  });
}

function loadForEdit(id) {
  fetch(`/api/connections/${id}`)
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then((cfg) => {
      clearStatus();
      fillForm(cfg);
    })
    .catch((err) => setStatus(err.message || String(err), "error"));
}

function confirmDelete(id, name) {
  pendingDeleteId = id;
  pendingDeleteName = name;
  const label = name ? `"${name}"` : "this connection";
  els.confirmMessage.textContent =
    `Are you sure you want to delete ${label}? This removes the saved connection and cannot be undone.`;
  els.confirmModal.hidden = false;
  document.body.style.overflow = "hidden";
  lastFocused = document.activeElement;
  els.confirmDelete.focus();
}

function cancelDelete() {
  pendingDeleteId = null;
  pendingDeleteName = null;
  els.confirmModal.hidden = true;
  document.body.style.overflow = "";
  if (lastFocused && typeof lastFocused.focus === "function") lastFocused.focus();
}

function performDelete() {
  const id = pendingDeleteId;
  cancelDelete();
  if (id == null) return;
  fetch(`/api/connections/${id}`, { method: "DELETE" })
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (editingId === id) closeModal();
      clearStatus();
      refreshList();
    })
    .catch((err) => setStatus(err.message || String(err), "error"));
}

// Re-enumerate a preset's databases from the server and store the list.
function refreshDatabases(id) {
  fetch(`/api/connections/${id}/databases/refresh`, { method: "POST" })
    .then(async (r) => {
      if (!r.ok) {
        const detail = await r.json().then((j) => j.detail).catch(() => null);
        throw new Error(detail || "Refresh failed");
      }
      clearStatus();
      refreshList();
    })
    .catch((err) => setStatus(err.message || String(err), "error"));
}

initDialectSelect();
refreshList();

// ---- Theme toggle (shadcn / next-themes parity: system default, explicit toggle) ----
const THEME_KEY = "data-comparator-theme";
const htmlEl = document.documentElement;
const mediaQuery = window.matchMedia("(prefers-color-scheme: dark)");

function resolveTheme(stored) {
  if (stored === "light" || stored === "dark") return stored;
  return mediaQuery.matches ? "dark" : "light";
}
function applyTheme(theme) {
  htmlEl.classList.toggle("dark", theme === "dark");
}

(function initTheme() {
  const stored = localStorage.getItem(THEME_KEY) || "system";
  applyTheme(resolveTheme(stored));
  mediaQuery.addEventListener?.("change", (e) => {
    if ((localStorage.getItem(THEME_KEY) || "system") === "system") {
      applyTheme(e.matches ? "dark" : "light");
    }
  });
})();

const themeToggle = document.getElementById("theme-toggle");
if (themeToggle) {
  themeToggle.addEventListener("click", () => {
    const next = htmlEl.classList.contains("dark") ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  });
}

// ---- Active nav link ----
(function initNav() {
  const path = window.location.pathname;
  document.querySelectorAll(".nav-link").forEach((link) => {
    const href = link.getAttribute("href");
    const matches = href === "/" ? path === "/" : path.startsWith(href);
    link.setAttribute("aria-current", matches ? "page" : "none");
  });
})();
