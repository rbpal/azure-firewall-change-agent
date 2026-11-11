"""code_version: report a hash of the tool server's own code files.

Example: {"code_sha256": "9c1e…", "files": {"auth.py": "5d2a…", "tools/whoami.py": "77f0…", …}}

Why: the agent's tools run from the package last deployed to the function app, not from main.
Before a ticket goes to the agent, the workflow hashes main's mcp/ folder the same way and
compares (workflow/tool_server.py). A server older than main stops the run. The agent is never
given this tool: workflow/agent.py lists the tools it may call, and this one is not among them.

Safety rule: it returns SHA-256 hashes of code files only, never their contents, settings or
environment. The workflow loads covered() and fingerprint() from this file, so both sides hash
the same files the same way.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the app root: mcp/ in the repo, wwwroot in Azure
ROOT_FILES = {"host.json", "requirements.txt"}  # with every .py file, these decide what the server does


def covered(path: str) -> bool:
    """True when a path relative to the app root is a code file the hash covers."""
    *folders, name = path.split("/")
    if any(f.startswith(".") or f == "__pycache__" for f in folders):
        return False
    return name.endswith(".py") or (not folders and name in ROOT_FILES)


def fingerprint(files: dict[str, bytes]) -> dict:
    """The SHA-256 of each covered file, by path, and one SHA-256 over that whole list."""
    hashes = {path: hashlib.sha256(data).hexdigest() for path, data in sorted(files.items()) if covered(path)}
    return {"code_sha256": hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest(), "files": hashes}


def app_files(root: Path = ROOT) -> dict[str, bytes]:
    """Every covered file under the app root; hidden folders, caches and virtual environments are skipped."""
    out = {}
    for folder, subfolders, names in os.walk(root):
        here = Path(folder)
        subfolders[:] = sorted(d for d in subfolders if not d.startswith(".") and d != "__pycache__"
                               and not (here / d / "pyvenv.cfg").exists())
        for name in names:
            rel = (here / name).relative_to(root).as_posix()
            if covered(rel):
                out[rel] = (here / name).read_bytes()
    return out


def code_version(caller, arguments: dict | None = None, root: Path = ROOT) -> dict:
    """Hash this server's code files; it takes no arguments."""
    return fingerprint(app_files(root))
