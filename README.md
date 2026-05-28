# iMessage Exporter

Back up your macOS iMessage conversations to clean, plain-text files —
one per contact, formatted and read-only.

```
========================================================================
  Conversation with : Jane Smith
  Phone / identifier: +15551234567
  Exported on       : 2026-05-20 at 03:45 PM EST
  Total messages    : 1,234
========================================================================

Timestamp             Sender |  Message
------------------------------------------------------------------------
2024-01-15  10:23 AM  Jane   |  Hey! Are you free tonight?
2024-01-15  10:25 AM  Asher  |  Yeah, what's up?
2024-01-15  10:26 AM  Jane   |  Want to grab dinner?
```

## Requirements

- **macOS** (this only works on a Mac — Messages.app's database doesn't
  exist on Windows or Linux)
- **Python 3.8+** (already installed on every modern Mac)
- **Full Disk Access** for the terminal app you're running it from
  (see [Setup](#setup) below — this is the #1 thing people miss)
- iMessage signed in on this Mac

No third-party dependencies — uses only the Python standard library.

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/imessage-exporter.git
cd imessage-exporter
```

### 2. Grant Full Disk Access to your terminal app

macOS protects the Messages database. Without this step, the script
can't read your messages — it'll print a detailed error explaining
exactly what to do, but here's the gist:

1. Open **System Settings** (Apple menu → System Settings…)
2. Click **Privacy & Security** in the sidebar
3. Click **Full Disk Access**
4. Find your terminal app in the list and toggle it ON. If it isn't
   listed, click **+** and add it from /Applications.

   - Using Terminal.app? → Applications → Utilities → Terminal
   - Using iTerm? → Applications → iTerm
   - Using VS Code? → Applications → Visual Studio Code
   - Using Cursor? → Applications → Cursor
   - Using Warp? → Applications → Warp

5. **Fully quit and reopen the terminal app** (⌘Q, then reopen). A
   reload is *not* enough — macOS only re-checks Full Disk Access on
   a fresh launch.

> **Heads up:** if you use the built-in terminal in VS Code or Cursor,
> you need to grant access to **VS Code / Cursor itself**, not Terminal.app.

### 3. Run it

You have two ways to use the tool:

#### Web UI (recommended)

```bash
pip install -r requirements.txt
python3 app.py
```

Your browser opens to `http://127.0.0.1:8765` with a clean interface for
managing contacts, kicking off exports, and viewing each conversation as
iMessage-style chat bubbles.

The Contacts tab has an **Import from Contacts** button that pulls names and
phone numbers straight from macOS Contacts.app, plus an autocomplete on the
Name field. The first time you use either, macOS will pop a one-time
**"Allow access to Contacts"** prompt — grant it and you're set.

#### Terminal menu

```bash
python3 main.py
```

You'll get a menu:

```
  Main menu
  1. Manage contacts (add / list / remove)
  2. Export messages
  3. Quit
```

## Usage

### Add contacts

Pick **1. Manage contacts → 1. Add contacts** and enter names and
phone numbers (or Apple ID emails). Phone numbers can be written any
way — `+1 (555) 123-4567`, `555-123-4567`, `5551234567` — and will be
normalized automatically.

Contacts are saved to `contacts.csv` in the repo root.

### Export

Pick **2. Export messages**. You'll be asked what name to use for
yourself in the logs (the sender label on your messages). The script
then dumps one `.txt` file per contact into `./exports/`.

Each file is set read-only after writing so you don't accidentally
modify the backup.

### Edit the CSV by hand

You can also skip the menu and edit `contacts.csv` directly. The format:

```csv
name,identifier
Jane Smith,+15551234567
Bob,bob@icloud.com
```

See `contacts.example.csv` for a template.

## How it works

macOS Messages.app stores everything in a SQLite database at
`~/Library/Messages/chat.db`. This script reads from that file
**read-only**, queries each contact's conversation, and writes the
messages to a text file. It never modifies the database.

## Privacy

- `contacts.csv` and `exports/` are gitignored — they will never be
  committed by accident.
- The script only exports conversations for contacts you explicitly
  add. It doesn't read or upload anything else.
- All processing happens locally on your Mac. No network calls.

## Troubleshooting

The script tries hard to give you a clear error for every failure
mode. If something goes wrong, read the error message — it'll usually
tell you exactly what to do. The most common issues:

| Symptom | Cause | Fix |
|--------|-------|-----|
| "Permission denied" or "unable to open database" | Terminal app lacks Full Disk Access | Follow [Setup](#setup) step 2, **and fully quit the terminal after granting access** |
| Error after granting access | Forgot to quit + reopen the terminal | ⌘Q, then reopen |
| "Messages.app has never been opened" | iMessage not set up on this Mac | Open Messages.app, sign in, send/receive a message, try again |
| "Database file is locked" | Messages.app is open | Quit Messages.app, then run the script |
| Granted access to the wrong app | Common with VS Code / Cursor users | Grant access to the actual app running the terminal, not Terminal.app |
| Running over SSH | Full Disk Access can't be granted to a remote session | Run locally on the Mac instead |

## License

MIT — see [LICENSE](LICENSE).
