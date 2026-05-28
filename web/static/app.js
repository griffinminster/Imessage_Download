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

// ─── macOS Contacts picker + autocomplete ──────────────────────

const AB_GUIDANCE = {
  permission_denied:
    "Contacts access is blocked. Open System Settings → Privacy & Security → Contacts and enable access for the terminal app running this server, then try again.",
  contacts_app_missing:
    "Contacts.app didn't respond. Make sure it's installed and try again.",
  osascript_missing:
    "osascript wasn't found — is this actually macOS?",
  unknown:
    "Couldn't read Contacts. See the terminal where you started the app for details.",
};

let addressBookCache = null; // [{name, phones:[{label,value}], emails:[...]}]
let addressBookPromise = null;
let pickerExpanded = new Set();
const ALREADY_ADDED = new Set(); // normalized identifiers already in contacts.csv

async function loadAddressBook(refresh = false) {
  if (addressBookCache && !refresh) return addressBookCache;
  if (addressBookPromise && !refresh) return addressBookPromise;

  addressBookPromise = (async () => {
    const res = await fetch(`/api/address-book${refresh ? "?refresh=1" : ""}`);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const kind = (data.detail && data.detail.kind) || "unknown";
      const err = new Error(AB_GUIDANCE[kind] || AB_GUIDANCE.unknown);
      err.kind = kind;
      throw err;
    }
    const data = await res.json();
    addressBookCache = data.contacts;
    return addressBookCache;
  })();

  try {
    return await addressBookPromise;
  } finally {
    addressBookPromise = null;
  }
}

async function refreshAlreadyAddedSet() {
  try {
    const res = await fetch("/api/contacts");
    const data = await res.json();
    ALREADY_ADDED.clear();
    for (const c of data.contacts) ALREADY_ADDED.add(c.identifier);
  } catch (e) { /* no-op */ }
}

// --- Modal ---

const pickerOverlay = $("#picker-overlay");
const pickerList = $("#picker-list");
const pickerStatus = $("#picker-status");
const pickerSearch = $("#picker-search");

$("#open-picker-btn").addEventListener("click", openPicker);
$("#picker-close").addEventListener("click", closePicker);
pickerOverlay.addEventListener("click", (e) => {
  if (e.target === pickerOverlay) closePicker();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !pickerOverlay.classList.contains("hidden")) closePicker();
});
pickerSearch.addEventListener("input", () => renderPickerList(pickerSearch.value));

async function openPicker() {
  pickerOverlay.classList.remove("hidden");
  pickerOverlay.setAttribute("aria-hidden", "false");
  pickerSearch.value = "";
  pickerExpanded = new Set();
  pickerStatus.textContent = "Loading your Contacts…";
  pickerList.innerHTML = "";
  await refreshAlreadyAddedSet();
  try {
    await loadAddressBook();
    pickerStatus.textContent = `${addressBookCache.length.toLocaleString()} contacts`;
    renderPickerList("");
    setTimeout(() => pickerSearch.focus(), 50);
  } catch (e) {
    pickerStatus.textContent = "";
    pickerList.innerHTML = `<li class="picker-error">${escapeHtml(e.message)}</li>`;
  }
}

function closePicker() {
  pickerOverlay.classList.add("hidden");
  pickerOverlay.setAttribute("aria-hidden", "true");
}

function renderPickerList(query) {
  if (!addressBookCache) return;
  const q = query.trim().toLowerCase();
  const matches = q
    ? addressBookCache.filter((c) => c.name.toLowerCase().includes(q))
    : addressBookCache;

  if (!matches.length) {
    pickerList.innerHTML = `<li class="muted" style="padding: 1rem; text-align: center;">No matches.</li>`;
    return;
  }

  // Cap to avoid rendering thousands of rows up front.
  const LIMIT = 200;
  const shown = matches.slice(0, LIMIT);
  const moreNote =
    matches.length > LIMIT
      ? `<li class="muted" style="padding: 0.5rem; text-align: center;">Showing first ${LIMIT} of ${matches.length}. Refine search to narrow.</li>`
      : "";

  pickerList.innerHTML =
    shown
      .map((c) => {
        const isOpen = pickerExpanded.has(c.name);
        const arrow = isOpen ? "▾" : "▸";
        return `
          <li class="picker-row">
            <div class="picker-name" data-name="${escapeHtml(c.name)}">
              <span class="arrow">${arrow}</span>${escapeHtml(c.name)}
            </div>
            ${isOpen ? renderChips(c) : ""}
          </li>
        `;
      })
      .join("") + moreNote;

  pickerList.querySelectorAll(".picker-name").forEach((el) =>
    el.addEventListener("click", () => {
      const n = el.dataset.name;
      if (pickerExpanded.has(n)) pickerExpanded.delete(n);
      else pickerExpanded.add(n);
      renderPickerList(pickerSearch.value);
    })
  );

  pickerList.querySelectorAll(".chip[data-identifier]").forEach((chip) =>
    chip.addEventListener("click", () => onChipClick(chip))
  );
}

