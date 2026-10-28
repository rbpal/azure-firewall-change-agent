"""The drafting agent on Foundry: one call per accepted ticket, tools over remote MCP.

Example: with FWAGENT_PROJECT_ENDPOINT set,
    agent = FoundryAgent.from_env(REPO)
    reply = agent(ticket, engineer_review=None)
returns {"outcome": "draft", "rules": [...], "explanation": "..."} after the model has called
locate_address_for_env_site and duplicate_rule_check on func-fwagentic-dev.

Why: the workflow order is fixed in code (ADR 0004); the model only drafts. Its
instructions are agents/drafter.md plus the standards and runbooks, sent with
every version of the agent. Its tools are the deployed MCP server, reached through
the project connection mcp-fwagentic-tools as the project's managed identity, so
the agent reads the same copy of main the tools serve (ADR 0003).

One revision per run: the run reads current.json once, checks that the snapshot it
names holds exactly that commit's data files, and pins that SHA. It never falls back
to the previous snapshot; a bad or mismatched snapshot stops the run. If
FWAGENT_SNAPSHOT_COMMIT is set, current.json must name that commit. The agent version
carries the SHA as the X-Fwagent-Snapshot header, so every tool call reads that
snapshot even if current.json moves during the run.
Because a header can be dropped on the way, the reply is accepted only when every
tool answer that read main names that same commit, and only when this repo's
data/network and infra/envs equal that commit, the files the draft is written into.
Any mismatch is an AgentError, and nothing is written.

Safety rule: the agent never writes. Its reply is only JSON. The agent version asks the
service for strict structured output: one {"reply": ...} object that fits
agents/reply.strict.schema.json. Code checks that wrapper, then checks the inner reply,
unchanged, against agents/reply.schema.json, then runs every scope and approval check in
workflow/scope.py before any file changes. Strict output narrows what the model can
write; it never replaces these checks. The agent receives the ticket and the
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
TOOLS = ["locate_address_for_env_site", "resolve_env_site", "duplicate_rule_check", "dnat_port_check", "dns_lookup_for_fqdn"]  # whoami is diagnostic only
AGENTS = Path(__file__).resolve().parent.parent / "agents"
GUIDANCE = ("data/standards", "data/runbooks")
REPLY_SCHEMA = json.loads((AGENTS / "reply.schema.json").read_text())
STRICT_SCHEMA = json.loads((AGENTS / "reply.strict.schema.json").read_text())
REPLY_FORMAT = {"type": "json_schema", "name": "fwagent_reply", "strict": True, "schema": STRICT_SCHEMA,
                "description": ("The reply described in the instructions, wrapped as {\"reply\": ...}. A stop keeps "
                                "rules as an empty list; action appears only on a draft that removes rules.")}
FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)
SNAPSHOT_HEADER = "X-Fwagent-Snapshot"
COMMIT = re.compile(r"[0-9a-f]{40}")
RAW_LIMIT = 20_000  # characters of an invalid reply kept for diagnosis; a valid reply is far shorter
READS_MAIN = {"locate_address_for_env_site", "resolve_env_site", "duplicate_rule_check", "dnat_port_check"}  # their answers name the commit they read
DATA = ("data/network", "infra/envs")  # what the sync job copies, and what a draft is written into
SNAPSHOT_ACCOUNT = "stfwagentfuncdev"
SNAPSHOT_CONTAINER = "network-snapshot"


class AgentError(Exception):
    """The agent's call failed or its reply is not a valid reply; nothing is written."""

    def __init__(self, message: str, raw: str | None = None):
        """Keep the message and, for an invalid reply, the agent's raw text (cut to RAW_LIMIT) for diagnosis."""
        super().__init__(message)
        self.raw = raw


class InfraError(AgentError):
    """The call itself failed (network, sign-in, service or quota), so the model gave no answer to judge."""


class RateLimited(InfraError):
    """The deployment throttled the call; retry_after is the server's wait in seconds, or None if it sent none."""

    def __init__(self, message: str, retry_after: float | None = None):
        """Keep the message and the server's wait."""
        super().__init__(message)
        self.retry_after = retry_after


