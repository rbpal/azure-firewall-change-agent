"""Standards and runbook pages: the only text the agent searches.

These tests hold the page rules from the plan: one standard per heading with
a stable ID, an Enforced line on every standard, no live addresses, and no
reference to a section that does not exist.
"""

import re
from pathlib import Path

import pytest

DATA = Path(__file__).resolve().parent.parent / "data"
PAGES = {
    "standards/naming.md": "STD-NAME",
    "standards/collections.md": "STD-COLL",
    "runbooks/partner-egress.md": "RB-01",
    "runbooks/inbound-dnat.md": "RB-02",
    "runbooks/rule-removal.md": "RB-03",
    "runbooks/partner-offboarding.md": "RB-04",
}
SECTION = re.compile(r"^## ((STD-[A-Z]+-\d{2})|(RB-\d{2}-\d+)) — \S", re.M)
REFERENCE = re.compile(r"\b(STD-[A-Z]+-\d{2}|RB-\d{2}-\d+|RB-\d{2})\b")
IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?:/\d{1,2})?\b")


def read(rel):
    return (DATA / rel).read_text()


def sections(text):
    """(id, body) for each ## section."""
    parts = re.split(r"^(?=## )", text, flags=re.M)
    out = []
    for part in parts:
        m = SECTION.match(part)
        if m:
            out.append((m.group(1), part))
    return out


def test_exactly_the_planned_pages_exist():
    found = {str(p.relative_to(DATA)) for d in ("standards", "runbooks") for p in (DATA / d).glob("*.md")}
    assert found == set(PAGES)


@pytest.mark.parametrize("rel,page_id", PAGES.items())
def test_title_carries_the_page_id(rel, page_id):
    assert read(rel).startswith(f"# {page_id} — ")


@pytest.mark.parametrize("rel,page_id", PAGES.items())
def test_every_section_has_a_stable_numbered_id(rel, page_id):
    text = read(rel)
    headings = re.findall(r"^## .*$", text, re.M)
    ids = [sid for sid, _ in sections(text)]
    assert len(ids) == len(headings), f"{rel}: a ## heading has no ID"
    assert all(sid.startswith(page_id + "-") for sid in ids), rel
    numbers = [int(sid.rsplit("-", 1)[1]) for sid in ids]
    assert numbers == list(range(1, len(ids) + 1)), f"{rel}: IDs must run 1, 2, 3 with no gaps"


@pytest.mark.parametrize("rel", [r for r in PAGES if r.startswith("standards/")])
def test_every_standard_says_how_it_is_enforced(rel):
    for sid, body in sections(read(rel)):
        lines = re.findall(r"^Enforced: (.+)$", body, re.M)
        assert lines in (["Tier 1"], ["Tier 1 (blocking)"], ["Reviewer"]), f"{sid}: {lines}"


def test_only_one_standard_blocks():
    blocking = [sid for rel in PAGES for sid, body in sections(read(rel)) if "Enforced: Tier 1 (blocking)" in body]
    assert blocking == ["STD-COLL-04"]


@pytest.mark.parametrize("rel", PAGES)
def test_no_live_addresses(rel):
    # Addresses come from tickets and tools, never from these pages (ADR 0001).
    found = [a for a in IPV4.findall(read(rel)) if a != "0.0.0.0/0"]
    assert found == [], f"{rel}: {found}"


def test_every_reference_points_to_something_that_exists():
    known = set(PAGES.values()) | {sid for rel in PAGES for sid, _ in sections(read(rel))}
    for rel in PAGES:
        for ref in REFERENCE.findall(read(rel)):
            assert ref in known, f"{rel} cites {ref}, which does not exist"


def test_ids_are_unique_across_pages():
    ids = [sid for rel in PAGES for sid, _ in sections(read(rel))]
    assert len(ids) == len(set(ids))
