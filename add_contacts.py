#!/usr/bin/env python3
"""
Contact Manager
---------------
Interactive add / list / remove for the contacts.csv file used by
export_imessages.py.

Can be run directly:
    python3 add_contacts.py

Or imported and used from main.py.
"""

import csv
import sys
from pathlib import Path

from export_imessages import (
    DEFAULT_CSV_PATH,
    DIVIDER,
    normalize_identifier,
)


def load_contacts(csv_path=DEFAULT_CSV_PATH):
    """Read contacts.csv into a list of (name, identifier) tuples.

    Returns [] if the file doesn't exist yet — that's fine, it just means
    nobody's added anyone yet.
    """
    csv_path = Path(csv_path)
    if not csv_path.exists():
        return []

    contacts = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("name") or "").strip()
                identifier = (row.get("identifier") or "").strip()
                if name and identifier:
                    contacts.append((name, identifier))
    except (csv.Error, UnicodeDecodeError) as e:
        print(f"❌  Couldn't read {csv_path}: {e}")
        print("    The file may be corrupted. Check it has 'name,identifier' columns.")
        return None  # signals an actual error vs. just "empty"
    return contacts


def save_contacts(contacts, csv_path=DEFAULT_CSV_PATH):
    """Write the contacts list back to disk."""
    csv_path = Path(csv_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["name", "identifier"])
            for name, identifier in contacts:
                writer.writerow([name, identifier])
        return True
    except OSError as e:
        print(f"❌  Couldn't save {csv_path}: {e}")
        return False


def list_contacts(csv_path=DEFAULT_CSV_PATH):
    """Show all current contacts in a numbered list. Returns the list."""
    contacts = load_contacts(csv_path)
    if contacts is None:
        return []

    print()
    print(DIVIDER)
    print("  Current contacts")
    print(DIVIDER)
    if not contacts:
        print()
        print("  (no contacts yet — add some with option 1)")
        print()
        print(DIVIDER)
        print()
        return []

    # Width of the index column, e.g. "12." for 12+ contacts
    idx_w = len(str(len(contacts))) + 1
    name_w = max((len(n) for n, _ in contacts), default=4)
    name_w = max(name_w, len("Name"))

    print()
    print(f"  {'#':<{idx_w}}  {'Name':<{name_w}}  Identifier")
    print(f"  {'-' * idx_w}  {'-' * name_w}  {'-' * 30}")
    for i, (name, identifier) in enumerate(contacts, 1):
        print(f"  {f'{i}.':<{idx_w}}  {name:<{name_w}}  {identifier}")
    print()
    print(f"  Total: {len(contacts)}")
    print(DIVIDER)
    print()
    return contacts


def add_contact_interactive(csv_path=DEFAULT_CSV_PATH):
    """Prompt for a new contact and append it. Loops until the user is done."""
    contacts = load_contacts(csv_path)
    if contacts is None:
        return  # file exists but is corrupted; load_contacts already printed

    print()
    print(DIVIDER)
    print("  Add contact(s)")
    print(DIVIDER)
    print()
    print("  Enter a name and an identifier (phone number or Apple ID email).")
    print("  Leave the name blank when you're done adding.")
    print()
    print("  Phone numbers can be entered with or without spaces, dashes,")
    print("  parentheses, or a + prefix — they'll be normalized to +1234567890")
    print(f"  format automatically.  \033[31mMAKE SURE TO INCLUDE COUNTRY CODE (1 for USA).\033[0m")    
    print()

    existing_ids = {normalize_identifier(i) for _, i in contacts}
    added = 0

    while True:
        try:
            name = input("  Name (blank to finish): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not name:
            break

        try:
            raw_id = input("  Phone or email: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw_id:
            print("  ⚠️  No identifier entered — skipping this contact.")
            print()
            continue

        identifier = normalize_identifier(raw_id)

        # Warn on obvious duplicates but let the user override
        if identifier in existing_ids:
            print(f"  ⚠️  {identifier} is already in your contacts.")
            try:
                confirm = input("  Add it again anyway? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if confirm != "y":
                print("  Skipped.")
                print()
                continue

        contacts.append((name, identifier))
        existing_ids.add(identifier)
        added += 1
        print(f"  ✅  Added: {name}  →  {identifier}")
        print()

    if added > 0:
        if save_contacts(contacts, csv_path):
            print(f"💾  Saved {added} new contact(s) to {csv_path}")
        # save_contacts prints its own error if it fails
    else:
        print("  (no contacts added)")
    print()


def remove_contact_interactive(csv_path=DEFAULT_CSV_PATH):
    """Show the list and let the user pick one (or more) to remove."""
    contacts = list_contacts(csv_path)
    if not contacts:
        return

    print("  Enter the number(s) of the contact(s) to remove.")
    print("  Examples:  3        (single)")
    print("             1,4,7    (multiple)")
    print("             1-3      (range)")
    print("  Leave blank to cancel.")
    print()

    try:
        choice = input("  Remove #: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if not choice:
        print("  Cancelled.")
        print()
        return

    # Parse the user input into a set of indices
    indices_to_remove = set()
    try:
        for part in choice.split(","):
            part = part.strip()
            if "-" in part:
                start, end = part.split("-", 1)
                start, end = int(start.strip()), int(end.strip())
                if start > end:
                    start, end = end, start
                indices_to_remove.update(range(start, end + 1))
            else:
                indices_to_remove.add(int(part))
    except ValueError:
        print(f"  ❌  Couldn't parse '{choice}'. Use numbers like: 3  or  1,4,7  or  1-3")
        print()
        return

    # Validate
    invalid = [i for i in indices_to_remove if i < 1 or i > len(contacts)]
    if invalid:
        print(f"  ❌  Invalid number(s): {', '.join(str(i) for i in sorted(invalid))}")
        print(f"      Valid range is 1 to {len(contacts)}.")
        print()
        return

    # Confirm
    to_remove = [(i, contacts[i - 1]) for i in sorted(indices_to_remove)]
    print()
    print("  About to remove:")
    for i, (name, identifier) in to_remove:
        print(f"    {i}. {name}  ({identifier})")
    print()
    try:
        confirm = input("  Confirm? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    if confirm != "y":
        print("  Cancelled.")
        print()
        return

    # Keep everything NOT in indices_to_remove (1-indexed)
    remaining = [c for i, c in enumerate(contacts, 1) if i not in indices_to_remove]
    if save_contacts(remaining, csv_path):
        print(f"  ✅  Removed {len(to_remove)} contact(s). {len(remaining)} remaining.")
    print()


# ─────────────────────────────────────────────
#  Standalone entry point
# ─────────────────────────────────────────────

def _standalone_menu():
    """Mini menu for when this file is run directly (not via main.py)."""
    while True:
        print()
        print("Contact Manager")
        print(DIVIDER)
        print("  1. Add contacts")
        print("  2. List contacts")
        print("  3. Remove contacts")
        print("  4. Quit")
        print(DIVIDER)
        try:
            choice = input("  Choose: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice == "1":
            add_contact_interactive()
        elif choice == "2":
            list_contacts()
        elif choice == "3":
            remove_contact_interactive()
        elif choice == "4" or choice.lower() in ("q", "quit", "exit"):
            return
        else:
            print(f"  ❌  Unknown option: {choice!r}")


if __name__ == "__main__":
    _standalone_menu()
