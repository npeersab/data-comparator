// Data Comparator frontend.
// The compare page only reuses *saved* connections (managed on the /admin page),
// so it never handles connection credentials. It uses fetch + ReadableStream
// (not EventSource) so we can POST the request body and still receive a
// streaming Server-Side-Events response.

let connections = []; // cache of public saved connections from /api/connections
let currentPayload = null; // last "result" payload, used for exports

// ---- DOM refs ----
const els = {
  sSaved: document.getElementById("s-saved"),
  tSaved: document.getElementById("t-saved"),
  sDatabase: document.getElementById("s-database"),
  tDatabase: document.getElementById("t-database"),
  sQuery: document.getElementById("s-query"),
  tQuery: document.getElementById("t-query"),

  maxMismatch: document.getElementById("max-mismatch"),
  run: document.getElementById("run"),
  reset: document.getElementById("reset"),
  status: document.getElementById("status"),
  results: document.getElementById("results"),
  counts: document.getElementById("counts"),
  tbody: document.querySelector("#mismatch-table tbody"),
  exportCsv: document.getElementById("export-csv"),
  exportJson: document.getElementById("export-json"),
};

function setStatus(msg, kind = "info") {
  els.status.hidden = false;
  els.status.className = `status ${kind}`;
  els.status.textContent = msg;
}
function clearStatus() {
  els.status.hidden = true;
}

// ---- Saved connections ----
function refreshConnections() {
  fetch("/api/connections")
    .then((r) => r.json())
    .then((list) => {
      connections = list;
      populateSelect(els.sSaved, list);
      populateSelect(els.tSaved, list);
      // No connection chosen yet: show the placeholder, never a blank dropdown.
      populateDatabaseSelect(els.sDatabase, null);
      populateDatabaseSelect(els.tDatabase, null);
    })
    .catch(() => {
      populateSelect(els.sSaved, []);
      populateSelect(els.tSaved, []);
      populateDatabaseSelect(els.sDatabase, null);
      populateDatabaseSelect(els.tDatabase, null);
    });
}

function populateSelect(sel, list) {
  sel.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = list.length
    ? "(select a connection)"
    : "(no saved connections — go to Admin)";
  sel.appendChild(none);
  list.forEach((c) => {
    const opt = document.createElement("option");
    opt.value = String(c.id);
    opt.textContent = `${c.name} (${c.dialect})`;
    sel.appendChild(opt);
  });
}

function findConn(id) {
  return id ? connections.find((c) => c.id === Number(id)) : null;
}

// Populate a side's database <select> from the list cached on the connection
// (enumerated server-side on save / refresh). No extra fetch, no credentials.
// When `conn` is null (no connection selected yet) it shows a placeholder and
// no options, so the dropdown is never blank.
function populateDatabaseSelect(sel, conn) {
  sel.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.disabled = true;
  none.selected = true;
  if (!conn) {
    none.textContent = "(select a connection first)";
  } else {
    const dbs = conn.databases || [];
    none.textContent = dbs.length
      ? "(select a database)"
      : "(no databases — check Admin)";
  }
  // Placeholder first (it is the selected default), then the real options.
  sel.appendChild(none);
  if (conn) {
    (conn.databases || []).forEach((d) => {
      const opt = document.createElement("option");
      opt.value = d;
      opt.textContent = d;
      sel.appendChild(opt);
    });
  }
}

