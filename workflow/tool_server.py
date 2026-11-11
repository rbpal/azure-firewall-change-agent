"""Check that the deployed tool server runs main's mcp/ code before any ticket goes to the agent.

Example: main's mcp/ folder hashes to 9c1e…. The code_version tool on func-fwagentic-dev answers
41b7…, with tools/locate_address_for_env_site.py different. check() raises one line naming that
file, and nothing is sent to the agent.

Why: the agent's tools run from the package last deployed to the function app, not from main. A
server older than main answers with old code, and its drafts look normal. Both sides hash the same
files the same way, because this module loads the rule from mcp/tools/code_version.py.

Safety rule: read-only. It signs in with az login, calls the one diagnostic tool, and never
deploys. A server that cannot be reached or does not answer is a failure, never a pass.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from workflow.agent import MCP_URL, AgentError
from workflow.snapshot import commit_files, differing

MCP_APP = "app-fwagentic-mcp-dev"  # the tool server's app registration; its api:// URI is the token audience
RULE = Path("mcp") / "tools" / "code_version.py"
TOOL = "code_version"
PROTOCOL = "2025-06-18"
TIMEOUT = 60  # seconds per request; a cold function app can take a while to answer
SHOWN = 10  # differing files named in the message; the detail keeps up to 50


def rule(repo: Path):
    """Load covered() and fingerprint() from repo's mcp/tools/code_version.py, the file the server runs."""
    spec = importlib.util.spec_from_file_location("fwagent_code_version_rule", Path(repo) / RULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main_code(repo: Path, commit: str) -> dict:
    """The code hash of the commit's mcp/ folder, read from Git, with each file's path relative to mcp/."""
    files = {path.removeprefix("mcp/"): data for path, data in commit_files(repo, commit, ("mcp",)).items()}
    return rule(repo).fingerprint(files)


def audience() -> str:
    """The tool server's token audience: $FWAGENT_MCP_AUDIENCE, else the api:// URI of MCP_APP from Entra."""
    if os.environ.get("FWAGENT_MCP_AUDIENCE"):
        return os.environ["FWAGENT_MCP_AUDIENCE"]
    done = subprocess.run(["az", "ad", "app", "list", "--display-name", MCP_APP, "--query", "[].identifierUris",
                           "-o", "json"], capture_output=True, text=True)
    if done.returncode != 0:
        raise AgentError(f"could not look up {MCP_APP} in Entra: {done.stderr.strip()[:300]}")
    uris = [u for app in json.loads(done.stdout or "[]") for u in app if u.startswith("api://")]
    if len(uris) != 1:
        raise AgentError(f"expected one api:// URI for {MCP_APP} in Entra, found {len(uris)}")
    return uris[0]


def token() -> str:
    """An Entra access token for the tool server, signed in as the engineer with az login."""
    from azure.identity import AzureCliCredential
    return AzureCliCredential().get_token(f"{audience()}/.default").token


def post(url: str, body: dict, headers: dict) -> tuple[dict | None, dict]:
    """POST one JSON-RPC message; return the JSON-RPC answer (None for a notification) and the response headers."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
        **headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            text, got = response.read().decode(), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        raise AgentError(f"the tool server answered HTTP {error.code} to {body.get('method')}") from error
    except OSError as error:
        raise AgentError(f"could not reach the tool server: {error}") from error
    return parse(text), got


def parse(text: str) -> dict | None:
    """The JSON-RPC answer in a plain JSON or event-stream body; None when the body is empty."""
    lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
    payload = lines[-1] if lines else text.strip()
    return json.loads(payload) if payload else None


def call_tool(url: str, bearer: str, name: str) -> dict:
    """Open an MCP session, call one tool with no arguments, and return its JSON answer."""
    auth = {"Authorization": f"Bearer {bearer}"}
    _, got = post(url, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "fwagent", "version": "1"}}}, auth)
    session = {**auth, **({"Mcp-Session-Id": got["mcp-session-id"]} if got.get("mcp-session-id") else {})}
    post(url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session)
    answer, _ = post(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": name, "arguments": {}}}, session)
    result = (answer or {}).get("result") or {}
    if (answer or {}).get("error") or result.get("isError") or not result.get("content"):
        raise AgentError(f"the deployed tool server has no working {name} tool, so it is older than this check. "
                         "Redeploy mcp/ from GitHub main")
    out = json.loads(result["content"][0]["text"])
    if "error" in out:
        raise AgentError(f"the tool server refused {name}: {out.get('reason') or out['error']}")
    return out


def deployed_code(url: str = MCP_URL) -> dict:
    """The code hash the deployed tool server reports for itself."""
    return call_tool(url, token(), TOOL)


def problems(main: dict, deployed: dict) -> list[str]:
    """Every file whose hash differs between main's mcp/ and the deployed server; [] when the code hashes match."""
    if deployed.get("code_sha256") == main["code_sha256"]:
        return []
    return differing(main["files"], deployed.get("files") or {}) or ["the code hashes differ"]


def check(repo: Path, commit: str, reader=None) -> dict:
    """Refuse unless the deployed tool server runs the commit's mcp/ code; return the matching hash."""
    main = main_code(repo, commit)
    deployed = (reader or deployed_code)()
    differ = problems(main, deployed)
    if differ:
        names = ", ".join(differ[:SHOWN]) + (f" and {len(differ) - SHOWN} more" if len(differ) > SHOWN else "")
        raise AgentError(f"the deployed tool server does not run GitHub main's mcp/ code: {len(differ)} file(s) "
                         f"differ ({names}). Redeploy mcp/ from main, then try again",
                         detail={"main_commit": commit, "main_code_sha256": main["code_sha256"],
                                 "deployed_code_sha256": deployed.get("code_sha256"), "differing": differ[:50]})
    return {"code_sha256": main["code_sha256"], "files": len(main["files"])}
