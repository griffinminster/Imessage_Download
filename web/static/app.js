// iMessage Exporter — frontend
//
// Single-page UI: three tabs (Contacts / Export / Conversations).
// Talks to the FastAPI backend via fetch().

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ─── Tabs ────────────────────────────────────────────────────────

function showTab(name) {
  $$(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  if (name === "view") loadConversations();
}

$$(".tab-btn").forEach((btn) =>
  btn.addEventListener("click", () => showTab(btn.dataset.tab))
);

// ─── DB status banner ───────────────────────────────────────────

const DB_GUIDANCE = {
  not_macos: "This tool only works on macOS — Messages.app's database doesn't exist on other platforms.",
  messages_never_set_up:
    "Messages.app has never been opened on this Mac. Open it, sign in with your Apple ID, send/receive at least one message, then reload this page.",
  permission_denied:
    "Your terminal app needs Full Disk Access. Open System Settings → Privacy & Security → Full Disk Access, enable it for the app running this server, then fully quit and reopen it. See the README for the full walkthrough.",
  corrupted_or_locked:
    "The Messages database is locked. Quit Messages.app (⌘Q) and reload this page.",
  unknown:
    "Couldn't read the Messages database — see the terminal where you started the app for details.",
};

async function checkDbStatus() {
  try {
    const res = await fetch("/api/db-status");
    const data = await res.json();
    const banner = $("#db-banner");
    if (data.ok) {
      banner.classList.add("hidden");
      return true;
    }
    banner.classList.remove("hidden");
    banner.classList.add("error");
    banner.innerHTML = `<strong>⚠️ Can't read the iMessage database.</strong><br/>${
      DB_GUIDANCE[data.kind] || DB_GUIDANCE.unknown
    }<br/><small>Path: <code>${data.db_path}</code></small>`;
    return false;
  } catch (e) {
    console.error(e);
    return false;
  }
}

// ─── Contacts ───────────────────────────────────────────────────

async function loadContacts() {
  const tbody = $("#contacts-tbody");
  tbody.innerHTML = `<tr><td colspan="3" class="muted">Loading…</td></tr>`;
  try {
    const res = await fetch("/api/contacts");
    const data = await res.json();
    if (!data.contacts.length) {
      tbody.innerHTML = `<tr><td colspan="3" class="muted">No contacts yet — add one below.</td></tr>`;
      return;
    }
    tbody.innerHTML = "";
    for (const c of data.contacts) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${escapeHtml(c.name)}</td>
        <td><code>${escapeHtml(c.identifier)}</code></td>
        <td style="text-align:right;">
          <button class="danger" data-id="${escapeHtml(c.identifier)}">Remove</button>
        </td>
      `;
      tbody.appendChild(tr);
    }
    tbody.querySelectorAll("button.danger").forEach((btn) =>
      btn.addEventListener("click", () => removeContact(btn.dataset.id))
    );
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="3" class="muted">Couldn't load contacts.</td></tr>`;
  }
}

$("#add-contact-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = $("#contact-name").value.trim();
  const identifier = $("#contact-id").value.trim();
  const errEl = $("#add-error");
  errEl.classList.add("hidden");

  if (!name || !identifier) {
    errEl.textContent = "Both name and identifier are required.";
    errEl.classList.remove("hidden");
    return;
  }

  const res = await fetch("/api/contacts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, identifier }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    errEl.textContent = data.detail || "Couldn't add contact.";
    errEl.classList.remove("hidden");
    return;
  }
  $("#contact-name").value = "";
  $("#contact-id").value = "";
  loadContacts();
});

async function removeContact(identifier) {
  if (!confirm(`Remove ${identifier}?`)) return;
  const res = await fetch(`/api/contacts/${encodeURIComponent(identifier)}`, {
    method: "DELETE",
  });
  if (res.ok) loadContacts();
  else alert("Couldn't remove contact.");
}

// ─── Export ─────────────────────────────────────────────────────

