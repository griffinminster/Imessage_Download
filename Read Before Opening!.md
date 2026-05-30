# Read Before Opening!

Thanks for trying **iMessage Exporter** — a small Mac app that backs up
your iMessage conversations to plain-text files on your computer.

Setup takes about a minute, but macOS asks for a few permissions
along the way. Follow the steps below in order and you'll be set.

---

## What's in this folder

- **iMessage Exporter.app** — the app itself.
- **Read Before Opening!.md** — this file.

Drag the app to your **Applications** folder before you continue.

---

## Step 1 — Get past the "unidentified developer" warning

This app is open-source and isn't registered with Apple, so the first
launch needs one extra click. (Apple does this for any app not from
the App Store — it's normal.)

1. Double-click **iMessage Exporter.app**.
2. macOS will say *"…cannot be opened because the developer cannot
   be verified."* Click **Done**. (Do **not** click "Move to Trash".)
3. Open **System Settings → Privacy & Security**.
4. Scroll down to the **Security** section. You'll see a line about
   iMessage Exporter being blocked, with an **Open Anyway** button.
   Click it. Enter your password if asked. Confirm.
5. Double-click the app again. You'll get one last
   *"Are you sure?"* dialog — click **Open**.

The app should now launch and open a tab in your browser.

---

## Step 2 — Grant Full Disk Access

When the browser tab loads, you'll see a red banner near the top:
*"Can't read the iMessage database."* That's expected — Apple keeps
your messages in a protected folder, and the app needs your
permission to look inside. Here's how to grant it:

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Click the **+** button at the bottom of the list.
3. Navigate to **Applications**, choose **iMessage Exporter**, and
   click Open.
4. Make sure the toggle next to it is **on**.
5. **Right-click the app's icon in your Dock → Quit**, then re-open
   the app.

The red banner should now be gone, and your contacts list and
exports will work.

> **Why does it need this?** macOS keeps your iMessage history in a
> protected folder, so any app that reads it needs explicit
> permission. This is the same access Apple's Mail.app and Time
> Machine ask for. iMessage Exporter only reads (never edits or
> sends) your messages, runs entirely on your Mac, and makes no
> internet connections — nothing about your conversations leaves
> this computer.

---

## Step 3 — Allow Contacts (only if you want the pickers)

When you click **"📇 Import from Contacts"** or **"👥 Import groups"**
the first time, macOS will ask if iMessage Exporter can read your
Contacts. Click **OK** / **Allow**.

This is purely so you can pick names from a list instead of typing
phone numbers. You can skip this entirely and just type contacts
in by hand if you prefer.

---

## Where your exports go

By default, exported `.txt` files land in:

```
~/Documents/iMessage Exports/
```

You can change this from the **Export** tab inside the app — there's
a "Save .txt files to" field where you can type a path or click
**Browse…** to pick a folder with the native macOS picker.

---

## Privacy recap

- Everything runs on your Mac. The app makes **no internet
  connections**.
- The app **only reads** your messages — it never modifies, deletes,
  or sends anything.
- Your contact list is stored at
  `~/Library/Application Support/iMessage Exporter/`.
- To uninstall: drag the app to the Trash. To also wipe its data,
  delete the folder above.
- To revoke permissions any time: System Settings → Privacy &
  Security → Full Disk Access (or Contacts) → remove iMessage
  Exporter or toggle it off.

---

## Troubleshooting

**"Permission denied" banner still showing after granting Full Disk
Access?** macOS only re-checks permissions when an app is launched
fresh. Right-click the Dock icon → **Quit** (a window-close isn't
enough), then re-open the app.

**Contacts picker shows raw phone numbers instead of names?** Make
sure Contacts.app is set up on this Mac and that you granted Contacts
access on the prompt. You can also re-prompt by quitting + relaunching
the app.

That's it — enjoy!
