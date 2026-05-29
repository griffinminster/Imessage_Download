#!/usr/bin/env python3
"""
iMessage Exporter — Web UI
--------------------------
FastAPI app that wraps the existing library code in a small JSON API and
serves a single static frontend. Run with:

    python3 app.py

The browser opens automatically to http://127.0.0.1:8765.
"""

import sqlite3
import sys
import threading
import time
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn

from export_imessages import (
    DEFAULT_CSV_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_OUTPUT_DIR,
    LOCAL_TZ,
    DatabaseAccessError,
    apple_timestamp_to_local,
    check_database_access,
    export_conversation,
    normalize_identifier,
    query_messages,
)
from add_contacts import load_contacts, save_contacts
from address_book import AddressBookError, check_access, fetch_address_book


HOST = "127.0.0.1"
PORT = 8765

REPO_ROOT = Path(__file__).resolve().parent


def _static_dir():
    """Locate the bundled frontend.

    When running from source, web/static/ lives next to app.py. When packaged
    by py2app, the data_files we declared land in the bundle's Resources
    folder, which is two levels up from the executable.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent / "Resources" / "web" / "static"
    return REPO_ROOT / "web" / "static"


STATIC_DIR = _static_dir()

app = FastAPI(title="iMessage Exporter")


# ─────────────────────────────────────────────
#  Pydantic models
# ─────────────────────────────────────────────

class ContactIn(BaseModel):
    name: str
    identifier: str


class ExportIn(BaseModel):
    my_name: str = "Me"


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _contacts_as_dicts():
    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    return [{"name": n, "identifier": i} for n, i in contacts]


def _serialize_messages(rows, tz=LOCAL_TZ, sender_name_map=None):
    """Convert raw DB rows into a JSON-friendly shape for the bubble viewer.

    Each row is (apple_ts, is_from_me, text, sender_handle). For group
    chats, `sender_handle` is the participant's phone/email; passing a
    `sender_name_map` ({handle_id: display_name}) lets the frontend show
    a "Asher" label above their bubbles.
    """
    sender_name_map = sender_name_map or {}
    out = []
    for row in rows:
        # Tolerate both legacy 3-tuples and the new 4-tuples.
        if len(row) == 4:
            apple_ts, is_from_me, text, sender_handle = row
        else:
            apple_ts, is_from_me, text = row
            sender_handle = None
        if apple_ts:
            unix_ts = apple_ts / 1_000_000_000 + 978_307_200
            dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(tz)
            iso = dt.isoformat()
            display = apple_timestamp_to_local(apple_ts, tz=tz)
        else:
            iso = None
            display = "Unknown time"
        item = {
            "timestamp": iso,
            "timestamp_display": display,
            "is_from_me": bool(is_from_me),
            "text": text or "",
        }
        if sender_handle and not is_from_me:
            item["sender_handle"] = sender_handle
            item["sender_name"] = sender_name_map.get(sender_handle, sender_handle)
        out.append(item)
    return out


def _build_handle_name_map(handles, allow_fetch=False):
    """Resolve each handle (phone/email) to a display name.

    Order of preference:
      1. contacts.csv  — handle matches a contact's normalized identifier.
      2. The macOS Address Book — handle matches any of a person's normalized
         phone/email values. Uses the process cache by default; if
         `allow_fetch=True` and the cache is empty, fetches once (~10s on a
         large book). Useful for group viewer/search where good names matter.
      3. Fallback: leave unmapped so the raw handle gets shown.
    """
    result: dict[str, str] = {}
    remaining = {h for h in handles if h}
    if not remaining:
        return result

    # 1) contacts.csv
    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    for name, raw_id in contacts:
        norm = normalize_identifier(raw_id)
        if norm in remaining:
            result[norm] = name
            remaining.discard(norm)

    if not remaining:
        return result

    # 2) address book — use cache; optionally trigger one-time fetch
    import address_book as ab
    if ab._cache is None and allow_fetch:
        try:
            ab.fetch_address_book()
        except ab.AddressBookError:
            pass  # surface raw handles rather than failing the whole request
    if not ab._cache:
        return result

    for person in ab._cache:
        for ph in person.get("phones", []):
            norm = normalize_identifier(ph["value"])
            if norm in remaining:
                result[norm] = person["name"]
                remaining.discard(norm)
        for em in person.get("emails", []):
            val = em["value"].strip()
            if val in remaining:
                result[val] = person["name"]
                remaining.discard(val)
        if not remaining:
            break

    return result


def _participants_for_group(conn, chat_identifier):
    """Return the list of handle ids participating in a group chat."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT h.id
        FROM chat c
        JOIN chat_handle_join chj ON chj.chat_id = c.ROWID
        JOIN handle h ON chj.handle_id = h.ROWID
        WHERE c.chat_identifier = ?
        """,
        (chat_identifier,),
    )
    return [row[0] for row in cur.fetchall()]


# ─────────────────────────────────────────────
#  API: database status
# ─────────────────────────────────────────────

_IS_BUNDLED = bool(getattr(sys, "frozen", False))


@app.get("/api/db-status")
def db_status():
    base = {
        "db_path": str(DEFAULT_DB_PATH),
        "bundled": _IS_BUNDLED,
    }
    try:
        check_database_access(DEFAULT_DB_PATH)
        return {**base, "ok": True, "kind": None, "detail": None}
    except DatabaseAccessError as e:
        return {**base, "ok": False, "kind": e.kind, "detail": e.detail}


# ─────────────────────────────────────────────
#  API: contacts
# ─────────────────────────────────────────────

@app.get("/api/contacts")
def get_contacts():
    return {"contacts": _contacts_as_dicts()}


@app.post("/api/contacts")
def add_contact(contact: ContactIn):
    name = contact.name.strip()
    raw_id = contact.identifier.strip()
    if not name or not raw_id:
        raise HTTPException(status_code=400, detail="Name and identifier are required.")

    identifier = normalize_identifier(raw_id)
    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    if any(normalize_identifier(i) == identifier for _, i in contacts):
        raise HTTPException(
            status_code=409,
            detail=f"{identifier} is already in your contacts.",
        )

    contacts.append((name, identifier))
    if not save_contacts(contacts, DEFAULT_CSV_PATH):
        raise HTTPException(status_code=500, detail="Couldn't save contacts.csv.")

    return {"contact": {"name": name, "identifier": identifier}}


@app.delete("/api/contacts/{identifier:path}")
def remove_contact(identifier: str):
    target = normalize_identifier(identifier.strip())
    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    remaining = [(n, i) for n, i in contacts if normalize_identifier(i) != target]
    if len(remaining) == len(contacts):
        raise HTTPException(status_code=404, detail="Contact not found.")
    if not save_contacts(remaining, DEFAULT_CSV_PATH):
        raise HTTPException(status_code=500, detail="Couldn't save contacts.csv.")
    return {"removed": target, "remaining": len(remaining)}


# ─────────────────────────────────────────────
#  API: macOS Contacts (address book)
# ─────────────────────────────────────────────

@app.get("/api/address-book/status")
def address_book_status():
    try:
        check_access()
        return {"ok": True, "kind": None, "detail": None}
    except AddressBookError as e:
        return {"ok": False, "kind": e.kind, "detail": e.detail}


@app.get("/api/address-book")
def address_book(refresh: int = 0):
    try:
        people = fetch_address_book(refresh=bool(refresh))
    except AddressBookError as e:
        raise HTTPException(
            status_code=503,
            detail={"kind": e.kind, "detail": e.detail},
        )
    return {"contacts": people}


# ─────────────────────────────────────────────
#  API: group chats from chat.db
# ─────────────────────────────────────────────

@app.get("/api/groups")
def list_groups():
    """Enumerate every group chat in chat.db, sorted by activity (msgs desc)."""
    try:
        check_database_access(DEFAULT_DB_PATH)
    except DatabaseAccessError as e:
        raise HTTPException(
            status_code=503,
            detail={"kind": e.kind, "detail": e.detail},
        )

    already_added = {
        normalize_identifier(i)
        for _, i in (load_contacts(DEFAULT_CSV_PATH) or [])
        if i.startswith("group:")
    }

    conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    groups = []
    all_handles = set()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                c.chat_identifier,
                c.display_name,
                (SELECT GROUP_CONCAT(h.id, char(31))
                   FROM chat_handle_join chj
                   JOIN handle h ON chj.handle_id = h.ROWID
                  WHERE chj.chat_id = c.ROWID) AS participants,
                (SELECT COUNT(*) FROM chat_message_join cmj
                  WHERE cmj.chat_id = c.ROWID) AS msg_count
            FROM chat c
            WHERE c.chat_identifier LIKE 'chat%'
            ORDER BY msg_count DESC
            """
        )
        for chat_identifier, display_name, participants_str, msg_count in cur.fetchall():
            participants = (participants_str or "").split(chr(31)) if participants_str else []
            participants = [p for p in participants if p]
            for h in participants:
                all_handles.add(h)
            groups.append({
                "chat_identifier": chat_identifier,
                "display_name": (display_name or "").strip(),
                "participants": participants,
                "message_count": msg_count,
                "already_added": f"group:{chat_identifier}" in already_added,
            })
    finally:
        conn.close()

    # Resolve participant names so the picker can show real names instead of
    # raw phones. Auto-fetches the address book on first call (~10s on a
    # large book, cached for the rest of the session).
    name_map = _build_handle_name_map(all_handles, allow_fetch=True)
    for g in groups:
        g["participant_names"] = [
            name_map.get(h, h) for h in g["participants"]
        ]
        if not g["display_name"]:
            # Generate a friendly fallback from the first few participant names.
            preview = ", ".join(g["participant_names"][:3])
            extra = len(g["participant_names"]) - 3
            g["display_name"] = (
                f"Group: {preview}" + (f" +{extra} more" if extra > 0 else "")
            )

    return {"groups": groups}


