#!/usr/bin/env python3
"""
iMessage Exporter
-----------------
Reads contacts from a CSV file and exports iMessage conversations
to formatted, read-only text files.

Can be run directly:
    python3 export_imessages.py

Or imported and called from main.py.
"""

import sys
import sqlite3
import csv
import os
import stat
import platform
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────
#  Defaults — used when no overrides are passed
# ─────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent


def _user_data_dir():
    """Where to read/write contacts.csv and exports/.

    When running from source (dev), we keep everything in the repo root so
    git status is the source of truth. When running as a frozen .app bundle
    (Contents/Resources is read-only and shared between users), we move to
    ~/Library/Application Support/iMessage Exporter/ so the user's data is
    persistent and writable across launches.
    """
    if getattr(sys, "frozen", False):
        path = Path.home() / "Library" / "Application Support" / "iMessage Exporter"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return REPO_ROOT


USER_DATA_DIR      = _user_data_dir()
DEFAULT_MY_NAME    = "Me"
DEFAULT_CSV_PATH   = USER_DATA_DIR / "contacts.csv"
DEFAULT_OUTPUT_DIR = USER_DATA_DIR / "exports"
DEFAULT_DB_PATH    = Path(os.path.expanduser("~/Library/Messages/chat.db"))

# Default timezone is whatever the local machine is set to
LOCAL_TZ = datetime.now().astimezone().tzinfo

DIVIDER = "=" * 72


# ─────────────────────────────────────────────
#  Small helpers
# ─────────────────────────────────────────────

def normalize_identifier(identifier):
    """Normalize a phone number into the +<country><number> form used by chat.db.

    - Emails are passed through unchanged.
    - Strips spaces, dashes, parentheses, and dots.
    - 10-digit input → assumed US, prepends +1  (the common case from
      Contacts.app, which stores plenty of unformatted local numbers).
    - 11-digit input starting with 1 → prepends + (already has US country code).
    - Anything else already starting with + → kept as-is.
    - Other shapes (short codes, partial international numbers) → just prepend
      + so the existing fallback behavior is preserved.
    """
    # Group chats use a special "group:<chat_identifier>" form. Keep them
    # opaque — chat.db stores group chat_identifiers like "chat620531608..."
    # which already match exactly what we need to query on.
    if identifier.startswith("group:"):
        return identifier

    if "@" in identifier:
        return identifier

    cleaned = (
        identifier.replace(" ", "")
                  .replace("-", "")
                  .replace("(", "")
                  .replace(")", "")
                  .replace(".", "")
    )

    if cleaned.startswith("+"):
        return cleaned

    digits = cleaned.lstrip("+")
    if digits.isdigit():
        if len(digits) == 10:
            return "+1" + digits
        if len(digits) == 11 and digits.startswith("1"):
            return "+" + digits

    return "+" + digits


def apple_timestamp_to_local(apple_ts, tz=LOCAL_TZ):
    """Convert Apple's nanosecond timestamp to a readable local datetime string."""
    if not apple_ts:
        return "Unknown time"
    unix_ts = apple_ts / 1_000_000_000 + 978_307_200
    dt = datetime.fromtimestamp(unix_ts, tz=timezone.utc).astimezone(tz)
    return dt.strftime("%Y-%m-%d  %I:%M %p")


def first_name(full_name):
    """Return just the first word of a name."""
    return full_name.strip().split()[0] if full_name.strip() else full_name


def detect_terminal_app():
    """Best-effort guess at which terminal app is running this script.

    Reads the TERM_PROGRAM env var that macOS terminals set. Falls back to a
    generic phrase. Knowing the exact app name makes the Full Disk Access
    instructions much clearer for the user.
    """
    term = os.environ.get("TERM_PROGRAM", "").lower()
    mapping = {
        "apple_terminal": "Terminal",
        "iterm.app":      "iTerm",
        "vscode":         "VS Code or Cursor",
        "warpterminal":   "Warp",
        "hyper":          "Hyper",
        "tabby":          "Tabby",
        "alacritty":      "Alacritty",
        "kitty":          "kitty",
        "wezterm":        "WezTerm",
    }
    return mapping.get(term, "your terminal app")


# ─────────────────────────────────────────────
#  Error / pre-flight handling
# ─────────────────────────────────────────────

class DatabaseAccessError(Exception):
    """Raised when we can't read the iMessage database, for any reason."""
    def __init__(self, kind, detail=""):
        # kind is one of: "not_macos", "messages_never_set_up", "permission_denied",
        #                 "corrupted_or_locked", "unknown"
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


