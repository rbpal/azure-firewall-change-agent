"""Write an agent reply into the spoke files of the sites the ticket selects, and no others.

Example: a ticket with `change_sites: {prod: [dr]}` and a draft that removes
`https-sett-to-lamnaFs` changes only infra/envs/prod-centralus/.../sett.tfvars.
The prod-eastus2 file keeps its copy of the rule and its numbers.

Why: the ticket answers two questions per environment. `dr_site_built` says whether
DR exists; `change_sites` says which sites this ticket changes, primary, dr or both
(decided 2026-10-18). The workflow follows `change_sites`, so a primary-only change
never edits DR to keep rule numbers aligned. Each file takes its own next index,
and a rule is matched by name and fields, never by its index.

Safety rule: every rule in the reply must sit at a selected site, every selected
site must get a rule, and an add or removal must match the ticket's catalog item.
Every source and destination must be one the ticket approves for that env-site,
in the ticket's type: a CIDR within an approved CIDR, or an IP group or hostname
the ticket names. A group is never accepted for a CIDR or a CIDR for a group,
even when they hold the same addresses (STD-COLL-03).
Every rule must use the ticket's protocol, and its ports must sit inside the
ticket's ports. A removal must name exactly the ticket's ports, because deleting
a rule for other traffic was never approved (RB-03-2). A DNAT rule translates to
the same port it publishes (RB-02-2). The one documented substitute is HTTPS to
addresses written as a TCP network rule (RB-01-4). Ports are read the way the
ticket schema writes them, so a malformed port is refused, never corrected.
A DNAT rule is never added with a source open to everyone, however it is written
(0.0.0.0/0, 0.0.0.0/00, *, two halves, an IP group holding them), even when the
ticket asks for it: STD-COLL-04 is the one standard that blocks. A removal of such
a rule is still written, because deleting it closes the hole.
Otherwise nothing is written. All files are worked out in memory first and written
only when every one succeeds, so a refusal leaves every file byte for byte as it was.
Disk failures: before anything is replaced, each original's exact bytes are saved
to a backup file beside it, and each new text to a temp file. Only then is each temp
file renamed over its target. If a rename fails, each file already swapped gets its
backup moved back. If that also fails, PartialWriteError names every file that still
holds the new text and keeps its backup; moving the backup over the file restores
the bytes from before the write, uncommitted edits included.
Limit: replacing several files is not crash-atomic. Each rename is atomic, but a
crash between two renames leaves some files new and some old; backups left beside
them are the way back. Recovery after power loss is not demonstrated: the tests
only make calls fail, they never cut power, and the folder is not fsynced after a
rename, so a rename or a backup may not have reached the disk.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from workflow.rule_index import next_index
from workflow.tfvars_writer import DraftError, insert_rule, remove_rule, rule_type, spoke_path
from workflow.tickets import SCHEMA_PATH

from data_readers.read_addressplan_routing import ROUTING, LocalSource  # noqa: E402  (tfvars_writer puts mcp/ on the path)
from data_readers.read_env_site_ipgroup import read_ip_groups  # noqa: E402
from errors import BadArguments  # noqa: E402
from tools.duplicate_rule_check import _ports, _ports_within  # noqa: E402  (the agent tool's port maths, so the two agree)
from policy.tier1 import open_to_everyone  # noqa: E402  (Tier 1's own STD-COLL-04 test, so the two agree)

REMOVAL_ITEM = "Firewall Rule Removal"


class ScopeError(DraftError):
    """The reply and the ticket's selected sites disagree; nothing is written."""


class ApprovalError(ScopeError):
    """A reply rule uses an address, address type, protocol or port the ticket does not approve, or opens DNAT to everyone; nothing is written."""


KINDS = {"cidr": "a CIDR", "ip_group": "an IP group", "fqdn": "a hostname"}
PORT = re.compile(json.loads(SCHEMA_PATH.read_text())["$defs"]["port"]["pattern"])  # a ticket port: 22, 1000-2000 or *