# ─────────────────────────────────────────────
#  API: export
# ─────────────────────────────────────────────

@app.post("/api/export")
def run_export_api(payload: ExportIn):
    try:
        check_database_access(DEFAULT_DB_PATH)
    except DatabaseAccessError as e:
        raise HTTPException(
            status_code=503,
            detail={"kind": e.kind, "detail": e.detail},
        )

    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    if not contacts:
        raise HTTPException(status_code=400, detail="No contacts to export. Add some first.")

    Path(DEFAULT_OUTPUT_DIR).mkdir(parents=True, exist_ok=True)

    results = []
    conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    try:
        for name, raw_id in contacts:
            identifier = normalize_identifier(raw_id)
            try:
                name_map = {}
                if identifier.startswith("group:"):
                    chat_id = identifier[len("group:"):]
                    handles = _participants_for_group(conn, chat_id)
                    name_map = _build_handle_name_map(handles)
                export_conversation(
                    conn, name, identifier, DEFAULT_OUTPUT_DIR,
                    payload.my_name, LOCAL_TZ,
                    sender_name_map=name_map,
                )
                rows = query_messages(conn, identifier)
                results.append({
                    "name": name,
                    "identifier": identifier,
                    "count": len(rows),
                    "messages": _serialize_messages(rows, sender_name_map=name_map),
                    "error": None,
                })
            except Exception as e:
                results.append({
                    "name": name,
                    "identifier": identifier,
                    "count": 0,
                    "messages": [],
                    "error": str(e),
                })
    finally:
        conn.close()

    return {
        "my_name": payload.my_name,
        "output_dir": str(DEFAULT_OUTPUT_DIR),
        "conversations": results,
    }


