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

import os
import tempfile
from pathlib import Path

import yaml

from workflow.rule_index import next_index
from workflow.tfvars_writer import DraftError, insert_rule, remove_rule, rule_type, spoke_path

from data_readers.read_addressplan_routing import ROUTING  # noqa: E402  (tfvars_writer puts mcp/ on the path)

REMOVAL_ITEM = "Firewall Rule Removal"


class ScopeError(DraftError):
    """The reply and the ticket's selected sites disagree; nothing is written."""


def selected_env_sites(repo: Path, ticket: dict) -> set[str]:
    """The env-sites the ticket changes, such as {"prod-centralus"}, from routing.yaml."""
    sites = yaml.safe_load((Path(repo) / ROUTING).read_text())["env_sites"]
    by_name = {(s["environment"], s["site"]): name for name, s in sites.items()}
    return {by_name[(env, site)] for env, chosen in ticket["change_sites"].items() for site in chosen}


def plan_writes(repo: Path, ticket: dict, reply: dict) -> list[tuple[Path, str, str]]:
    """Work out every changed file in memory; return (path, new text, key) per rule, or raise."""
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

    texts: dict[Path, str] = {}
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
    writes = plan_writes(repo, ticket, reply)
    write_all({path: text for path, text, _ in writes})  # a later rule in the same file holds the latest text
    return [(path, key) for path, _, key in writes]
