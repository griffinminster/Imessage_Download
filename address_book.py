#!/usr/bin/env python3
"""
macOS Contacts reader
---------------------
Uses AppleScript (via `osascript`) to read names + phones + emails out of
Contacts.app. Triggers the standard macOS Contacts permission prompt on
first use; afterwards calls are silent until the user revokes access.

No third-party dependencies — `osascript` ships with macOS.
"""

import subprocess
from typing import Optional


# AppleScript that bulk-extracts the address book using NESTED per-person
# property lists. This is alignment-safe by construction: each person's
# phones/emails are wrapped in their own sublist, so we never have to rely
# on flat-list ordering matching across separate "every X of every Y" calls
# (which AppleScript does NOT actually guarantee).
#
# Output shape: 5 fields joined by ASCII GS (0x1D):
#   names  |  phone_values  |  phone_labels  |  email_values  |  email_labels
#
# - `names` is flat, items joined by US (0x1F)
# - the other four are nested: inner items joined by US, persons by RS (0x1E)
#
# So the per-person phone values for person N are at position N in the
# RS-split of phone_values, then US-split into individual values.
_GS = chr(0x1D)  # group separator (between the 5 top-level fields)
_RS = chr(0x1E)  # record separator (between persons in a nested field)
_US = chr(0x1F)  # unit separator (between items within a person)

_DUMP_SCRIPT = f"""
set US to (ASCII character 31)
set RS to (ASCII character 30)
set GS to (ASCII character 29)
tell application "Contacts"
    set theNames to name of every person
    set thePhoneValueLists to value of phones of every person
    set thePhoneLabelLists to label of phones of every person
    set theEmailValueLists to value of emails of every person
    set theEmailLabelLists to label of emails of every person
end tell

-- Flatten the nested lists into US-per-item, RS-per-person strings.
set AppleScript's text item delimiters to US
set namesStr to theNames as text

set phoneValParts to {{}}
repeat with sub in thePhoneValueLists
    set end of phoneValParts to (sub as text)
end repeat
set phoneLblParts to {{}}
repeat with sub in thePhoneLabelLists
    set end of phoneLblParts to (sub as text)
end repeat
set emailValParts to {{}}
repeat with sub in theEmailValueLists
    set end of emailValParts to (sub as text)
end repeat
set emailLblParts to {{}}
repeat with sub in theEmailLabelLists
    set end of emailLblParts to (sub as text)
end repeat

set AppleScript's text item delimiters to RS
set phoneValStr to phoneValParts as text
set phoneLblStr to phoneLblParts as text
set emailValStr to emailValParts as text
set emailLblStr to emailLblParts as text

return namesStr & GS & phoneValStr & GS & phoneLblStr & GS & emailValStr & GS & emailLblStr
"""

# Tiny probe used by /api/address-book/status to surface the permission state
# without paying for a full dump.
_PROBE_SCRIPT = r"""
tell application "Contacts"
    count of people
end tell
"""


class AddressBookError(Exception):
    """Raised when we can't read Contacts."""
    def __init__(self, kind, detail=""):
        # kind is one of: "permission_denied", "contacts_app_missing",
        #                 "osascript_missing", "unknown"
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


_cache: Optional[list] = None


def _run_osascript(script: str, timeout: int = 30) -> str:
    """Run an AppleScript, mapping common failures to AddressBookError."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as e:
        raise AddressBookError("osascript_missing", str(e)) from e
    except subprocess.TimeoutExpired as e:
        raise AddressBookError("unknown", "osascript timed out") from e

    if result.returncode != 0:
        err = (result.stderr or "").strip()
        low = err.lower()
        # macOS returns -1743 when the user denied automation access to
        # the target app. "not authorized" / "not allowed" cover the same
        # case across macOS versions.
        if "-1743" in err or "not authorized" in low or "not allowed" in low:
            raise AddressBookError("permission_denied", err)
        if "application isn't running" in low or "can't get application" in low:
            raise AddressBookError("contacts_app_missing", err)
        raise AddressBookError("unknown", err or f"osascript exited {result.returncode}")

    return result.stdout


def check_access() -> None:
    """Quick probe. Raises AddressBookError on failure, returns None on success."""
    _run_osascript(_PROBE_SCRIPT)


def fetch_address_book(refresh: bool = False) -> list:
    """Return the user's Contacts grouped by name.

    Shape: [{"name": str,
             "phones": [{"label": str, "value": str}, ...],
             "emails": [{"label": str, "value": str}, ...]}]

    Results are cached for the lifetime of the Python process. Pass
    refresh=True to bypass.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache

    # 60s is plenty for the bulk-fetch script even on large address books.
    raw = _run_osascript(_DUMP_SCRIPT, timeout=60)
    contacts = _parse_dump(raw)
    _cache = contacts
    return contacts


def _parse_dump(raw: str) -> list:
    """Turn the GS/RS/US-delimited blob into structured contacts.

    The five fields are: names, phone-values, phone-labels, email-values,
    email-labels. The four non-name fields are RS-delimited per-person,
    where each per-person chunk is itself US-delimited.
    """
    parts = raw.split(_GS)
    if len(parts) != 5:
        raise AddressBookError(
            "unknown",
            f"Unexpected AppleScript output (got {len(parts)} fields, expected 5)",
        )
    names_str, pv_str, pl_str, ev_str, el_str = parts

    def split_flat(s: str) -> list[str]:
        return s.split(_US) if s else []

    def split_nested(s: str) -> list[list[str]]:
        # An empty top-level string means zero people (shouldn't happen, but
        # guard anyway). A person with no items shows up as the empty string
        # between two RS markers — split_flat("") returns [], which is right.
        if s == "":
            return []
        return [split_flat(chunk) for chunk in s.split(_RS)]

    names = split_flat(names_str)
    phone_vals = split_nested(pv_str)
    phone_lbls = split_nested(pl_str)
    email_vals = split_nested(ev_str)
    email_lbls = split_nested(el_str)

    n = len(names)
    if not (len(phone_vals) == len(phone_lbls) == len(email_vals)
            == len(email_lbls) == n):
        raise AddressBookError(
            "unknown",
            f"AppleScript per-person lists out of sync "
            f"(names={n}, pv={len(phone_vals)}, pl={len(phone_lbls)}, "
            f"ev={len(email_vals)}, el={len(email_lbls)})",
        )

    by_name: dict[str, dict] = {}
    for i in range(n):
        name = names[i].strip()
        if not name:
            continue
        entry = by_name.setdefault(name, {"name": name, "phones": [], "emails": []})

        pv = phone_vals[i]
        pl = phone_lbls[i]
        for v, l in zip(pv, pl):
            v, l = v.strip(), l.strip()
            if v:
                entry["phones"].append({"label": l, "value": v})

        ev = email_vals[i]
        el = email_lbls[i]
        for v, l in zip(ev, el):
            v, l = v.strip(), l.strip()
            if v:
                entry["emails"].append({"label": l, "value": v})

    return sorted(by_name.values(), key=lambda c: c["name"].lower())


if __name__ == "__main__":
    # Quick CLI for poking at the output during development.
    try:
        people = fetch_address_book()
    except AddressBookError as e:
        print(f"❌  {e.kind}: {e.detail}")
        raise SystemExit(1)
    print(f"{len(people)} contact(s) loaded.")
    for p in people[:5]:
        print(f"  - {p['name']}: {len(p['phones'])} phones, {len(p['emails'])} emails")
