# ADR 0001: Facts come from tools, never from search

- **Status:** Accepted
- **Date:** 2026-10-08

## The problem

To write a firewall rule, the agent needs facts. Which rules exist already? Which network does this address belong to? Which firewalls does the traffic pass through? Is the DR site built?

The agent could get these facts in two ways:

1. **Search.** Copy the firewall rules into a search index, and let the agent search it, like searching a website.
2. **Tools.** Small programs that read the real files and systems and give back an exact answer.

## What we decided

Facts come only from tools. Search is used only for written guidance: the standards and the runbooks.

| The agent asks | Who answers |
| --- | --- |
| Does a rule already allow this traffic? | A tool that reads the rule files in `main`. Those files are the source of truth. |
| Is there a rule in Azure that is not in the files? | A tool that reads the live firewall policy. This only finds drift. |
| Which environment, site and spoke is this address in? | A tool that looks the address up in `data/estate/address-plan.yaml` |
| Which firewalls does this traffic pass through? | A tool that reads `data/estate/routing.yaml` |
| Is the DR site built? | Azure Resource Graph |
| How should this kind of rule be written? | Search over `data/standards/` and `data/runbooks/` |

The agent is told never to state a fact that no tool gave it. After it drafts, the Tier 1 checks test the draft again in code. So if the agent gets a fact wrong, the checks still catch it.

## Why

1. **A search index goes out of date.** It is a copy, and it only updates when it is refreshed. A rule added an hour ago may be missing.
2. **Search finds things that look alike.** `10.100.14.0/24` and `10.100.15.0/24` look almost the same to a search engine. They are different networks. A firewall needs the exact one.
3. **Search cuts files into pieces.** A long rule file is split into chunks before it is indexed. A rule can lose the part that says which group it belongs to.
4. **Overlap needs maths.** "Does an existing rule already cover this?" is a question about address ranges and ports. Code can work that out exactly. Search cannot.
5. **Tools leave a record.** Every tool call is logged with what was asked and what came back. A search result only shows what was found, not whether it was right.

## What we did not choose

1. **Put the rules in a search index.** No, for the reasons above.
2. **Paste all the rule files into the agent's prompt.** One real file can run to hundreds of lines, and there are eight firewalls. The cost grows as the estate grows. The agent would still have to do the maths in its head.
3. **A knowledge graph** (a database of how networks and rules connect). The estate is already structured data, so code can read it directly. A later ADR explains this one.

## What this costs us

1. Every fact needs its own tool, and every tool needs tests that can fail. That is more work than one search index.
2. The tools must be protected. Every call must prove who is calling and that they are allowed.
3. Runbooks must never contain real rules or address lists. A runbook like that is out of date as soon as it is saved.
4. Each tool call makes the draft a little slower. We set a time limit and measure it in the eval.

## What would change our mind

Eval results showing that tools miss facts that search would have found, often enough to matter.