def _kind(value: str) -> str:
    """The type of one address in a reply rule: cidr, ip_group or fqdn."""
    try:
        ipaddress.ip_network(value, strict=False)
        return "cidr"
    except ValueError:
        return "ip_group" if value.lower().startswith("ipg-") else "fqdn"


def _approved(entries: list[dict], env: str, site: str) -> list[tuple[str, str]]:
    """The ticket's typed values for one env-site: internal entries at that site, plus every external entry."""
    out = []
    for a in entries:
        if "environment" in a and (a["environment"], a["site"]) != (env, site):
            continue
        if "url" in a:
            out.append(("fqdn", urlsplit(a["url"]).hostname))
        else:
            kind = next(k for k in ("cidr", "ip_group", "fqdn") if k in a)
            out.append((kind, a[kind]))
    return out


def _not_approved(value: str, approved: list[tuple[str, str]]) -> str:
    """Say why one reply address is not approved by the ticket, or return ''."""
    kind = _kind(value)
    for k, v in approved:
        if k == kind == "cidr":
            given, ok = ipaddress.ip_network(value, strict=False), ipaddress.ip_network(v)
            if given.version == ok.version and given.subnet_of(ok):  # ::/0 is refused, never a crash
                return ""
        if k == kind and k != "cidr" and v.lower() == value.lower():
            return ""
    given = ", ".join(f"{v} ({k.replace('_', ' ')})" for k, v in approved) or "nothing"
    same = [v for k, v in approved if k == kind]
    why = "is not on the ticket" if same else f"is {KINDS[kind]}, a type the ticket does not approve here"
    return f"{value} {why}; the ticket approves {given} (STD-COLL-03)"


def _port_spans(values) -> list[tuple[int, int]] | None:
    """Read reply ports written as a ticket writes them ("22", "1000-2000", "*") as ranges, or None if any is not."""
    if not isinstance(values, list) or not values:
        return None
    if not all(isinstance(v, (str, int)) and not isinstance(v, bool) and PORT.fullmatch(str(v)) for v in values):
        return None  # " 22", "022" and "22.0" are refused, never read as 22
    try:
        return _ports([str(v) for v in values])
    except BadArguments:  # above 65535 or high to low
        return None


