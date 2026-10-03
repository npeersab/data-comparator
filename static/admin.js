// Data Comparator — admin page.
// Manages saved connections (create / edit / delete). The compare page only
// consumes these by id, so it never sees credentials. Reuses the existing
// /api/connections CRUD endpoints.

let connections = []; // cache of public saved connections
let editingId = null; // id being edited, or null for a new connection

// ---- DOM refs ----
const els = {
  form: document.getElementById("conn-form"),
  name: document.getElementById("f-name"),
  dialect: document.getElementById("f-dialect"),
  username: document.getElementById("f-username"),
  password: document.getElementById("f-password"),
  host: document.getElementById("f-host"),
  port: document.getElementById("f-port"),
  database: document.getElementById("f-database"),
  save: document.getElementById("f-save"),
  clear: document.getElementById("f-clear"),
  title: document.getElementById("form-title"),
  tbody: document.querySelector("#conn-table tbody"),
  empty: document.getElementById("list-empty"),
  status: document.getElementById("status"),
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
  fetch("/api/dialects")
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
    });
}

// ---- Form ----
function resetForm() {
  editingId = null;
  els.title.textContent = "New connection";
  els.save.textContent = "Save connection";
  els.form.reset();
  els.host.value = "localhost";
  initDialectSelect();
}

function fillForm(cfg) {
  editingId = cfg.id;
  els.title.textContent = "Edit connection";
  els.save.textContent = "Update connection";
  els.name.value = cfg.name;
  els.dialect.value = cfg.dialect;
  els.username.value = cfg.username || "";
  els.password.value = cfg.password || "";
  els.host.value = cfg.host || "localhost";
  els.port.value = cfg.port ?? "";
  els.database.value = cfg.database || "";
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
    database: els.database.value,
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
      resetForm();
      refreshList();
    })
    .catch((err) => setStatus(err.message || String(err), "error"));
});

els.clear.addEventListener("click", resetForm);

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
    tdDb.textContent = c.database;
    tr.appendChild(tdDb);

    const tdActions = document.createElement("td");
    tdActions.className = "actions";

    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "btn btn-outline btn-sm";
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", () => loadForEdit(c.id));

    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className = "btn btn-destructive btn-sm";
    delBtn.textContent = "Delete";
    delBtn.addEventListener("click", () => deleteConnection(c.id));

    tdActions.appendChild(editBtn);
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
      window.scrollTo({ top: 0, behavior: "smooth" });
    })
    .catch((err) => setStatus(err.message || String(err), "error"));
}

function deleteConnection(id) {
  fetch(`/api/connections/${id}`, { method: "DELETE" })
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      if (editingId === id) resetForm();
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
