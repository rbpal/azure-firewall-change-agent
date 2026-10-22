"""The drafting agent on Foundry: one call per accepted ticket, tools over remote MCP.

Example: with FWAGENT_PROJECT_ENDPOINT and FWAGENT_SNAPSHOT_COMMIT set,
    agent = FoundryAgent.from_env(REPO)
    reply = agent(ticket, engineer_review=None)
returns {"outcome": "draft", "rules": [...]} after the model has called
locate_address_for_env_site and duplicate_rule_check on func-fwagentic-dev.

Why: the workflow order is fixed in code (ADR 0004); the model only drafts. Its
instructions are agents/drafter.md plus the standards and runbooks, sent with
every version of the agent. Its tools are the deployed MCP server, reached through
the project connection mcp-fwagentic-tools as the project's managed identity, so
the agent reads the same copy of main the tools serve (ADR 0003).

One revision per ticket: FWAGENT_SNAPSHOT_COMMIT names the commit of main the tools
must read. The agent version carries it as the X-Fwagent-Snapshot header, so every
tool call of a ticket reads that snapshot, not whatever current.json says then.
Because a header can be dropped on the way, the reply is accepted only when every
tool answer that read main names that same commit, and only when this repo's
data/network and infra/envs equal that commit, the files the draft is written into.
Any mismatch is an AgentError, and nothing is written.

Safety rule: the agent never writes. Its reply is only JSON, checked here against
agents/reply.schema.json, then by every scope and approval check in
workflow/scope.py before any file changes. The agent receives the ticket and the
engineer's recorded acceptance, nothing else: never an answer key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

AGENT_NAME = "fwagent-drafter"
DEFAULT_MODEL = "gpt-6-luna-agent"
DEFAULT_CONNECTION = "mcp-fwagentic-tools"
MCP_URL = "https://func-fwagentic-dev.azurewebsites.net/runtime/webhooks/mcp"
TOOLS = ["locate_address_for_env_site", "duplicate_rule_check", "dns_lookup_for_fqdn"]  # whoami is diagnostic only
AGENTS = Path(__file__).resolve().parent.parent / "agents"
GUIDANCE = ("data/standards", "data/runbooks")
REPLY_SCHEMA = json.loads((AGENTS / "reply.schema.json").read_text())
FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)
SNAPSHOT_HEADER = "X-Fwagent-Snapshot"
COMMIT = re.compile(r"[0-9a-f]{40}")
READS_MAIN = {"locate_address_for_env_site", "duplicate_rule_check"}  # their answers name the commit they read
DATA = ("data/network", "infra/envs")  # what the sync job copies, and what a draft is written into


class AgentError(Exception):
    """The agent's call failed or its reply is not a valid reply; nothing is written."""


def instructions(repo: Path) -> str:
    """What the agent is told on every call: agents/drafter.md, then each standard and runbook page."""
    parts = [(AGENTS / "drafter.md").read_text().strip()]
    for folder in GUIDANCE:
        for page in sorted((Path(repo) / folder).glob("*.md")):
            parts.append(f"<!-- {folder}/{page.name} -->\n{page.read_text().strip()}")
    return "\n\n---\n\n".join(parts) + "\n"


def definition(text: str, snapshot: str, model: str = DEFAULT_MODEL, connection: str = DEFAULT_CONNECTION) -> dict:
    """The prompt agent: model, instructions, and the three read tools over MCP, pinned to one snapshot, with no approval step."""
    if not COMMIT.fullmatch(snapshot or ""):
        raise AgentError(f"the snapshot must be a full commit SHA, not {snapshot!r}")
    return {"kind": "prompt", "model": model, "instructions": text,
            "tools": [{"type": "mcp", "server_label": "fwtools", "server_url": MCP_URL, "allowed_tools": list(TOOLS),
                       "require_approval": "never", "project_connection_id": connection,
                       "headers": {SNAPSHOT_HEADER: snapshot}}]}


def data_differences(repo: Path, commit: str) -> list[str]:
    """The data files in this repo that differ from commit, committed or not, plus untracked ones; [] when equal."""
    def git(*args):
        """Run git in the repo; any failure, such as an unknown commit, is an AgentError."""
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        if done.returncode != 0:
            raise AgentError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
        return [line for line in done.stdout.splitlines() if line]
    git("cat-file", "-e", f"{commit}^{{commit}}")
    return sorted(set(git("diff", "--name-only", commit, "--", *DATA)) | set(git("ls-files", "--others", "--exclude-standard", "--", *DATA)))


def tool_commits(response) -> list[tuple[str, str | None]]:
    """(tool, commit its answer names) for each call to a tool that reads main; None when the answer names none."""
    out = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", "") != "mcp_call" or getattr(item, "name", "") not in READS_MAIN:
            continue
        try:
            answer = json.loads(getattr(item, "output", None) or "null")
        except ValueError:
            answer = None
        if isinstance(answer, dict) and "error" in answer and "source" not in answer:
            continue  # refused or failed before reading main: no data from any revision
        source = answer.get("source") if isinstance(answer, dict) else None
        out.append((item.name, source.get("commit") if isinstance(source, dict) else None))
    return out