def _same_ports(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    """True when two port lists allow exactly the same ports, such as ["22", "23"] and ["22-23"]."""
    return _ports_within(a, b) and _ports_within(b, a)


def flow_errors(ticket: dict, rule: dict, removal: bool) -> list[str]:
    """Every way one reply rule's protocol or ports differ from the ticket's."""
    errors = []
    want, protocol = ticket["protocol"], str(rule.get("protocol") or "")
    https_as_network = (want.upper() == "HTTPS" and protocol.upper() == "TCP" and "translated_address" not in rule
                        and all(_kind(str(d)) != "fqdn" for d in rule.get("destinations") or []))
    if protocol.upper() != want.upper() and not https_as_network:  # RB-01-4: HTTPS to an address is a TCP network rule
        errors.append(f"protocol {protocol or '(none)'} is not the ticket's {want}")
    approved, ports = _ports(ticket["ports"]), _port_spans(rule.get("ports"))
    if ports is None:
        errors.append(f"ports {rule.get('ports')!r} are not written as a ticket writes ports (22, 1000-2000 or *)")
    elif removal:
        if not _same_ports(ports, approved):
            errors.append(f"ports {rule['ports']} are not exactly the ticket's {ticket['ports']}; "
                          "a removal deletes only the ticket's flow (RB-03-2)")
    else:
        errors += [f"port {v} is not within the ticket's {ticket['ports']}"
                   for v, span in zip(rule["ports"], ports) if not _ports_within([span], approved)]
    if "translated_address" in rule:
        translated = _port_spans([rule.get("translated_port")])
        if translated is None or translated[0][0] != translated[0][1] or not _same_ports(ports or [], translated):
            errors.append(f"translated port {rule.get('translated_port')!r} is not the one port the rule publishes, "
                          f"{rule.get('ports')}; DNAT translates to the same port (RB-02-2)")
    return errors


def open_dnat_error(repo: Path, rule: dict) -> str:
    """Say why an added DNAT rule's sources let in everyone (STD-COLL-04), or return ''."""
    sources = [str(s) for s in rule.get("sources") or []]
    groups = [s for s in sources if s.lower().startswith("ipg-")]
    members = read_ip_groups(LocalSource(Path(repo)), rule["env_site"]) if groups else {}
    why = open_to_everyone([s for s in sources if s not in groups], groups, members)
    return (f"source is open to everyone: {why}. A DNAT rule never takes its source from everyone, "
            "even when the ticket asks (STD-COLL-04, RB-02-5 open_dnat_source)") if why else ""


def approval_errors(repo: Path, ticket: dict, reply: dict) -> list[str]:
    """Every reply address, protocol or port the ticket does not approve at that rule's env-site, and every open DNAT add."""
    sites = yaml.safe_load((Path(repo) / ROUTING).read_text())["env_sites"]
    removal = reply.get("action") == "remove"
    errors = []
    for rule in reply.get("rules") or []:
        where = sites[rule["env_site"]]
        env, site = where["environment"], where["site"]
        checks = [("source", rule.get("sources") or [], ticket["sources"])]
        if "translated_address" in rule:  # DNAT: the rule's destination is the firewall; the ticket's is the host
            checks.append(("translated address", [rule["translated_address"]], ticket["destination"]))
        else:
            checks.append(("destination", rule.get("destinations") or [], ticket["destination"]))
        for side, values, entries in checks:
            approved = _approved(entries, env, site)
            errors += [f"{rule['env_site']} {rule['name']}: {side} {why}"
                       for v in values if (why := _not_approved(str(v), approved))]
        errors += [f"{rule['env_site']} {rule['name']}: {why}" for why in flow_errors(ticket, rule, removal)]
        if "translated_address" in rule and not removal and (why := open_dnat_error(repo, rule)):
            errors.append(f"{rule['env_site']} {rule['name']}: {why}")
    return errors


def selected_env_sites(repo: Path, ticket: dict) -> set[str]:
    """The env-sites the ticket changes, such as {"prod-centralus"}, from routing.yaml."""
    sites = yaml.safe_load((Path(repo) / ROUTING).read_text())["env_sites"]
    by_name = {(s["environment"], s["site"]): name for name, s in sites.items()}
    return {by_name[(env, site)] for env, chosen in ticket["change_sites"].items() for site in chosen}


def plan_writes(repo: Path, ticket: dict, reply: dict, base: dict[Path, str] | None = None) -> list[tuple[Path, str, str]]:
    """Work out every changed file in memory, starting from `base` texts where given; return (path, new text, key) per rule."""
    if reply.get("outcome") != "draft":
        return []
    removal = reply.get("action") == "remove"
    if removal != (ticket["item"] == REMOVAL_ITEM):
        raise ScopeError(f"reply {'removes' if removal else 'adds'} rules, but the ticket is a {ticket['item']!r}")
    scope = selected_env_sites(repo, ticket)
    named = {r["env_site"] for r in reply["rules"]}
    if named - scope:
        raise ScopeError(f"reply changes {sorted(named - scope)}, which the ticket does not select")
    if scope - named:
        raise ScopeError(f"ticket selects {sorted(scope - named)}, but the reply has no rule there")
    errors = approval_errors(repo, ticket, reply)
    if errors:
        raise ApprovalError("reply uses addresses, a protocol or ports the ticket does not approve, "
                            "or opens DNAT to everyone:\n  " + "\n  ".join(errors))

    texts: dict[Path, str] = dict(base or {})  # fix plans the new draft on the text from before the old one
    out = []
    for rule in reply["rules"]:
        path, rel = spoke_path(repo, rule["env_site"], rule["spoke"])
        text = texts[path] if path in texts else path.read_text()
        draft = {k: v for k, v in rule.items() if k not in ("env_site", "spoke")}
        if removal:
            text, key = remove_rule(text, rule["spoke"], draft, rel)
        else:
            index = next_index(text, rule["spoke"], rule_type(draft), rel)
            text, key = insert_rule(text, rule["spoke"], draft, index, rel), f"{index}-{draft['name']}"
        texts[path] = text
        out.append((path, text, key))
    return out


BACKUP = ".backup-"  # in the backup file's name; it never ends in .tfvars, so Terraform ignores it


class BackupsRemainError(DraftError):
    """Backups from an earlier failed write are still on disk; no new write may start until they are dealt with."""


def leftover_backups(repo: Path) -> list[Path]:
    """Every backup file left beside an env-site file by a failed or interrupted write."""
    return sorted(p for p in (Path(repo) / "infra" / "envs").rglob(f".*{BACKUP}*") if p.is_file())


def check_no_backups(repo: Path) -> None:
    """Refuse to go on while any backup remains, naming each one and the file it belongs to."""
    found = leftover_backups(repo)
    if found:
        lines = [f"  {b}  (original bytes of {b.parent / b.name[1:].split(BACKUP)[0]})" for b in found]
        raise BackupsRemainError(
            f"{len(found)} recovery backup(s) remain from an earlier write; no new write starts until each is dealt with:\n"
            + "\n".join(lines)
            + "\nCompare each with its file. Move the backup over the file to restore it, or delete the backup to keep the file.")


class PartialWriteError(OSError):
    """A write and its undo both failed; `changed` maps each file still holding the new text to its backup."""

    def __init__(self, changed: dict[Path, Path], cause: BaseException):
        self.changed = changed
        lines = [f"  {path}: has the new text; original bytes in {backup}" for path, backup in changed.items()]
        super().__init__(f"write failed ({cause}) and could not be undone for {len(changed)} file(s):\n"
                         + "\n".join(lines) + "\nTo restore one, move its backup over it, for example: mv BACKUP FILE")


def _stage(path: Path, data: bytes, tag: str = ".tmp-") -> Path:
    """Write bytes to a new hidden file beside the target, with the target's mode, flushed to disk."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}{tag}")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, path.stat().st_mode & 0o7777)
    except BaseException:
        os.unlink(tmp)
        raise
    return Path(tmp)


def write_all(texts: dict[Path, str]) -> None:
    """Replace every file with its new text; on failure undo from backups, or raise PartialWriteError."""
    backups: dict[Path, Path] = {}
    staged: dict[Path, Path] = {}
    swapped: list[Path] = []
    stuck: dict[Path, Path] = {}  # still has the new text after a failed undo -> its backup, kept
    try:
        for path in texts:
            backups[path] = _stage(path, path.read_bytes(), BACKUP)
        for path, text in texts.items():
            staged[path] = _stage(path, text.encode())
        for path, tmp in staged.items():
            os.replace(tmp, path)
            swapped.append(path)
    except BaseException as error:
        for path in reversed(swapped):
            try:
                os.replace(backups[path], path)
            except OSError:
                stuck[path] = backups[path]
        if stuck:
            raise PartialWriteError(stuck, error) from error
        raise
    finally:
        for path, tmp in list(staged.items()) + list(backups.items()):
            if tmp not in stuck.values() and tmp.exists():
                tmp.unlink()


def apply_reply(repo: Path, ticket: dict, reply: dict) -> list[tuple[Path, str]]:
    """Write the reply into the selected sites' files only; return (path, key) per rule."""
    check_no_backups(repo)
    writes = plan_writes(repo, ticket, reply)
    write_all({path: text for path, text, _ in writes})  # a later rule in the same file holds the latest text
    return [(path, key) for path, _, key in writes]