function renderChips(contact) {
  const phones = contact.phones.map((p) => chipHtml(contact.name, p.label, p.value, "phone"));
  const emails = contact.emails.map((p) => chipHtml(contact.name, p.label, p.value, "email"));
  const all = [...phones, ...emails];
  if (!all.length) {
    return `<div class="picker-chips"><span class="muted">No phones or emails.</span></div>`;
  }
  return `<div class="picker-chips">${all.join("")}</div>`;
}

function chipHtml(name, label, value, kind) {
  // We don't know the post-normalization identifier client-side, so we just
  // pass the raw value and let the backend normalize. The chip is marked
  // "added" only after the POST round-trip succeeds.
  const cleanLabel = (label || kind).replace(/^_?\$!<|>!\$_?$/g, "").toLowerCase();
  return `
    <span class="chip" data-name="${escapeHtml(name)}" data-identifier="${escapeHtml(value)}">
      <span class="chip-label">${escapeHtml(cleanLabel)}</span>
      <span class="chip-value">${escapeHtml(value)}</span>
    </span>
  `;
}

async function onChipClick(chip) {
  if (chip.classList.contains("added")) return;
  const name = chip.dataset.name;
  const identifier = chip.dataset.identifier;
  chip.style.opacity = "0.5";
  try {
    const res = await fetch("/api/contacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, identifier }),
    });
    if (res.ok) {
      const data = await res.json().catch(() => ({}));
      const normalized = data.contact?.identifier || identifier;
      chip.classList.add("added");
      chip.innerHTML = `<span class="chip-label">added</span><span class="chip-value">${escapeHtml(normalized)}</span>`;
      loadContacts();
    } else {
      const data = await res.json().catch(() => ({}));
      alert(data.detail || "Couldn't add contact.");
    }
  } finally {
    chip.style.opacity = "";
  }
}

// --- Autocomplete on the Name input ---

const nameInput = $("#contact-name");
const idInput = $("#contact-id");
const suggestionList = $("#name-suggestions");
let suggestionIndex = -1;

nameInput.addEventListener("focus", () => maybeShowSuggestions());
nameInput.addEventListener("input", () => maybeShowSuggestions());
nameInput.addEventListener("blur", () => {
  // Delay so a click on a suggestion still fires.
  setTimeout(hideSuggestions, 150);
});
nameInput.addEventListener("keydown", (e) => {
  const items = suggestionList.querySelectorAll("li");
  if (!items.length || suggestionList.classList.contains("hidden")) return;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    suggestionIndex = Math.min(suggestionIndex + 1, items.length - 1);
    highlightSuggestion(items);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    suggestionIndex = Math.max(suggestionIndex - 1, 0);
    highlightSuggestion(items);
  } else if (e.key === "Enter" && suggestionIndex >= 0) {
    e.preventDefault();
    items[suggestionIndex].click();
  } else if (e.key === "Escape") {
    hideSuggestions();
  }
});

async function maybeShowSuggestions() {
  const q = nameInput.value.trim().toLowerCase();
  if (q.length < 1) {
    hideSuggestions();
    return;
  }
  try {
    await loadAddressBook();
  } catch (e) {
    hideSuggestions();
    return;
  }
  if (!addressBookCache) return;

  const matches = addressBookCache
    .filter((c) => c.name.toLowerCase().includes(q))
    .slice(0, 8);

  if (!matches.length) {
    hideSuggestions();
    return;
  }

  suggestionList.innerHTML = matches
    .map((c) => {
      const firstPhone = c.phones[0]?.value || c.emails[0]?.value || "";
      return `
        <li data-name="${escapeHtml(c.name)}" data-id="${escapeHtml(firstPhone)}">
          <span class="ac-name">${escapeHtml(c.name)}</span>
          <span class="ac-id">${escapeHtml(firstPhone)}</span>
        </li>
      `;
    })
    .join("");
  suggestionList.classList.remove("hidden");
  suggestionIndex = -1;

  suggestionList.querySelectorAll("li").forEach((li) =>
    li.addEventListener("mousedown", (e) => {
      e.preventDefault();
      nameInput.value = li.dataset.name;
      if (li.dataset.id) idInput.value = li.dataset.id;
      hideSuggestions();
      idInput.focus();
    })
  );
}

function highlightSuggestion(items) {
  items.forEach((li, i) => li.classList.toggle("active", i === suggestionIndex));
  if (suggestionIndex >= 0) items[suggestionIndex].scrollIntoView({ block: "nearest" });
}

function hideSuggestions() {
  suggestionList.classList.add("hidden");
  suggestionIndex = -1;
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