function escapeHtml(s) {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

els.sSaved.addEventListener("change", () => {
  populateDatabaseSelect(els.sDatabase, findConn(els.sSaved.value));
});
els.tSaved.addEventListener("change", () => {
  populateDatabaseSelect(els.tDatabase, findConn(els.tSaved.value));
});

// ---- SSE parsing over a fetch ReadableStream ----
async function streamCompare(body, onEvent, onDone) {
  const resp = await fetch("/api/compare/saved", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail || detail;
    } catch {
      /* ignore */
    }
    throw new Error(`Request failed (${resp.status}): ${detail}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let type = "message";
  let data = "";

  function dispatch() {
    let payload = data.trim();
    try {
      payload = payload ? JSON.parse(payload) : payload;
    } catch {
      /* keep raw string */
    }
    onEvent(type, payload);
    type = "message";
    data = "";
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).replace(/\r$/, "");
      buffer = buffer.slice(idx + 1);
      if (line === "") {
        if (type !== "message" || data) dispatch();
        continue;
      }
      if (line.startsWith("event:")) {
        type = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        data += line.slice(5).trim() + "\n";
      }
    }
  }
  if (type !== "message" || data) dispatch();
  onDone();
}

// ---- Rendering ----
function renderCounts(p) {
  const srcMismatch = p.source_mismatches.length;
  const tgtMismatch = p.target_mismatches.length;
  const matched = p.source_scanned - srcMismatch;
  const rows = [
    `Source scanned: <b>${p.source_scanned}</b>`,
    `Target scanned: <b>${p.target_scanned}</b>`,
    `Matched: <b>${matched}</b>`,
    `Source-only mismatches: <b class="src">${srcMismatch}</b>`,
    `Target-only mismatches: <b class="tgt">${tgtMismatch}</b>`,
  ];
  if (p.truncated) {
    rows.push(`<span class="warn">Truncated at max_mismatch_size = ${p.max_mismatch_size}</span>`);
  }
  els.counts.innerHTML = rows.join(" &nbsp;•&nbsp; ");
}

function renderTable(p) {
  els.tbody.innerHTML = "";
  const frag = document.createDocumentFragment();
  const LIMIT = 1000;

  p.source_mismatches.forEach((row) => {
    frag.appendChild(makeRow("source", row));
  });
  p.target_mismatches.forEach((row) => {
    frag.appendChild(makeRow("target", row));
  });
  els.tbody.appendChild(frag);

  const total = p.source_mismatches.length + p.target_mismatches.length;
  if (total > LIMIT) {
    const note = document.createElement("p");
    note.className = "warn";
    note.textContent = `Showing first ${LIMIT} of ${total} mismatches. Use Export for the full list.`;
    els.tbody.parentElement.parentNode.insertBefore(note, els.tbody.parentElement.nextSibling);
  }
}

function makeRow(side, values) {
  const tr = document.createElement("tr");
  const tdSide = document.createElement("td");
  tdSide.className = side;
  tdSide.textContent = side === "source" ? "source only" : "target only";
  const tdVals = document.createElement("td");
  tdVals.className = "values";
  tdVals.textContent = values.length ? values.join("  |  ") : "(empty row)";
  tr.appendChild(tdSide);
  tr.appendChild(tdVals);
  return tr;
}

function showResults(p) {
  currentPayload = p;
  renderCounts(p);
  renderTable(p);
  els.results.hidden = false;
  els.reset.disabled = false;
}

// ---- Exports ----
function download(filename, content, mime) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  // Force a download: without this, browsers render certain MIME types
  // (e.g. application/json) inline and navigate to the blob URL instead of
  // saving the file.
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function toCsv(rows) {
  const cells = rows.map((r) =>
    r.map((c) => {
      const s = c === null || c === undefined ? "" : String(c);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")
  );
  return cells.join("\n") + "\n";
}

els.exportCsv.addEventListener("click", () => {
  if (!currentPayload) return;
  const rows = [
    ...currentPayload.source_mismatches.map((r) => ["source", ...r]),
    ...currentPayload.target_mismatches.map((r) => ["target", ...r]),
  ];
  download("mismatches.csv", toCsv(rows), "text/csv");
});

els.exportJson.addEventListener("click", () => {
  if (!currentPayload) return;
  download("mismatches.json", JSON.stringify(currentPayload, null, 2), "application/json");
});

// ---- Orchestration ----
async function run() {
  const sourceId = els.sSaved.value ? Number(els.sSaved.value) : null;
  const targetId = els.tSaved.value ? Number(els.tSaved.value) : null;
  if (sourceId === null || targetId === null) {
    setStatus("Select a saved connection for both Source and Target.", "error");
    return;
  }
  const sourceQuery = els.sQuery.value.trim();
  const targetQuery = els.tQuery.value.trim();
  if (!sourceQuery || !targetQuery) {
    setStatus("Enter a SQL query for both Source and Target.", "error");
    return;
  }
  const sourceDatabase = els.sDatabase.value;
  const targetDatabase = els.tDatabase.value;
  if (!sourceDatabase || !targetDatabase) {
    setStatus("Select a database for both Source and Target.", "error");
    return;
  }

  els.run.disabled = true;
  els.results.hidden = true;
  clearStatus();
  setStatus("Running comparison…");
  els.tbody.innerHTML = "";

  const body = {
    source_id: sourceId,
    source_query: sourceQuery,
    source_database: sourceDatabase,
    target_id: targetId,
    target_query: targetQuery,
    target_database: targetDatabase,
    max_mismatch_size: Number(els.maxMismatch.value),
  };

  try {
    await streamCompare(
      body,
      (type, payload) => {
        if (type === "progress") {
          setStatus(`Scanning — source: ${payload.source_scanned}, target: ${payload.target_scanned}…`);
        } else if (type === "result") {
          setStatus("Done.");
          showResults(payload);
        } else if (type === "error") {
          setStatus(payload.message || "Comparison failed.", "error");
        }
      },
      () => {
        els.run.disabled = false;
        els.reset.disabled = false;
      }
    );
  } catch (err) {
    setStatus(err.message || String(err), "error");
    els.run.disabled = false;
  }
}

els.run.addEventListener("click", run);
els.reset.addEventListener("click", () => {
  els.results.hidden = true;
  currentPayload = null;
  clearStatus();
});

refreshConnections();

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
  // While on "system", follow OS changes.
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
