// iMessage Exporter — frontend
//
// Single-page UI: four tabs (Contacts / Export / Conversations / Search).
// Talks to the FastAPI backend via fetch().

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ─── Tabs ────────────────────────────────────────────────────────

function showTab(name) {
  $$(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === `tab-${name}`));
  document.body.dataset.activeTab = name;
  if (name === "view") loadConversations();
  if (name === "search") loadSearchScope();
  if (name === "export") loadSettings();
}

$$(".tab-btn").forEach((btn) =>
  btn.addEventListener("click", () => showTab(btn.dataset.tab))
);

// ─── DB status banner ───────────────────────────────────────────

function dbGuidance(kind, bundled) {
  const target = bundled ? "iMessage Exporter" : "your terminal app";
  switch (kind) {
    case "not_macos":
      return "This tool only works on macOS — Messages.app's database doesn't exist on other platforms.";
    case "messages_never_set_up":
      return "Messages.app has never been opened on this Mac. Open it, sign in with your Apple ID, send/receive at least one message, then reload this page.";
    case "permission_denied":
      return (
        `${target} needs Full Disk Access. Open System Settings → Privacy & Security → Full Disk Access, ` +
        (bundled
          ? "find iMessage Exporter in the list (click + and add it from /Applications if it's not there), toggle it on, then fully quit the app and reopen it."
          : "enable it for the app running this server, then fully quit and reopen it. See the README for the full walkthrough.")
      );
    case "corrupted_or_locked":
      return "The Messages database is locked. Quit Messages.app (⌘Q) and reload this page.";
    default:
      return bundled
        ? "Couldn't read the Messages database — quit iMessage Exporter and try again."
        : "Couldn't read the Messages database — see the terminal where you started the app for details.";
  }
}

let RUNTIME_BUNDLED = false;

async function checkDbStatus() {
  try {
    const res = await fetch("/api/db-status");
    const data = await res.json();
    RUNTIME_BUNDLED = !!data.bundled;
    const banner = $("#db-banner");
    if (data.ok) {
      banner.classList.add("hidden");
      return true;
    }
    banner.classList.remove("hidden");
    banner.classList.add("error");
    const why =
      data.kind === "permission_denied"
        ? `<details class="banner-why">
             <summary>Why does it need this?</summary>
             <p>macOS keeps your iMessage history in a protected folder, so any app that wants to read it
             needs your explicit permission. This is the same permission Apple's Mail.app, Time Machine,
             and every third-party iMessage tool ask for.</p>
             <p><strong>iMessage Exporter only reads</strong> (never edits or sends) your messages, runs
             entirely on your Mac, and makes <strong>no internet connections</strong> — nothing about
             your conversations leaves this computer. You can revoke the permission any time from the
             same Settings panel.</p>
           </details>`
        : "";
    banner.innerHTML = `<strong>⚠️ Can't read the iMessage database.</strong><br/>${
      dbGuidance(data.kind, RUNTIME_BUNDLED)
    }${why}`;
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

function abGuidance(kind, bundled, detail) {
  switch (kind) {
    case "permission_denied":
      return bundled
        ? "Contacts access is blocked. Open System Settings → Privacy & Security → Contacts, find iMessage Exporter, toggle it on, then try again."
        : "Contacts access is blocked. Open System Settings → Privacy & Security → Contacts and enable access for the terminal app running this server, then try again.";
    case "contacts_app_missing":
      return "Couldn't start Contacts.app. Open it manually once (Applications → Contacts), then try again.";
    case "osascript_missing":
      return "osascript wasn't found — is this actually macOS?";
    default:
      return (
        (bundled
          ? "Couldn't read Contacts — try fully quitting iMessage Exporter and reopening."
          : "Couldn't read Contacts. See the terminal where you started the app for details.") +
        (detail ? ` (${detail})` : "")
      );
  }
}

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
      const detail = data.detail && data.detail.detail;
      const err = new Error(abGuidance(kind, RUNTIME_BUNDLED, detail));
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

// --- Group picker modal ---

const groupOverlay = $("#group-picker-overlay");
const groupList = $("#group-picker-list");
const groupStatus = $("#group-picker-status");
const groupSearch = $("#group-picker-search");

let groupsCache = null;
let groupAddedThisSession = new Set(); // chat_identifiers added since modal opened

$("#open-group-picker-btn").addEventListener("click", openGroupPicker);
$("#group-picker-close").addEventListener("click", closeGroupPicker);
groupOverlay.addEventListener("click", (e) => {
  if (e.target === groupOverlay) closeGroupPicker();
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !groupOverlay.classList.contains("hidden")) closeGroupPicker();
});
groupSearch.addEventListener("input", () => renderGroupList(groupSearch.value));

async function openGroupPicker() {
  groupOverlay.classList.remove("hidden");
  groupOverlay.setAttribute("aria-hidden", "false");
  groupSearch.value = "";
  groupStatus.textContent = "Loading group chats…";
  groupList.innerHTML = "";
  groupAddedThisSession = new Set();
  try {
    const res = await fetch("/api/groups");
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      const kind = data.detail?.kind || "unknown";
      groupStatus.textContent = "";
      groupList.innerHTML = `<li class="picker-error">${escapeHtml(dbGuidance(kind, RUNTIME_BUNDLED))}</li>`;
      return;
    }
    const data = await res.json();
    groupsCache = data.groups;
    groupStatus.textContent = `${groupsCache.length.toLocaleString()} group chat${groupsCache.length === 1 ? "" : "s"}`;
    renderGroupList("");
    setTimeout(() => groupSearch.focus(), 50);
  } catch (e) {
    groupStatus.textContent = "";
    groupList.innerHTML = `<li class="picker-error">${escapeHtml(e.message || String(e))}</li>`;
  }
}