# ─────────────────────────────────────────────
#  API: conversations (re-query DB for the bubble view)
# ─────────────────────────────────────────────

@app.get("/api/conversations")
def list_conversations():
    """List exported .txt files so the sidebar can show what's available.

    Each item carries the contact's **csv name** (which may differ from the
    .txt filename when the name contained emoji or other stripped chars) so
    the frontend can fetch the conversation by the canonical name. Also
    includes `is_group` so the sidebar can split individuals vs groups.
    """
    output_dir = Path(DEFAULT_OUTPUT_DIR)
    if not output_dir.exists():
        return {"conversations": []}

    # Map .txt stem (after safe_filename) → (csv_name, identifier).
    by_stem = {}
    for n, i in (load_contacts(DEFAULT_CSV_PATH) or []):
        by_stem[_safe_filename(n)] = (n, normalize_identifier(i))

    items = []
    for txt in sorted(output_dir.glob("*.txt")):
        stem = txt.stem
        csv_name, identifier = by_stem.get(stem, (stem, None))
        items.append({
            "name": csv_name,
            "display_name": stem,
            "identifier": identifier,
            "is_group": bool(identifier and identifier.startswith("group:")),
            "file": txt.name,
        })
    return {"conversations": items}


@app.get("/api/conversations/{name}")
def get_conversation(name: str):
    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    # First try exact match (the common case), then fall back to safe_filename
    # so the bubble viewer works for groups whose name contains emoji/etc.
    match = next(((n, i) for n, i in contacts if n == name), None)
    if not match:
        match = next(((n, i) for n, i in contacts if _safe_filename(n) == name), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"No contact named {name!r}.")

    contact_name, raw_id = match
    identifier = normalize_identifier(raw_id)

    try:
        check_database_access(DEFAULT_DB_PATH)
    except DatabaseAccessError as e:
        raise HTTPException(
            status_code=503,
            detail={"kind": e.kind, "detail": e.detail},
        )

    conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    try:
        rows = query_messages(conn, identifier)
        name_map = {}
        is_group = identifier.startswith("group:")
        if is_group:
            handles = _participants_for_group(conn, identifier[len("group:"):])
            name_map = _build_handle_name_map(handles, allow_fetch=True)
    finally:
        conn.close()

    return {
        "name": contact_name,
        "identifier": identifier,
        "is_group": is_group,
        "count": len(rows),
        "messages": _serialize_messages(rows, sender_name_map=name_map),
    }