def check_database_access(db_path):
    """Pre-flight check: can we actually read the iMessage database?

    Distinguishes between several failure modes so we can print a tailored
    error message for each. Returns nothing on success; raises
    DatabaseAccessError on any failure.
    """
    # 1. Are we even on macOS? Messages.app only exists there.
    if platform.system() != "Darwin":
        raise DatabaseAccessError(
            "not_macos",
            f"This script reads from macOS Messages.app. Detected: {platform.system()}.",
        )

    # 2. Has iMessage ever been set up on this Mac?
    #    The ~/Library/Messages/ directory itself only exists once Messages.app
    #    has been opened and signed into at least once.
    messages_dir = Path(db_path).parent
    if not messages_dir.exists():
        raise DatabaseAccessError(
            "messages_never_set_up",
            f"{messages_dir} does not exist.",
        )

    # 3. Try a real read. We can't trust os.path.exists() or sqlite3.connect()
    #    on their own — without Full Disk Access, macOS makes the file look
    #    like it isn't there (path.exists() returns False) AND sqlite3.connect()
    #    succeeds lazily without actually opening the file. The only honest
    #    test is to run a query.
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            conn.execute("SELECT COUNT(*) FROM message LIMIT 1").fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "unable to open" in msg or "authorization" in msg or "permission" in msg:
            raise DatabaseAccessError("permission_denied", str(e)) from e
        if "no such table" in msg or "not a database" in msg:
            raise DatabaseAccessError("corrupted_or_locked", str(e)) from e
        raise DatabaseAccessError("unknown", str(e)) from e
    except sqlite3.DatabaseError as e:
        raise DatabaseAccessError("corrupted_or_locked", str(e)) from e
    except PermissionError as e:
        raise DatabaseAccessError("permission_denied", str(e)) from e
    except OSError as e:
        # Catch-all for other low-level filesystem issues
        raise DatabaseAccessError("unknown", str(e)) from e


def print_error(err: DatabaseAccessError, db_path):
    """Route a DatabaseAccessError to the right tailored message."""
    if err.kind == "not_macos":
        _print_not_macos(err.detail)
    elif err.kind == "messages_never_set_up":
        _print_messages_never_set_up(db_path)
    elif err.kind == "permission_denied":
        _print_full_disk_access_help(db_path, err.detail)
    elif err.kind == "corrupted_or_locked":
        _print_corrupted_or_locked(db_path, err.detail)
    else:
        _print_unknown(db_path, err.detail)


def _box(title):
    print()
    print("=" * 72)
    print(f"  ❌  {title}")
    print("=" * 72)
    print()


def _print_not_macos(detail):
    _box("THIS SCRIPT ONLY WORKS ON macOS")
    print(f"  {detail}")
    print()
    print("  Why: iMessage stores its history in a SQLite database that only")
    print("  exists on a Mac running Messages.app. There is no equivalent file")
    print("  on Windows or Linux.")
    print()
    print("  If you want to back up your iMessages, you'll need to run this")
    print("  script on the Mac where you receive them.")
    print()
    print("=" * 72)
    print()


def _print_messages_never_set_up(db_path):
    _box("MESSAGES.APP HAS NEVER BEEN OPENED ON THIS MAC")
    print(f"  Looking for: {db_path}")
    print(f"  But the folder it lives in doesn't exist yet.")
    print()
    print("  This usually means one of two things:")
    print()
    print("  1. You've never signed into iMessage on this Mac.")
    print("     → Open Messages.app from your Applications folder, sign in")
    print("       with your Apple ID, send or receive at least one message,")
    print("       then run this script again.")
    print()
    print("  2. You're running as a different user than the one signed into")
    print("     iMessage. The script reads from the *current user's* home")
    print("     folder, so make sure you're logged in as that user.")
    print()
    print("=" * 72)
    print()


