# ADR 0005: Requests come in through a command-line tool until ServiceNow

- **Status:** Accepted
- **Date:** 2026-10-17 (decision made 2026-10-08)

## The problem

In the real process, an approved ServiceNow ticket starts every firewall change. ServiceNow arrives at Step 09.

Until then, an engineer still needs a way to hand a ticket to the workflow, read the agent's draft, and approve, fix or reject it.

## What we decided

A Python command-line tool, `fwagent`, run on the engineer's laptop.

| Command | What it does |
| --- | --- |
| `fwagent submit <ticket.yaml>` | Checks the ticket. A ticket with a problem is saved as awaiting review and never reaches the agent. Otherwise it gets the agent's reply, writes a draft into the tfvars files and prints the draft note; a stop is saved as awaiting review |
| `fwagent fix <ticket> "<correction>"` | Sends the engineer's correction to the agent and rewrites the draft |
| `fwagent edit <ticket> <edited.yaml>` | Replaces a ticket awaiting review with the engineer's edit, records what changed, and runs every check again |
| `fwagent accept <ticket>` | Records the engineer's acceptance and reason, then lets the agent draft within the ticket's own values; refused while any value is invalid or missing |
| `fwagent reject <ticket> "<reason>"` | Removes any draft from the files and closes the ticket with the reason |
| `fwagent approve <ticket>` | Hands the approved draft to the pull request step |

Amended 2026-10-20: the workflow never rejects a ticket on its own. Problems wait for the engineer, who rejects, edits or accepts (`edit` and `accept` added; RB-01-8).

The tool signs in with the engineer's own `az login`. The draft shows up as a normal diff in VS Code.

## Why

1. **The engineer sees the real change.** The draft lands in the tfvars files, so the review is a normal file diff, the same thing the pull request reviewers will see.
2. **Nothing new to host or protect.** No web server, no sign-in page, no public endpoint and no new Azure resource. The tool uses the engineer's existing Entra sign-in.
3. **Easy to test.** Each command is a Python function, so pytest covers it like the rest of the workflow code.

## What we did not choose

1. **A small web form.** It needs hosting, its own sign-in and protection against cross-site attacks. It also shows the draft as a form, not as the file change the reviewers will approve.
2. **A Teams or chat bot.** It needs a bot registration, a hosted endpoint and a second place where tickets live.
3. **ServiceNow now.** The real integration is Step 09. Building it first would delay the agent and its eval.

## What this costs us

1. **Engineers only.** Requesters cannot submit tickets themselves. Until Step 09 an engineer types in each ticket as YAML.
2. **One laptop at a time.** Drafts live in that engineer's working copy until approval.
3. **Thrown away later.** ServiceNow replaces the front end at Step 09. The writer code behind it stays.

## What would change our mind

Requesters who are not engineers need to submit tickets before ServiceNow is ready, or several engineers need to see each other's drafts before approval. Then a hosted front end earns its cost.
