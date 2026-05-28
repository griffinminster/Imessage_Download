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
STATIC_DIR = REPO_ROOT / "web" / "static"

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


def _serialize_messages(rows, tz=LOCAL_TZ):
    """Convert raw DB rows into a JSON-friendly shape for the bubble viewer."""
    out = []
    for apple_ts, is_from_me, text in rows:
        if apple_ts:
            unix_ts = apple_ts / 1_000_000_000 + 978_307_200
            dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(tz)
            iso = dt.isoformat()
            display = apple_timestamp_to_local(apple_ts, tz=tz)
        else:
            iso = None
            display = "Unknown time"
        out.append({
            "timestamp": iso,
            "timestamp_display": display,
            "is_from_me": bool(is_from_me),
            "text": text or "",
        })
    return out


# ─────────────────────────────────────────────
#  API: database status
# ─────────────────────────────────────────────

@app.get("/api/db-status")
def db_status():
    try:
        check_database_access(DEFAULT_DB_PATH)
        return {"ok": True, "kind": None, "detail": None, "db_path": str(DEFAULT_DB_PATH)}
    except DatabaseAccessError as e:
        return {
            "ok": False,
            "kind": e.kind,
            "detail": e.detail,
            "db_path": str(DEFAULT_DB_PATH),
        }


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
                export_conversation(
                    conn, name, identifier, DEFAULT_OUTPUT_DIR, payload.my_name, LOCAL_TZ
                )
                rows = query_messages(conn, identifier)
                results.append({
                    "name": name,
                    "identifier": identifier,
                    "count": len(rows),
                    "messages": _serialize_messages(rows),
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
    """List exported .txt files so the sidebar can show what's available."""
    output_dir = Path(DEFAULT_OUTPUT_DIR)
    if not output_dir.exists():
        return {"conversations": []}

    contacts = {n: normalize_identifier(i) for n, i in (load_contacts(DEFAULT_CSV_PATH) or [])}

    items = []
    for txt in sorted(output_dir.glob("*.txt")):
        stem = txt.stem
        identifier = contacts.get(stem)
        items.append({
            "name": stem,
            "identifier": identifier,
            "file": txt.name,
        })
    return {"conversations": items}


@app.get("/api/conversations/{name}")
def get_conversation(name: str):
    contacts = load_contacts(DEFAULT_CSV_PATH) or []
    match = next(((n, i) for n, i in contacts if n == name), None)
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
    finally:
        conn.close()

    return {
        "name": contact_name,
        "identifier": identifier,
        "count": len(rows),
        "messages": _serialize_messages(rows),
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