def failed_call(error: Exception) -> InfraError:
    """Turn a failed call into RateLimited when the service throttled it, else into InfraError."""
    message = f"the agent call failed: {type(error).__name__}: {error}"
    body = getattr(error, "body", None)
    codes = [getattr(error, "code", None)]
    if isinstance(body, dict):
        codes += [body.get("code"), (body.get("error") or {}).get("code") if isinstance(body.get("error"), dict) else None]
    if getattr(error, "status_code", None) != 429 and "rate_limit_exceeded" not in codes:
        return InfraError(message)
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    wait = None
    try:
        if headers.get("retry-after-ms") is not None:
            wait = float(headers["retry-after-ms"]) / 1000
        elif headers.get("retry-after") is not None:
            wait = float(headers["retry-after"])
    except ValueError:  # an HTTP-date or junk: fall back to the caller's default wait
        wait = None
    return RateLimited(message, retry_after=wait)


SERVICE_CODES = {"server_error", "vector_store_timeout"}  # failed responses that are the service's fault, not the agent's


def unfinished(response) -> AgentError | None:
    """The error for a response the service returned without finishing it, or None when it completed.

    The service can answer without raising and mark the response failed, incomplete or still running; its
    text is then never read as a reply. A rate limit is RateLimited, so it is retried; any other service
    failure or an unfinished run is InfraError; a failure on the request's content, or a reply cut short
    (incomplete), is the agent's own failure. A response with no status field counts as completed.
    """
    status = getattr(response, "status", None)
    if status in (None, "completed"):
        return None
    code = getattr(getattr(response, "error", None), "code", None)
    if status == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
        return AgentError(f"the agent's response is incomplete: {reason or 'no reason given'}")
    message = f"the agent's response has status {status}" + (f": {code}" if code else "")
    if code == "rate_limit_exceeded":
        return RateLimited(message)
    if status == "failed" and code and code not in SERVICE_CODES:
        return AgentError(message)
    return InfraError(message)


def instructions(repo: Path) -> str:
    """What the agent is told on every call: agents/drafter.md, then each standard and runbook page."""
    parts = [(AGENTS / "drafter.md").read_text().strip()]
    for folder in GUIDANCE:
        for page in sorted((Path(repo) / folder).glob("*.md")):
            parts.append(f"<!-- {folder}/{page.name} -->\n{page.read_text().strip()}")
    return "\n\n---\n\n".join(parts) + "\n"


def definition(text: str, snapshot: str, model: str = DEFAULT_MODEL, connection: str = DEFAULT_CONNECTION) -> dict:
    """The prompt agent: model, instructions, strict reply format, and the read tools over MCP pinned to one snapshot."""
    if not COMMIT.fullmatch(snapshot or ""):
        raise AgentError(f"the snapshot must be a full commit SHA, not {snapshot!r}")
    return {"kind": "prompt", "model": model, "instructions": text,
            "tools": [{"type": "mcp", "server_label": "fwtools", "server_url": MCP_URL, "allowed_tools": list(TOOLS),
                       "require_approval": "never", "project_connection_id": connection,
                       "headers": {SNAPSHOT_HEADER: snapshot}}],
            "text": {"format": REPLY_FORMAT}}


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


def _git_files(repo: Path, commit: str) -> set[str]:
    """The data files commit holds, from this checkout's git history."""
    done = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "--name-only", commit, "--", *DATA],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise AgentError(f"this checkout does not have commit {commit[:12]}, so its snapshot cannot be checked: "
                         f"{done.stderr.strip()}")
    return {line for line in done.stdout.splitlines() if line}


def current_snapshot(repo: Path, container) -> str:
    """The commit current.json names, after checking its snapshot holds exactly that commit's data files."""
    try:
        pointer = json.loads(container.download_blob("current.json").readall())
    except Exception as error:
        raise AgentError(f"current.json could not be read: {type(error).__name__}: {error}") from error
    commit = pointer.get("commit") if isinstance(pointer, dict) else None
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise AgentError(f"current.json does not name a full commit SHA: {pointer!r}")
    prefix = f"snapshots/{commit}/"
    uploaded = {b.name[len(prefix):] for b in container.list_blobs(name_starts_with=prefix)}
    wanted = _git_files(repo, commit)
    if uploaded != wanted:
        missing, extra = sorted(wanted - uploaded), sorted(uploaded - wanted)
        raise AgentError(f"snapshot {commit[:12]} does not match its commit: {len(missing)} files missing "
                         f"{missing[:3]}, {len(extra)} extra {extra[:3]}. Stopped; the previous snapshot is never used instead")
    return commit