function closeGroupPicker() {
  groupOverlay.classList.add("hidden");
  groupOverlay.setAttribute("aria-hidden", "true");
}

function renderGroupList(query) {
  if (!groupsCache) return;
  const q = query.trim().toLowerCase();
  const matches = q
    ? groupsCache.filter((g) =>
        g.display_name.toLowerCase().includes(q) ||
        g.participant_names.some((n) => n.toLowerCase().includes(q))
      )
    : groupsCache;

  if (!matches.length) {
    groupList.innerHTML = `<li class="muted" style="padding: 1rem; text-align: center;">No matches.</li>`;
    return;
  }

  const LIMIT = 200;
  const shown = matches.slice(0, LIMIT);
  const moreNote =
    matches.length > LIMIT
      ? `<li class="muted" style="padding: 0.5rem; text-align: center;">Showing first ${LIMIT} of ${matches.length}. Refine search to narrow.</li>`
      : "";

  groupList.innerHTML =
    shown.map((g) => {
      const added = g.already_added || groupAddedThisSession.has(g.chat_identifier);
      const namesPreview = g.participant_names.slice(0, 4).join(", ");
      const extra = g.participant_names.length - 4;
      const participants = namesPreview + (extra > 0 ? `, +${extra} more` : "");
      return `
        <li class="picker-row group-row">
          <div class="group-row-main" data-chat="${escapeHtml(g.chat_identifier)}" data-name="${escapeHtml(g.display_name)}">
            <div class="group-row-top">
              <span class="group-row-name">${escapeHtml(g.display_name)}</span>
              <span class="group-row-stats">${g.participant_names.length} ppl · ${g.message_count.toLocaleString()} msgs</span>
            </div>
            <div class="group-row-participants">${escapeHtml(participants)}</div>
          </div>
          <div class="group-row-action">
            ${added
              ? `<span class="chip added"><span class="chip-label">added</span></span>`
              : `<button type="button" class="add-group-btn" data-chat="${escapeHtml(g.chat_identifier)}" data-name="${escapeHtml(g.display_name)}">Add</button>`}
          </div>
        </li>
      `;
    }).join("") + moreNote;

  groupList.querySelectorAll(".add-group-btn").forEach((btn) =>
    btn.addEventListener("click", () => onGroupAddClick(btn))
  );
}

