#!/usr/bin/env python3
"""
iMessage Exporter — Main Menu
-----------------------------
Entry point. Provides a simple numbered menu for managing contacts
and running exports.

Usage:
    python3 main.py
"""

import sys

from export_imessages import (
    DEFAULT_MY_NAME,
    DEFAULT_CSV_PATH,
    DIVIDER,
    run_export,
)
from add_contacts import (
    add_contact_interactive,
    list_contacts,
    remove_contact_interactive,
    load_contacts,
)


def prompt_for_name():
    """Ask the user what name to use for themselves in the exported logs."""
    print()
    print("  What name should appear on YOUR messages in the export?")
    print("  (e.g. 'Asher' — used as the sender label on your texts)")
    try:
        name = input("  Your name: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return name or DEFAULT_MY_NAME


def contacts_submenu():
    """The 'Manage contacts' branch of the main menu."""
    while True:
        print()
        print(DIVIDER)
        print("  Manage contacts")
        print(DIVIDER)
        print("  1. Add contacts")
        print("  2. List contacts")
        print("  3. Remove contacts")
        print("  4. Back to main menu")
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
        elif choice == "4" or choice.lower() in ("b", "back", "q", "quit"):
            return
        else:
            print(f"  ❌  Unknown option: {choice!r}")


def export_branch():
    """The 'Export messages' branch of the main menu."""
    # Make sure they have contacts first — easier to catch this here than to
    # let run_export print the "no contacts" error.
    contacts = load_contacts()
    if not contacts:
        print()
        print("  ⚠️  You don't have any contacts yet. Add some first")
        print("      (main menu → 1. Manage contacts → 1. Add contacts).")
        print()
        return

    print()
    print(f"  Ready to export {len(contacts)} conversation(s).")
    my_name = prompt_for_name()
    if my_name is None:
        return

    run_export(my_name=my_name)


def main():
    print()
    print(DIVIDER)
    print("  iMessage Exporter")
    print(DIVIDER)
    print()
    print("  Back up your iMessage conversations to plain-text files.")
    print("  See README.md for setup (Full Disk Access is required).")

    while True:
        print()
        print(DIVIDER)
        print("  Main menu")
        print(DIVIDER)
        print("  1. Manage contacts (add / list / remove)")
        print("  2. Export messages")
        print("  3. Quit")
        print(DIVIDER)
        try:
            choice = input("  Choose: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if choice == "1":
            contacts_submenu()
        elif choice == "2":
            export_branch()
        elif choice == "3" or choice.lower() in ("q", "quit", "exit"):
            print()
            print("  👋  Bye!")
            print()
            return
        else:
            print(f"  ❌  Unknown option: {choice!r}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print("  (interrupted)")
        sys.exit(130)