def snapshot_container():
    """The snapshot container, read with your az login (Storage Blob Data Reader on the container)."""
    from azure.identity import AzureCliCredential
    from azure.storage.blob import ContainerClient
    account = os.environ.get("FWAGENT_SNAPSHOT_ACCOUNT", SNAPSHOT_ACCOUNT)
    return ContainerClient(f"https://{account}.blob.core.windows.net", SNAPSHOT_CONTAINER, credential=AzureCliCredential())


def pin_snapshot(repo: Path, container, allowed_differences=()) -> str:
    """Pin the current snapshot for a run: verified, as required, and the same data as this checkout, or stop."""
    commit = current_snapshot(repo, container)
    required = os.environ.get("FWAGENT_SNAPSHOT_COMMIT")
    if required and required != commit:
        raise AgentError(f"current.json names {commit[:12]}, but this run requires {required[:12]}. Stopped; "
                         "the previous snapshot is never used instead")
    differ = sorted(set(data_differences(repo, commit)) - set(allowed_differences))
    if differ:
        raise AgentError(f"this checkout's data differs from snapshot {commit[:12]}, so the draft and the tools would "
                         "use two revisions: " + ", ".join(differ))
    return commit


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
    from azure.ai.projects.models import (MCPTool, PromptAgentDefinition, PromptAgentDefinitionTextOptions,
                                          TextResponseFormatJsonSchema)
    tool, fmt = body["tools"][0], body["text"]["format"]
    made = project.agents.create_version(
        AGENT_NAME,
        definition=PromptAgentDefinition(model=body["model"], instructions=body["instructions"],
                                         tools=[MCPTool(**{k: v for k, v in tool.items() if k != "type"})],
                                         text=PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
                                             **{k: v for k, v in fmt.items() if k != "type"}))),
        metadata={"definition_sha": sha}, description="Drafts firewall rule changes for one accepted ticket.")
    return str(made.version)


def message(ticket: dict, engineer_review: dict | None) -> str:
    """The one user message: the ticket and the engineer's recorded acceptance, as JSON."""
    return json.dumps({"ticket": ticket, "engineer_review": engineer_review}, sort_keys=True, default=str)


def _load(text: str):
    """The JSON value in the agent's text, a code fence allowed, or raise AgentError keeping the raw text."""
    body = (text or "").strip()
    fenced = FENCE.match(body)
    if fenced:
        body = fenced.group(1)
    try:
        return json.loads(body)
    except ValueError as error:
        raise AgentError(f"the agent's reply is not JSON: {body[:200]!r}", raw=(text or "")[:RAW_LIMIT]) from error


def _refuse(value, schema: dict, name: str, text: str) -> None:
    """Raise AgentError listing up to ten ways value breaks schema; return when it fits."""
    if not jsonschema.Draft202012Validator(schema).is_valid(value):
        problems = [f"{'/'.join(map(str, p.path)) or '(top)'}: {p.message}" for p in _problems(value, schema)]
        raise AgentError(f"the agent's reply does not fit {name}:\n  " + "\n  ".join(problems[:10]),
                         raw=(text or "")[:RAW_LIMIT])


def _problems(value, schema: dict) -> list:
    """The schema errors in value; for the strict wrapper, those of the shape the reply's own outcome claims."""
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(value), key=lambda e: list(e.path))
    reply = value.get("reply") if schema is STRICT_SCHEMA and isinstance(value, dict) else None
    outcome = reply.get("outcome") if isinstance(reply, dict) else None
    shape = ("draft_remove" if "action" in reply else "draft_add") if outcome == "draft" else outcome
    if shape not in STRICT_SCHEMA["$defs"]:
        return errors
    claimed = {**STRICT_SCHEMA["$defs"][shape], "$defs": STRICT_SCHEMA["$defs"]}
    inner = sorted(jsonschema.Draft202012Validator(claimed).iter_errors(reply), key=lambda e: list(e.path))
    for e in inner:
        e.path.appendleft("reply")
    return [e for e in errors if list(e.path) != ["reply"]] + inner