async function onGroupAddClick(btn) {
  const chatId = btn.dataset.chat;
  const name = btn.dataset.name;
  btn.disabled = true;
  btn.textContent = "Adding…";
  try {
    const res = await fetch("/api/contacts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, identifier: `group:${chatId}` }),
    });
    if (res.ok) {
      groupAddedThisSession.add(chatId);
      renderGroupList(groupSearch.value);
      loadContacts();
    } else {
      const data = await res.json().catch(() => ({}));
      alert(data.detail || "Couldn't add group.");
      btn.disabled = false;
      btn.textContent = "Add";
    }
  } catch (e) {
    alert(e.message || String(e));
    btn.disabled = false;
    btn.textContent = "Add";
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

// ─── Export folder settings ────────────────────────────────────

const folderInput = $("#folder-input");
const folderSaveBtn = $("#folder-save-btn");
const folderResetBtn = $("#folder-reset-btn");
const folderBrowseBtn = $("#folder-browse-btn");
const folderError = $("#folder-error");

let settingsCache = null;

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    settingsCache = data;
    folderInput.value = data.output_dir;
    folderInput.placeholder = data.default_output_dir;
    folderResetBtn.classList.toggle("hidden", data.is_default);
    folderError.classList.add("hidden");
  } catch (e) {
    console.error(e);
  }
}

function showFolderError(msg) {
  folderError.textContent = msg;
  folderError.classList.remove("hidden");
}

async function saveSettings(newPath) {
  folderSaveBtn.disabled = true;
  folderSaveBtn.innerHTML = `<span class="spinner"></span>Saving…`;
  folderError.classList.add("hidden");
  try {
    const res = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_dir: newPath }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showFolderError(data.detail || "Couldn't save folder.");
      return;
    }
    settingsCache = data;
    folderInput.value = data.output_dir;
    folderResetBtn.classList.toggle("hidden", data.is_default);
    folderSaveBtn.textContent = "Saved ✓";
    setTimeout(() => { folderSaveBtn.textContent = "Save"; }, 1400);
  } finally {
    folderSaveBtn.disabled = false;
    if (folderSaveBtn.textContent.startsWith("Saving")) folderSaveBtn.textContent = "Save";
  }
}

$("#folder-form").addEventListener("submit", (e) => {
  e.preventDefault();
  saveSettings(folderInput.value.trim());
});

folderResetBtn.addEventListener("click", () => saveSettings(null));

folderBrowseBtn.addEventListener("click", async () => {
  folderBrowseBtn.disabled = true;
  folderBrowseBtn.innerHTML = `<span class="spinner"></span>Choose…`;
  try {
    const res = await fetch("/api/browse-folder", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showFolderError(data.detail || "Couldn't open folder picker.");
      return;
    }
    if (data.cancelled) return;
    if (data.path) {
      folderInput.value = data.path;
      folderError.classList.add("hidden");
      folderInput.focus();
    }
  } finally {
    folderBrowseBtn.disabled = false;
    folderBrowseBtn.textContent = "Browse…";
  }
});

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
          ? dbGuidance(data.detail.kind, RUNTIME_BUNDLED)
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
let activeConvName = null;

async function loadConversations() {
  const indivList = $("#conversation-list-individuals");
  const groupList = $("#conversation-list-groups");
  try {
    const res = await fetch("/api/conversations");
    const data = await res.json();
    conversationListCache = data.conversations;

    const individuals = data.conversations.filter((c) => !c.is_group);
    const groups = data.conversations.filter((c) => c.is_group);

    $("#individuals-count").textContent = individuals.length ? `(${individuals.length})` : "";
    $("#groups-count").textContent = groups.length ? `(${groups.length})` : "";

    renderConvList(indivList, individuals, "No individuals exported yet.");
    renderConvList(groupList, groups, "No groups exported yet.");
  } catch (e) {
    indivList.innerHTML = `<li class="muted">Couldn't load conversations.</li>`;
    groupList.innerHTML = "";
  }
}

function renderConvList(listEl, items, emptyMsg) {
  if (!items.length) {
    listEl.innerHTML = `<li class="muted">${emptyMsg}</li>`;
    return;
  }
  listEl.innerHTML = "";
  for (const c of items) {
    const li = document.createElement("li");
    li.textContent = c.display_name || c.name;
    li.dataset.name = c.name;
    if (c.name === activeConvName) li.classList.add("active");
    li.addEventListener("click", () => openConversation(c.name));
    listEl.appendChild(li);
  }
}

