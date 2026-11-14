"""Deploy one main commit's mcp/ folder to the tool server, then check the server runs exactly that code.

Example: main 4f2a1c9… changes mcp/tools/duplicate_rule_check.py. The deployed server's code_version
answers an older hash, so this packs `git archive 4f2a1c9…:mcp`, deploys it with config-zip and asks
code_version again until the hashes match. The sync job records the hash in the ready marker.

Why: the agent's tools run from the package last deployed to the function app, not from main. A
release is ready only when its network data, its agent version and its tool code all come from the
same main commit, and each one is checked.

Safety rule: it deploys only the mcp/ tree of the commit being released, read from Git, never the
working folder. It never touches a firewall policy. A deploy that fails, or a server that still does
not answer the commit's code hash before the deadline, raises: the sync job then writes no marker,
so drafting and the eval stop instead of using a half-finished release.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from pathlib import Path

from workflow.agent import AgentError

FUNCTION_APP = os.environ.get("FWAGENT_FUNCTION_APP", "func-fwagentic-dev")
RESOURCE_GROUP = os.environ.get("FWAGENT_RESOURCE_GROUP", "rg-fwagentic-dev")
DEPLOY_TIMEOUT = 600  # seconds az waits for the remote build
VERIFY_TIMEOUT = 600  # seconds to wait for the new code to answer; a cold Flex app restarts slowly
VERIFY_INTERVAL = 20


def package(repo: Path, commit: str, out: Path) -> Path:
    """Write the commit's mcp/ tree, exactly as Git holds it, to a zip file; return its path."""
    done = subprocess.run(["git", "-C", str(repo), "archive", "--format=zip", "-o", str(out), f"{commit}:mcp"],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AgentError(f"could not pack mcp/ from {commit[:12]}: {done.stderr.strip()[:300]}")
    return out


def config_zip(repo: Path, commit: str) -> None:
    """Deploy the commit's mcp/ package to the function app with a remote build; raise if az reports a failure."""
    with tempfile.TemporaryDirectory() as folder:
        zip_path = package(repo, commit, Path(folder) / "mcp.zip")
        done = subprocess.run(["az", "functionapp", "deployment", "source", "config-zip", "-g", RESOURCE_GROUP,
                               "-n", FUNCTION_APP, "--build-remote", "true", "--src", str(zip_path),
                               "--timeout", str(DEPLOY_TIMEOUT), "--output", "none", "--only-show-errors"],
                              capture_output=True, text=True)
    if done.returncode != 0:
        raise AgentError(f"deploying mcp/ from {commit[:12]} to {FUNCTION_APP} failed: {done.stderr.strip()[:500]}")


def ensure_tool_code(repo: Path, commit: str, reader=None, deployer=config_zip, sleep=time.sleep,
                     clock=time.monotonic, timeout: float = VERIFY_TIMEOUT, interval: float = VERIFY_INTERVAL) -> dict:
    """Make the tool server run the commit's mcp/ code, deploying only if it does not yet; return the checked record."""
    from workflow import tool_server  # imported here: tool_server imports the agent module too
    read = reader or tool_server.deployed_code
    main = tool_server.main_code(repo, commit)
    try:
        current = tool_server.problems(main, read())
    except AgentError:
        current = ["the deployed server's code could not be read"]  # unknown counts as different: deploy, then check
    deployed = bool(current)
    if deployed:
        deployer(repo, commit)
        start, differ = clock(), current
        while True:
            try:
                differ = tool_server.problems(main, read())
            except AgentError as error:  # the app restarts after a deploy; keep asking until the deadline
                differ = [str(error)]
            if not differ:
                break
            if clock() - start >= timeout:
                raise AgentError(f"after deploying mcp/ from {commit[:12]}, the tool server still does not run that "
                                 f"code ({', '.join(differ[:5])}); the release is not marked ready",
                                 detail={"main_commit": commit, "main_code_sha256": main["code_sha256"],
                                         "differing": differ[:50]})
            sleep(interval)
    return {"commit": commit, "code_sha256": main["code_sha256"], "files": len(main["files"]),
            "function_app": FUNCTION_APP, "deployed": deployed}