def _print_full_disk_access_help(db_path, error_detail=""):
    """The big one — the most common failure for new users."""
    terminal_name = detect_terminal_app()

    _box("CAN'T READ YOUR IMESSAGE DATABASE — PERMISSION DENIED")
    if error_detail:
        print(f"  Error details: {error_detail}")
        print()
    print(f"  Looking for: {db_path}")
    print()
    print("  macOS protects the Messages database — your terminal app needs")
    print("  explicit permission to read it. This is the #1 issue people hit")
    print("  on first run. Here's exactly how to fix it:")
    print()
    print("  ─── HOW TO GRANT FULL DISK ACCESS ─────────────────────────────")
    print()
    print("  1. Open System Settings (Apple menu  → System Settings…)")
    print()
    print("  2. In the sidebar, click:  Privacy & Security")
    print()
    print("  3. Scroll down and click:  Full Disk Access")
    print()
    print(f"  4. Look for {terminal_name} in the list.")
    print()
    print(f"     • If {terminal_name} is there:  toggle the switch ON.")
    print(f"     • If {terminal_name} is NOT there:  click the '+' button,")
    print("       then navigate to Applications and add it.")
    print()
    print("       Common locations:")
    print("         Terminal.app    →  Applications → Utilities → Terminal")
    print("         iTerm           →  Applications → iTerm")
    print("         VS Code         →  Applications → Visual Studio Code")
    print("         Cursor          →  Applications → Cursor")
    print("         Warp            →  Applications → Warp")
    print()
    print("  5. You may be prompted for your Mac password — enter it.")
    print()
    print(f"  6. IMPORTANT — fully quit {terminal_name} and reopen it.")
    print(f"     ({terminal_name} menu → Quit, or  ⌘Q.  A reload is NOT")
    print("      enough — the new permission only takes effect on a fresh")
    print("      launch of the app.)")
    print()
    print("  7. Reopen the terminal and run this script again.")
    print()
    print("  ─── COMMON GOTCHAS ────────────────────────────────────────────")
    print()
    print(f"  • Wrong app?  We detected you're running in: {terminal_name}.")
    print("    Make sure THAT app is the one with Full Disk Access — not")
    print("    just Terminal.app. If you use VS Code's or Cursor's built-in")
    print("    terminal, you need to grant access to VS Code / Cursor itself,")
    print("    not Terminal.")
    print()
    print("  • Forgot to quit and reopen?  This is by far the most common")
    print("    mistake. macOS only re-checks Full Disk Access on a fresh")
    print("    process launch. Closing the window or opening a new tab is")
    print("    not enough.")
    print()
    print("  • Running over SSH?  Full Disk Access can't be granted to a")
    print("    remote session. You'll need to run this locally on the Mac.")
    print()
    print("=" * 72)
    print()


def _print_corrupted_or_locked(db_path, detail):
    _box("DATABASE FILE IS LOCKED OR UNREADABLE")
    print(f"  Looking for: {db_path}")
    print(f"  Error details: {detail}")
    print()
    print("  Possible causes:")
    print()
    print("  • Messages.app is currently open and has the database locked.")
    print("    → Quit Messages.app (⌘Q) and try again.")
    print()
    print("  • A previous run of this script crashed and left a lock file.")
    print("    → Look for files in ~/Library/Messages/ ending in -wal or -shm")
    print("       and consider quitting Messages.app to let it clean up.")
    print()
    print("  • The database is genuinely corrupted (rare).")
    print("    → Try signing out and back into iMessage from Messages.app.")
    print()
    print("=" * 72)
    print()


def _print_unknown(db_path, detail):
    _box("UNEXPECTED ERROR READING THE DATABASE")
    print(f"  Looking for: {db_path}")
    print(f"  Error details: {detail}")
    print()
    print("  This isn't one of the failure modes we know how to diagnose.")
    print("  Some things to try:")
    print()
    print("  • Confirm Full Disk Access is granted to your terminal app")
    print("    (see the README for the full walkthrough).")
    print("  • Quit Messages.app and try again.")
    print("  • Make sure you're not running as a different user (sudo, etc.).")
    print()
    print("=" * 72)
    print()


# ─────────────────────────────────────────────
#  Export logic
# ─────────────────────────────────────────────

def _extract_attributed_text(blob):
    """Pull the message text out of an NSArchiver typedstream attributedBody blob.

    macOS Ventura+ increasingly stores message text in `attributedBody` (a
    binary NSAttributedString blob) instead of the plain `text` column —
    sometimes only 0.1% of a conversation has a non-empty `text`. The blob
    format is NSArchiver's "typedstream": after the `NSString` class name
    we find a `+` (0x2B) cstring marker, a variable-length length prefix,
    then the UTF-8 bytes.
    """
    if not blob:
        return None
    ns_idx = blob.find(b"NSString")
    if ns_idx == -1:
        return None
    plus_idx = blob.find(b"\x2b", ns_idx + len(b"NSString"))
    if plus_idx == -1:
        return None
    p = plus_idx + 1
    if p >= len(blob):
        return None
    first = blob[p]
    if first < 0x81:
        length = first
        text_start = p + 1
    elif first == 0x81 and p + 2 < len(blob):
        length = blob[p + 1] | (blob[p + 2] << 8)
        text_start = p + 3
    elif first == 0x82 and p + 4 < len(blob):
        length = (
            blob[p + 1]
            | (blob[p + 2] << 8)
            | (blob[p + 3] << 16)
            | (blob[p + 4] << 24)
        )
        text_start = p + 5
    else:
        return None
    if length <= 0 or text_start + length > len(blob):
        return None
    try:
        return blob[text_start : text_start + length].decode("utf-8", errors="replace")
    except Exception:
        return None