async function openConversation(name, jumpToIndex = null) {
  activeConvName = name;
  $$(".conversation-list li").forEach((li) =>
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
    if (jumpToIndex != null) jumpToBubble(pane, jumpToIndex);
  } catch (e) {
    pane.innerHTML = `<p class="empty-chat">Error: ${escapeHtml(e.message || String(e))}</p>`;
  }
}

function jumpToBubble(pane, idx) {
  const target = pane.querySelector(`.bubble-row[data-msg-index="${idx}"]`);
  if (!target) return;
  // Defer to next paint so layout is settled before scrolling.
  requestAnimationFrame(() => {
    target.scrollIntoView({ block: "center", behavior: "smooth" });
    target.classList.add("highlight");
    setTimeout(() => target.classList.remove("highlight"), 2200);
  });
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
  let lastSender = null;
  const ONE_HOUR_MS = 60 * 60 * 1000;

  data.messages.forEach((m, i) => {
    const t = m.timestamp ? new Date(m.timestamp) : null;
    const timeJumped = t && (!lastTime || t - lastTime > ONE_HOUR_MS);
    if (timeJumped) {
      const divider = document.createElement("div");
      divider.className = "ts-divider";
      divider.textContent = m.timestamp_display;
      pane.appendChild(divider);
    }
    lastTime = t;

    // Group sender label: show above incoming bubbles only when the sender
    // changes (or a time gap reset the burst). Skip for me + 1:1 chats.
    if (!m.is_from_me && m.sender_name) {
      const isBurstStart = timeJumped || m.sender_name !== lastSender;
      if (isBurstStart) {
        const label = document.createElement("div");
        label.className = "bubble-sender";
        label.textContent = m.sender_name;
        pane.appendChild(label);
      }
      lastSender = m.sender_name;
    } else {
      lastSender = m.is_from_me ? "__me__" : null;
    }

    const row = document.createElement("div");
    row.className = `bubble-row ${m.is_from_me ? "me" : "them"}`;
    row.dataset.msgIndex = String(i);
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    bubble.textContent = m.text;
    bubble.title = m.timestamp_display;
    row.appendChild(bubble);
    pane.appendChild(row);
  });

  pane.scrollTop = 0;
}

// ─── Search ─────────────────────────────────────────────────────

const searchForm = $("#search-form");
const searchInput = $("#search-input");
const searchScope = $("#search-scope");
const searchSummary = $("#search-summary");
const searchResults = $("#search-results");
const searchLoadMore = $("#search-load-more");

let currentSearch = { query: "", contact: "", offset: 0, total: 0 };
let searchScopeLoaded = false;

async function loadSearchScope() {
  // Populate the scope dropdown from /api/conversations once per session.
  if (searchScopeLoaded) return;
  try {
    const res = await fetch("/api/conversations");
    const data = await res.json();
    // Keep the first "All exported conversations" option, replace the rest.
    searchScope.length = 1;
    for (const c of data.conversations) {
      const opt = document.createElement("option");
      opt.value = c.name;
      opt.textContent = c.name;
      searchScope.appendChild(opt);
    }
    searchScopeLoaded = true;
  } catch (e) {
    console.error("Couldn't load scope:", e);
  }
}

searchForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = searchInput.value.trim();
  if (q.length < 2) {
    searchSummary.textContent = "Enter at least 2 characters.";
    searchResults.innerHTML = "";
    searchLoadMore.classList.add("hidden");
    return;
  }
  currentSearch = {
    query: q,
    contact: searchScope.value || "",
    offset: 0,
    total: 0,
  };
  searchResults.innerHTML = "";
  searchSummary.textContent = "Searching…";
  searchLoadMore.classList.add("hidden");
  await fetchSearchPage(true);
});

searchLoadMore.addEventListener("click", () => fetchSearchPage(false));

