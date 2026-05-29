"""
py2app configuration for iMessage Exporter.

Build the .app bundle:
    ./build.sh
or manually:
    pip install py2app
    python setup.py py2app

Output: dist/iMessage Exporter.app  (drag to /Applications or share as-is).
"""

from setuptools import setup

APP = ["app.py"]

# Resources bundled into Contents/Resources/ of the .app.
# - web/static is the frontend the FastAPI app serves.
# - The "" subdir target keeps the layout flat next to web/.
DATA_FILES = [
    ("web/static", [
        "web/static/index.html",
        "web/static/styles.css",
        "web/static/app.js",
    ]),
]

PLIST = {
    "CFBundleName": "iMessage Exporter",
    "CFBundleDisplayName": "iMessage Exporter",
    "CFBundleIdentifier": "com.griffinminster.imessage-exporter",
    "CFBundleVersion": "1.0.0",
    "CFBundleShortVersionString": "1.0.0",
    "CFBundleExecutable": "iMessage Exporter",
    "LSMinimumSystemVersion": "11.0",
    "NSHighResolutionCapable": True,
    "NSHumanReadableCopyright": "Local-only iMessage backup tool.",
    # First-launch permission prompts. macOS reads these strings verbatim.
    "NSContactsUsageDescription":
        "iMessage Exporter reads your Contacts so you can pick names to "
        "export instead of typing phone numbers by hand.",
    "NSAppleEventsUsageDescription":
        "iMessage Exporter uses Apple Events to read your Contacts.",
    # Make sure the .app shows up as a normal foreground GUI app in the
    # Dock (default behavior, set explicitly for clarity).
    "LSUIElement": False,
}

OPTIONS = {
    "argv_emulation": False,
    "plist": PLIST,
    # Universal: runs natively on both Apple Silicon and Intel Macs.
    "arch": "universal2",
    # FastAPI + uvicorn pull in a number of indirect deps. modulegraph
    # usually finds them, but the dynamic ones get listed explicitly so
    # py2app doesn't quietly drop them.
    "packages": [
        "fastapi",
        "starlette",
        "pydantic",
        "pydantic_core",
        "uvicorn",
        "anyio",
        "h11",
    ],
    "includes": [
        "sniffio",
        "websockets",
        "httptools",
        "uvloop",
        "click",
        "watchfiles",
        "email",
        "email.mime",
    ],
    # Excludes shave megabytes — none of these are used by the app.
    "excludes": [
        "tkinter",
        "matplotlib",
        "numpy",
        "scipy",
        "pandas",
        "PIL",
        "test",
        "tests",
    ],
}

setup(
    name="iMessage Exporter",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
