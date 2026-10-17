# ADR 0004: One agent inside a fixed workflow

- **Status:** Accepted
- **Date:** 2026-10-17

## The problem

A firewall change goes through the same steps every time. The ticket is checked, the rule is drafted, the draft is checked, and an engineer approves, edits or rejects it. Only an approved draft becomes a pull request.

Only one of those steps needs a language model: reading a free-text ticket and turning it into a rule. Every other step is a fixed check or a fixed action.

So the question is how much the model controls. It could run one step, or it could decide which step comes next and hand work to other models.

## What we decided

There is one agent. Code runs the steps, always in the same order. The agent runs one step and never decides what happens next.

| Step | Who does it |
| --- | --- |
| Check the ticket against the schema | Code |
| Screen the ticket text with Prompt Shields | Code calls Azure AI Content Safety |
| Draft the rule and write up to three risk notes | **The agent**, calling read-only tools |
| Run the Tier 1 checks and write the draft or block note | Code |
| Approve, edit or reject the draft | The engineer |
| Commit to an `agent/<ticket>` branch and open the pull request | Code |
| Review, build and release | People and the pipeline |

## Why

1. **The order never changes.** Several agents help when a model has to choose between paths. Here the path is fixed, so code can follow it exactly.
2. **The job fits one context.** A ticket, a few tool answers and about 4,000 tokens of standards and runbooks fit easily in one model call.
3. **One agent, not several.** One agent avoids the extra coordination and handoffs between multiple agents. We expect this to reduce complexity and potentially cost and response time. Actual cost and response time will be measured during evaluation.
4. **No model sits next to write access.** Code holds the identity that opens pull requests (ADR 0002). A separate "pull request agent" would put a model next to that identity for no gain.
5. **One thing to score.** The Tier 2 eval scores one agent on one job. Its score says something clear about that job.

## What we did not choose

1. **A main agent that delegates work to specialist agents.** The current task fits one agent, and code already controls the surrounding workflow. We will reconsider only if evaluation shows that splitting the work improves results.
2. **Multi-agent workflows**, in Foundry or in Microsoft Agent Framework. Several agents pass work along a graph, or take turns in a group chat. This suits work whose path depends on the content. Our path does not, so it adds parts to build, trace and score.
3. **Only Python, no model.** We use a language model to interpret free-text requests and propose firewall rules. Ordinary Python handles structured validation, URL parsing and workflow steps. The evaluation measures how reliably the model performs its part.

## What this costs us

1. **One prompt does two jobs:** the draft and the risk notes. If the two pull against each other, the risk notes may get worse. Tier 2, and the Groundedness score added at Step 05, will show it.
2. **The context grows with every tool answer.** A token cap per request limits it (Step 04 Task 05).
3. **One place to fail.** If the agent is down or gives up, nothing is drafted. The ticket goes back to the engineer, as it does for any stop.

## What would change our mind

A Tier 2 failure that splitting the agent would fix. One example: the agent copies an address from a runbook example instead of from a tool.

All three of these must hold before we split:

1. The failure repeats on at least two validation tickets, across repeated runs.
2. A change to the prompt or the tools was tried first and did not remove it.
3. A split version, scored on the same validation set, fixes the failure and scores no worse anywhere else.

The ADR that replaces this one cites those runs: the ticket numbers and both scores.