async function fetchSearchPage(isFirstPage) {
  const params = new URLSearchParams({
    q: currentSearch.query,
    offset: String(currentSearch.offset),
    limit: "9",
  });
  if (currentSearch.contact) params.set("contact", currentSearch.contact);

  // Show loading state on the Load-more button for subsequent pages.
  if (!isFirstPage) {
    searchLoadMore.disabled = true;
    searchLoadMore.innerHTML = `<span class="spinner"></span>Loading…`;
  }

  try {
    const res = await fetch(`/api/search?${params}`);
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      searchSummary.textContent = `Error: ${typeof data.detail === "string" ? data.detail : "search failed"}`;
      return;
    }
    const data = await res.json();
    currentSearch.total = data.total;

    if (isFirstPage && data.total === 0) {
      searchSummary.textContent = "";
      searchResults.innerHTML = `<div class="search-empty">No matches for ${escapeHtml(currentSearch.query)}.</div>`;
      return;
    }

    const shownNow = currentSearch.offset + data.hits.length;
    searchSummary.textContent = `${data.total.toLocaleString()} match${data.total === 1 ? "" : "es"} — showing ${shownNow}`;
    for (const hit of data.hits) {
      searchResults.appendChild(renderHit(hit, currentSearch.query));
    }
    currentSearch.offset += data.hits.length;
    if (currentSearch.offset < data.total) {
      searchLoadMore.classList.remove("hidden");
      searchLoadMore.textContent = `Load 9 more (${(data.total - currentSearch.offset).toLocaleString()} remaining)`;
    } else {
      searchLoadMore.classList.add("hidden");
    }
  } catch (e) {
    searchSummary.textContent = `Error: ${e.message || String(e)}`;
  } finally {
    searchLoadMore.disabled = false;
  }
}

function renderHit(hit, query) {
  const card = document.createElement("div");
  card.className = "search-hit";
  card.dataset.contact = hit.contact_name;
  card.dataset.index = String(hit.match_index);

  const header = document.createElement("div");
  header.className = "hit-header";
  header.innerHTML = `
    <span class="hit-contact">${escapeHtml(hit.contact_name)}</span>
    <span class="hit-ts">${escapeHtml(hit.match.timestamp_display)}</span>
  `;
  card.appendChild(header);

  for (const m of hit.before) card.appendChild(renderHitLine(m, "context", query, hit.contact_name));
  card.appendChild(renderHitLine(hit.match, "match", query, hit.contact_name));
  for (const m of hit.after) card.appendChild(renderHitLine(m, "context", query, hit.contact_name));

  card.addEventListener("click", () => {
    showTab("view");
    openConversation(hit.contact_name, hit.match_index);
  });

  return card;
}

function renderHitLine(msg, kind, query, contactName) {
  const line = document.createElement("div");
  line.className = `hit-line ${kind}`;
  const sender = document.createElement("span");
  sender.className = "sender";
  sender.textContent = msg.is_from_me ? "me" : contactName.split(" ")[0];
  const text = document.createElement("span");
  text.className = "text";
  if (kind === "match") {
    text.innerHTML = highlightQuery(msg.text, query);
  } else {
    text.textContent = truncate(msg.text, 200);
  }
  line.appendChild(sender);
  line.appendChild(text);
  return line;
}

function highlightQuery(text, query) {
  // Case-insensitive: find every match of `query` in `text` and wrap with <mark>.
  // We escape the surrounding text and the matched substrings separately, so HTML
  // metacharacters in the message don't break anything.
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const parts = [];
  let i = 0;
  while (i < text.length) {
    const idx = lower.indexOf(q, i);
    if (idx === -1) {
      parts.push(escapeHtml(text.slice(i)));
      break;
    }
    if (idx > i) parts.push(escapeHtml(text.slice(i, idx)));
    parts.push(`<mark>${escapeHtml(text.slice(idx, idx + q.length))}</mark>`);
    i = idx + q.length;
  }
  return parts.join("");
}

function truncate(s, n) {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
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

// Heartbeat — tells the server the browser tab is still open. When the
// user closes the tab these pings stop, the server's watchdog notices, and
// the .app exits. Only enforced in bundled mode; in dev the server keeps
// running so you can reload freely.
function pingHeartbeat() {
  fetch("/api/heartbeat", { method: "POST", keepalive: true }).catch(() => {});
}
pingHeartbeat();
setInterval(pingHeartbeat, 5000);

(async function init() {
  document.body.dataset.activeTab = "contacts";
  await checkDbStatus();
  await loadContacts();
})();