# ─────────────────────────────────────────────
#  API: search across exported conversations
# ─────────────────────────────────────────────

def _safe_filename(name: str) -> str:
    """Mirror the safe_name logic in export_conversation."""
    return "".join(c for c in name if c.isalnum() or c in " _-").strip()


@app.get("/api/search")
def search(q: str, contact: str | None = None, offset: int = 0, limit: int = 10):
    """Search messages in exported conversations for a substring.

    Scope = contacts that have a corresponding .txt file in exports/. If
    `contact` is supplied, scope narrows to just that one.
    """
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(
            status_code=400,
            detail="Query must be at least 2 characters.",
        )
    needle = query.lower()
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    try:
        check_database_access(DEFAULT_DB_PATH)
    except DatabaseAccessError as e:
        raise HTTPException(
            status_code=503,
            detail={"kind": e.kind, "detail": e.detail},
        )

    output_dir = Path(DEFAULT_OUTPUT_DIR)
    exported_stems = (
        {p.stem for p in output_dir.glob("*.txt")} if output_dir.exists() else set()
    )

    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    if contact:
        targets = [(n, i) for n, i in contacts if n == contact]
        if not targets:
            raise HTTPException(status_code=404, detail=f"No contact named {contact!r}.")
    else:
        targets = [(n, i) for n, i in contacts if _safe_filename(n) in exported_stems]

    hits = []
    conn = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    try:
        for name, raw_id in targets:
            identifier = normalize_identifier(raw_id)
            rows = query_messages(conn, identifier)
            if not rows:
                continue
            name_map = {}
            if identifier.startswith("group:"):
                handles = _participants_for_group(conn, identifier[len("group:"):])
                name_map = _build_handle_name_map(handles, allow_fetch=True)
            serialized = _serialize_messages(rows, sender_name_map=name_map)
            for idx, msg in enumerate(serialized):
                if needle in msg["text"].lower():
                    before = serialized[max(0, idx - 3) : idx]
                    after = serialized[idx + 1 : idx + 4]
                    hits.append({
                        "contact_name": name,
                        "contact_identifier": identifier,
                        "match_index": idx,
                        "match": msg,
                        "before": before,
                        "after": after,
                    })
    finally:
        conn.close()

    total = len(hits)
    page = hits[offset : offset + limit]
    return {
        "query": query,
        "total": total,
        "offset": offset,
        "limit": limit,
        "hits": page,
    }


# ─────────────────────────────────────────────
#  Static frontend
# ─────────────────────────────────────────────

@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ─────────────────────────────────────────────
#  Launch
# ─────────────────────────────────────────────

def _open_browser_when_ready():
    """Give uvicorn a moment to bind the port, then pop the browser open."""
    time.sleep(0.8)
    webbrowser.open(f"http://{HOST}:{PORT}")


def main():
    print()
    print("=" * 60)
    print(f"  iMessage Exporter — Web UI")
    print(f"  → http://{HOST}:{PORT}")
    print(f"  (Ctrl-C to stop)")
    print("=" * 60)
    print()

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