$("#export-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const myName = $("#my-name").value.trim() || "Me";
  const status = $("#export-status");
  const btn = $("#export-btn");

  status.innerHTML = `<div class="line">Running export…</div>`;
  btn.disabled = true;

  try {
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ my_name: myName }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const msg =
        typeof data.detail === "object"
          ? DB_GUIDANCE[data.detail.kind] || data.detail.detail
          : data.detail || "Export failed.";
      status.innerHTML = `<div class="line err">❌ ${escapeHtml(msg)}</div>`;
      return;
    }
    const data = await res.json();
    const lines = data.conversations.map((c) => {
      if (c.error) return `<div class="line err">❌ ${escapeHtml(c.name)} — ${escapeHtml(c.error)}</div>`;
      if (!c.count) return `<div class="line">⚠️ ${escapeHtml(c.name)} — no messages found</div>`;
      return `<div class="line ok">✅ ${escapeHtml(c.name)} — ${c.count.toLocaleString()} messages</div>`;
    });
    lines.push(
      `<div class="line">📁 Files saved to <code>${escapeHtml(data.output_dir)}</code></div>`,
      `<div class="line"><button type="button" id="goto-view-btn">View conversations →</button></div>`
    );
    status.innerHTML = lines.join("");
    $("#goto-view-btn").addEventListener("click", () => showTab("view"));
  } catch (e) {
    status.innerHTML = `<div class="line err">❌ ${escapeHtml(e.message || String(e))}</div>`;
  } finally {
    btn.disabled = false;
  }
});

// ─── Conversation viewer ───────────────────────────────────────

let conversationListCache = [];

async function loadConversations() {
  const list = $("#conversation-list");
  try {
    const res = await fetch("/api/conversations");
    const data = await res.json();
    conversationListCache = data.conversations;
    if (!data.conversations.length) {
      list.innerHTML = `<li class="muted">No exports yet — run one from the Export tab.</li>`;
      return;
    }
    list.innerHTML = "";
    for (const c of data.conversations) {
      const li = document.createElement("li");
      li.textContent = c.name;
      li.dataset.name = c.name;
      li.addEventListener("click", () => openConversation(c.name));
      list.appendChild(li);
    }
  } catch (e) {
    list.innerHTML = `<li class="muted">Couldn't load conversations.</li>`;
  }
}

async function openConversation(name) {
  $$("#conversation-list li").forEach((li) =>
    li.classList.toggle("active", li.dataset.name === name)
  );

  const pane = $("#chat-pane");
  pane.innerHTML = `<p class="empty-chat">Loading ${escapeHtml(name)}…</p>`;

  try {
    const res = await fetch(`/api/conversations/${encodeURIComponent(name)}`);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      pane.innerHTML = `<p class="empty-chat">Couldn't load: ${escapeHtml(
        typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "")
      )}</p>`;
      return;
    }
    const data = await res.json();
    renderChat(pane, data);
  } catch (e) {
    pane.innerHTML = `<p class="empty-chat">Error: ${escapeHtml(e.message || String(e))}</p>`;
  }
}

function renderChat(pane, data) {
  pane.innerHTML = "";
  const header = document.createElement("div");
  header.className = "chat-header";
  header.innerHTML = `
    <h2>${escapeHtml(data.name)}</h2>
    <div class="meta">${escapeHtml(data.identifier)} • ${data.count.toLocaleString()} messages</div>
  `;
  pane.appendChild(header);

  if (!data.messages.length) {
    const empty = document.createElement("p");
    empty.className = "empty-chat";
    empty.textContent = "No messages.";
    pane.appendChild(empty);
    return;
  }

  let lastTime = null;
  const ONE_HOUR_MS = 60 * 60 * 1000;

  for (const m of data.messages) {
    const t = m.timestamp ? new Date(m.timestamp) : null;
    if (t && (!lastTime || t - lastTime > ONE_HOUR_MS)) {
      const divider = document.createElement("div");
      divider.className = "ts-divider";
      divider.textContent = m.timestamp_display;
      pane.appendChild(divider);
    }
    lastTime = t;

    const row = document.createElement("div");
    row.className = `bubble-row ${m.is_from_me ? "me" : "them"}`;
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = m.text;
    bubble.title = m.timestamp_display;
    row.appendChild(bubble);
    pane.appendChild(row);
  }

  pane.scrollTop = 0;
}

// ─── Utilities ──────────────────────────────────────────────────

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// ─── Boot ───────────────────────────────────────────────────────

(async function init() {
  await checkDbStatus();
  await loadContacts();
})();