def query_messages(conn, identifier):
    """Return the raw message rows for one conversation, oldest first.

    Each row is (apple_ts, is_from_me, text, sender_handle). Used by both
    the .txt writer and the web bubble viewer so the query lives in
    exactly one place.

    Messages where `text` is empty but `attributedBody` is set get their
    content decoded from the typedstream blob — this catches the bulk of
    modern (macOS Ventura+) messages.

    For group chats (identifier="group:chat<id>"), `sender_handle` is the
    raw phone/email of the sender (or None for `is_from_me=1`). For 1:1
    chats `sender_handle` is always None.
    """
    cursor = conn.cursor()
    if identifier.startswith("group:"):
        chat_identifier = identifier[len("group:"):]
        cursor.execute(
            """
            SELECT
                m.date,
                m.is_from_me,
                m.text,
                m.attributedBody,
                h.id AS sender_handle
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.ROWID
            LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE c.chat_identifier = ?
              AND (
                    (m.text IS NOT NULL AND m.text != '')
                 OR m.attributedBody IS NOT NULL
              )
            ORDER BY m.date ASC
            """,
            (chat_identifier,),
        )
    else:
        cursor.execute(
            """
            SELECT
                m.date,
                m.is_from_me,
                m.text,
                m.attributedBody,
                NULL AS sender_handle
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            JOIN chat c ON cmj.chat_id = c.ROWID
            WHERE c.chat_identifier = ?
              AND (
                    (m.text IS NOT NULL AND m.text != '')
                 OR m.attributedBody IS NOT NULL
              )
            ORDER BY m.date ASC
            """,
            (identifier,),
        )

    rows = []
    for apple_ts, is_from_me, text, attr_body, sender_handle in cursor.fetchall():
        if not text:
            text = _extract_attributed_text(attr_body)
        if text:
            rows.append((apple_ts, is_from_me, text, sender_handle))
    return rows


def export_conversation(conn, name, identifier, output_dir, my_name, tz,
                        sender_name_map=None):
    """Query the DB for one conversation and write it to a formatted text file.

    For group chats, pass `sender_name_map` ({handle_id: display_name}) so the
    Sender column can show each participant's name; missing handles fall back
    to the raw phone/email.
    """
    rows = query_messages(conn, identifier)

    if not rows:
        print(f"  ⚠️  No messages found for {name} ({identifier}) — skipping.")
        return

    is_group = identifier.startswith("group:")
    sender_name_map = sender_name_map or {}

    exported_at = datetime.now(tz=tz).strftime("%Y-%m-%d at %I:%M %p %Z").strip()
    total = len(rows)

    my_first = first_name(my_name)

    if is_group:
        # Compute Sender column width from the actual senders we'll write
        # (resolved first names, falling back to raw handles).
        def resolve(handle):
            if handle is None:
                return my_first
            return first_name(sender_name_map.get(handle, handle))
        observed = {resolve(h) for _, _, _, h in rows}
        observed.add(my_first)
        max_name_len = max(len(s) for s in observed | {"Sender"})
    else:
        their_first = first_name(name)
        max_name_len = max(len(their_first), len(my_first), len("Sender"))

    col_w_time = 20

    def fmt_row(timestamp_str, sender, text):
        sender_padded = sender.ljust(max_name_len)
        return f"{timestamp_str:<{col_w_time}}  {sender_padded} |  {text}"

    if is_group:
        # Build a stable participants list from the messages themselves.
        participants_seen = []
        seen = set()
        for _, is_from_me, _, handle in rows:
            if is_from_me or handle is None or handle in seen:
                continue
            seen.add(handle)
            display = sender_name_map.get(handle, handle)
            participants_seen.append(display)
        participants_line = ", ".join(participants_seen) if participants_seen else "(unknown)"
        header_lines = [
            DIVIDER,
            f"  Group chat        : {name}",
            f"  Participants      : {participants_line}",
            f"  Exported on       : {exported_at}",
            f"  Total messages    : {total:,}",
            DIVIDER,
        ]
    else:
        header_lines = [
            DIVIDER,
            f"  Conversation with : {name}",
            f"  Phone / identifier: {identifier}",
            f"  Exported on       : {exported_at}",
            f"  Total messages    : {total:,}",
            DIVIDER,
        ]

    lines = header_lines + [
        "",
        fmt_row("Timestamp", "Sender", "Message"),
        "-" * 72,
    ]

    their_first_1to1 = first_name(name) if not is_group else None
    for apple_ts, is_from_me, text, sender_handle in rows:
        timestamp_str = apple_timestamp_to_local(apple_ts, tz=tz)
        if is_from_me:
            sender = my_first
        elif is_group:
            sender = first_name(sender_name_map.get(sender_handle, sender_handle or "?"))
        else:
            sender = their_first_1to1
        first_line, *rest = (text or "").split("\n")
        lines.append(fmt_row(timestamp_str, sender, first_line.strip()))
        for extra in rest:
            if extra.strip():
                lines.append(fmt_row("", "", extra.strip()))

    lines.append("")
    lines.append(DIVIDER)
    lines.append(f"  End of conversation — {total:,} messages")
    lines.append(DIVIDER)

    safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    file_path = Path(output_dir) / f"{safe_name}.txt"

    if file_path.exists():
        file_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    file_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)

    print(f"  ✅  {safe_name}.txt — {total:,} messages saved (read-only)")