def parse_reply(text: str) -> dict:
    """Read text as one reply object that fits agents/reply.schema.json, or raise AgentError."""
    reply = _load(text)
    _refuse(reply, REPLY_SCHEMA, "agents/reply.schema.json", text)
    return reply


def parse_agent_text(text: str) -> dict:
    """Read the agent's text: the strict {"reply": ...} wrapper, then the inner reply, unchanged, by parse_reply's check."""
    wrapped = _load(text)
    _refuse(wrapped, STRICT_SCHEMA, "agents/reply.strict.schema.json", text)
    reply = wrapped["reply"]
    _refuse(reply, REPLY_SCHEMA, "agents/reply.schema.json", text)
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
    response_id: str | None = None  # finds the call's trace in Application Insights (gen_ai.response.id)
    raw_reply: str | None = None  # the agent's text when it was not a valid reply, cut to RAW_LIMIT


def connect(endpoint: str):
    """The Foundry project client, signed in with az login."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import AzureCliCredential
    return AIProjectClient(endpoint=endpoint, credential=AzureCliCredential())


class FoundryAgent:
    """Calls the published drafter version on Foundry Agent Service, one ticket per call."""

    controlled_dns = False  # its DNS tool runs in Azure, so an eval's dns: condition cannot reach it

    def __init__(self, project, openai_client, version: str, snapshot: str, container=None):
        """Keep the clients, the agent version, the pinned snapshot and the container that names the current one."""
        self.project, self.openai, self.version, self.snapshot = project, openai_client, version, snapshot
        self.container = container
        self.calls: list[Call] = []

    def pointer_now(self) -> str | None:
        """The commit current.json names now, to report if it moved during the run; None if it cannot be read."""
        try:
            return json.loads(self.container.download_blob("current.json").readall()).get("commit")
        except Exception:
            return None

    @classmethod
    def from_env(cls, repo: Path, allowed_differences=(), container=None) -> "FoundryAgent":
        """Pin the current snapshot, sign in with az login, publish the drafter if its definition changed, and return it."""
        endpoint = os.environ.get("FWAGENT_PROJECT_ENDPOINT")
        if not endpoint:
            raise AgentError("FWAGENT_PROJECT_ENDPOINT is not set: the Foundry project endpoint, "
                             "https://<account>.services.ai.azure.com/api/projects/<project>")
        container = container if container is not None else snapshot_container()
        snapshot = pin_snapshot(repo, container, allowed_differences)  # before any Foundry call
        project = connect(endpoint)
        body = definition(instructions(repo), snapshot, os.environ.get("FWAGENT_MODEL", DEFAULT_MODEL),
                          os.environ.get("FWAGENT_MCP_CONNECTION", DEFAULT_CONNECTION))
        # No hidden retries in the SDK: the runner retries, waits and records every attempt.
        return cls(project, project.get_openai_client(max_retries=0), ensure_version(project, body), snapshot, container)

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
            raise failed_call(error) from error
        call.response_id = getattr(response, "id", None)
        usage = getattr(response, "usage", None)
        call.input_tokens = getattr(usage, "input_tokens", 0) or 0
        call.output_tokens = getattr(usage, "output_tokens", 0) or 0
        refused = unfinished(response)
        if refused is not None:
            call.error = str(refused)
            raise refused
        call.tools = [getattr(item, "name", "?") for item in getattr(response, "output", []) or []
                      if getattr(item, "type", "") == "mcp_call"]
        read = tool_commits(response)
        call.commits = [c for _, c in read]
        mixed = [f"{name} read {commit or 'no named commit'}" for name, commit in read if commit != self.snapshot]
        if mixed:
            call.error = "tool answers from another revision"
            raise AgentError(f"tool answers are not all from snapshot {self.snapshot[:12]}: " + "; ".join(mixed))
        try:
            return parse_agent_text(getattr(response, "output_text", ""))
        except AgentError as error:
            call.error, call.raw_reply = str(error).splitlines()[0], error.raw
            raise
