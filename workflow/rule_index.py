"""Work out the next free rule index in one collection of a spoke's rules file.

Example: in a sett.tfvars whose network collection runs 001-006 and whose app
collection runs 001-009, `next_index(text, "sett", "network")` returns "007".

Why: the agent drafts a rule name without an index, and code picks the number
(STD-NAME-03). Each collection, DNAT, network and application, counts on its own
from 001, so the function reads only the collection the rule belongs to.

Safety rule: it never searches the whole file for "NNN-" keys, which would mix
the three counts. It stops on a gap, a duplicate or a malformed key instead of
guessing, because STD-NAME-03 says numbers run from 001 with no gaps.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mcp"))

from data_readers.read_env_site_ipgroup import parse_rules  # noqa: E402

# Rule type -> the word STD-NAME-02 puts in the collection name.
TYPE_WORD = {"dnat": "dnat", "network": "network", "application": "app"}
INDEX = re.compile(r"^(\d{3})-")
MAX_INDEX = 999


class RuleIndexError(ValueError):
    """A collection's keys break STD-NAME-03, so no safe next index exists."""


def collection_name(spoke: str, rule_type: str) -> str:
    """The collection a rule of this type belongs to in this spoke, by STD-NAME-02."""
    if rule_type not in TYPE_WORD:
        raise RuleIndexError(f"unknown rule type {rule_type!r}; use one of {sorted(TYPE_WORD)}")
    return f"allow-{spoke}-{TYPE_WORD[rule_type]}-rules"


def collection_indexes(text: str, spoke: str, rule_type: str, path: str = "<tfvars>") -> list[int]:
    """List the index numbers of one collection's rules, checked to run 1..n with no gap."""
    wanted = collection_name(spoke, rule_type)
    group = parse_rules(text, spoke, path)
    matches = [c for c in group["collections"] if c["name"] == wanted]
    if not matches:
        return []  # the collection does not exist yet; code creates it with the rule
    if matches[0]["type"] != rule_type:
        raise RuleIndexError(f"{path}: {wanted} is a {matches[0]['type']} collection, not {rule_type}")
    numbers = []
    for rule in matches[0]["rules"]:
        found = INDEX.match(rule["key"])
        if not found:
            raise RuleIndexError(f"{path}: {wanted} key {rule['key']!r} has no three-digit index")
        numbers.append(int(found.group(1)))
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise RuleIndexError(f"{path}: {wanted} indexes {sorted(numbers)} do not run 001-{len(numbers):03d} with no gap")
    return sorted(numbers)


def next_index(text: str, spoke: str, rule_type: str, path: str = "<tfvars>") -> str:
    """Return the next free index in the rule type's collection, as three digits."""
    n = len(collection_indexes(text, spoke, rule_type, path)) + 1
    if n > MAX_INDEX:
        raise RuleIndexError(f"{path}: {collection_name(spoke, rule_type)} already holds {MAX_INDEX} rules")
    return f"{n:03d}"