def run_export(
    my_name=DEFAULT_MY_NAME,
    csv_path=DEFAULT_CSV_PATH,
    output_dir=DEFAULT_OUTPUT_DIR,
    db_path=DEFAULT_DB_PATH,
    tz=LOCAL_TZ,
):
    """Main entry point. Importable from main.py or runnable standalone."""
    print()
    print("iMessage Exporter")
    print(DIVIDER)

    # Pre-flight: can we actually read the database?
    try:
        check_database_access(db_path)
    except DatabaseAccessError as e:
        print_error(e, db_path)
        return False

    # Check the CSV exists
    if not Path(csv_path).exists():
        print()
        print("=" * 72)
        print("  ❌  CONTACTS FILE NOT FOUND")
        print("=" * 72)
        print()
        print(f"  Looking for: {csv_path}")
        print()
        print("  You need to create a contacts file before exporting. The easiest")
        print("  way is to run main.py and choose 'Manage contacts' from the menu —")
        print("  it'll walk you through adding contacts interactively.")
        print()
        print("  Or you can copy contacts.example.csv to contacts.csv and edit it")
        print("  by hand. The format is:")
        print()
        print("      name,identifier")
        print("      Jane Smith,+15551234567")
        print("      Bob,bob@icloud.com")
        print()
        print("=" * 72)
        print()
        return False

    # Make the output folder
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    print(f"📁  Output folder: {output_dir}")
    print()

    # Load contacts
    contacts = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("name", "").strip()
                identifier = row.get("identifier", "").strip()
                if name and identifier:
                    contacts.append((name, normalize_identifier(identifier)))
    except (csv.Error, UnicodeDecodeError) as e:
        print(f"❌  Couldn't read {csv_path}: {e}")
        print("    Make sure it's a valid UTF-8 CSV with 'name' and 'identifier' columns.")
        return False

    if not contacts:
        print(f"❌  No contacts found in {csv_path}.")
        print("    Run main.py and add some contacts, or edit the CSV by hand.")
        return False

    print(f"👥  Found {len(contacts)} contact(s)")
    print()

    # Connect and export
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.OperationalError as e:
        # This shouldn't happen since we already passed check_database_access,
        # but just in case something changed between the pre-flight and now.
        print_error(DatabaseAccessError("permission_denied", str(e)), db_path)
        return False

    try:
        for name, identifier in contacts:
            print(f"→  Exporting: {name} ({identifier})")
            try:
                export_conversation(conn, name, identifier, output_dir, my_name, tz)
            except Exception as e:
                print(f"  ❌  Error exporting {name}: {e}")
    finally:
        conn.close()

    print()
    print(DIVIDER)
    print(f"🎉  Done! All files saved to:")
    print(f"    {output_dir}")
    print()
    return True


if __name__ == "__main__":
    success = run_export()
    sys.exit(0 if success else 1)