def definition_sha(body: dict) -> str:
    """A short hash of the definition, stored on each agent version so an unchanged one is reused."""
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def ensure_version(project, body: dict) -> str:
    """Return the agent version whose definition matches body, creating one only when none does."""
    sha = definition_sha(body)
    try:
        versions = list(project.agents.list_versions(AGENT_NAME))
    except Exception as error:  # the agent does not exist yet
        if getattr(error, "status_code", None) != 404:
            raise
        versions = []
    for v in versions:
        if (getattr(v, "metadata", None) or {}).get("definition_sha") == sha:
            return str(v.version)
    from azure.ai.projects.models import MCPTool, PromptAgentDefinition
    tool = body["tools"][0]
    made = project.agents.create_version(
        AGENT_NAME,
        definition=PromptAgentDefinition(model=body["model"], instructions=body["instructions"],
                                         tools=[MCPTool(**{k: v for k, v in tool.items() if k != "type"})]),
        metadata={"definition_sha": sha}, description="Drafts firewall rule changes for one accepted ticket.")
    return str(made.version)


def message(ticket: dict, engineer_review: dict | None) -> str:
    """The one user message: the ticket and the engineer's recorded acceptance, as JSON."""
    return json.dumps({"ticket": ticket, "engineer_review": engineer_review}, sort_keys=True, default=str)


def parse_reply(text: str) -> dict:
    """Read the agent's text as one reply object that fits agents/reply.schema.json, or raise AgentError."""
    body = (text or "").strip()
    fenced = FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        reply = json.loads(body)
    except ValueError as error:
        raise AgentError(f"the agent's reply is not JSON: {body[:200]!r}") from error
    problems = sorted(jsonschema.Draft202012Validator(REPLY_SCHEMA).iter_errors(reply), key=lambda e: list(e.path))
    if problems:
        raise AgentError("the agent's reply does not fit agents/reply.schema.json:\n  "
                         + "\n  ".join(f"{'/'.join(map(str, p.path)) or '(top)'}: {p.message}" for p in problems[:10]))
    return reply


@dataclass
class Call:
    """What one agent call used and did, kept for the score sheet and the cost check."""
    number: str
    input_tokens: int = 0
    output_tokens: int = 0
    tools: list[str] = field(default_factory=list)
    commits: list[str | None] = field(default_factory=list)
    error: str | None = None


class FoundryAgent:
    """Calls the published drafter version on Foundry Agent Service, one ticket per call."""

    controlled_dns = False  # its DNS tool runs in Azure, so an eval's dns: condition cannot reach it

    def __init__(self, project, openai_client, version: str, snapshot: str):
        """Keep the project client, its OpenAI client, the agent version and the snapshot every call must use."""
        self.project, self.openai, self.version, self.snapshot = project, openai_client, version, snapshot
        self.calls: list[Call] = []

    @classmethod
    def from_env(cls, repo: Path, require_same_data: bool = True) -> "FoundryAgent":
        """Sign in with az login, check the snapshot, publish the drafter if its definition changed, and return the agent."""
        endpoint = os.environ.get("FWAGENT_PROJECT_ENDPOINT")
        if not endpoint:
            raise AgentError("FWAGENT_PROJECT_ENDPOINT is not set: the Foundry project endpoint, "
                             "https://<account>.services.ai.azure.com/api/projects/<project>")
        snapshot = os.environ.get("FWAGENT_SNAPSHOT_COMMIT", "")
        if not COMMIT.fullmatch(snapshot):
            raise AgentError("FWAGENT_SNAPSHOT_COMMIT must be the full SHA of the snapshot the tools read")
        differ = data_differences(repo, snapshot)
        if require_same_data and differ:
            raise AgentError(f"this repo's data differs from snapshot {snapshot[:12]}, so the draft and the tools "
                             "would use two revisions: " + ", ".join(differ))
        from azure.ai.projects import AIProjectClient
        from azure.identity import AzureCliCredential
        project = AIProjectClient(endpoint=endpoint, credential=AzureCliCredential())
        body = definition(instructions(repo), snapshot, os.environ.get("FWAGENT_MODEL", DEFAULT_MODEL),
                          os.environ.get("FWAGENT_MCP_CONNECTION", DEFAULT_CONNECTION))
        return cls(project, project.get_openai_client(), ensure_version(project, body), snapshot)

    def __call__(self, ticket: dict, engineer_review: dict | None = None, dns_lookup=None) -> dict:
        """Draft one ticket; refuse a controlled DNS condition, which cannot reach the deployed tools."""
        call = Call(str(ticket.get("number")))
        self.calls.append(call)
        if dns_lookup is not None:
            call.error = "controlled DNS cannot reach the deployed tools"
            raise AgentError("this request fixes a DNS answer, but the agent's DNS tool runs in Azure and asks Azure DNS")
        try:
            response = self.openai.responses.create(
                input=message(ticket, engineer_review),
                extra_body={"agent_reference": {"name": AGENT_NAME, "version": self.version, "type": "agent_reference"}})
        except Exception as error:
            call.error = f"{type(error).__name__}: {error}"
            raise AgentError(f"the agent call failed: {call.error}") from error
        usage = getattr(response, "usage", None)
        call.input_tokens = getattr(usage, "input_tokens", 0) or 0
        call.output_tokens = getattr(usage, "output_tokens", 0) or 0
        call.tools = [getattr(item, "name", "?") for item in getattr(response, "output", []) or []
                      if getattr(item, "type", "") == "mcp_call"]
        read = tool_commits(response)
        call.commits = [c for _, c in read]
        mixed = [f"{name} read {commit or 'no named commit'}" for name, commit in read if commit != self.snapshot]
        if mixed:
            call.error = "tool answers from another revision"
            raise AgentError(f"tool answers are not all from snapshot {self.snapshot[:12]}: " + "; ".join(mixed))
        try:
            return parse_reply(getattr(response, "output_text", ""))
        except AgentError as error:
            call.error = str(error).splitlines()[0]
            raise
