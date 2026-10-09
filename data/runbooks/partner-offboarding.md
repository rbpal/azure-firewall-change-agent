# RB-04 — Partner offboarding

Use for: a partner relationship has ended, and every rule for that partner must go.
Do not use for: removing one rule while the partner stays (use RB-03).

## RB-04-1 — Confirm the partner and the scope

The ticket names the partner. It must be a partner in the estate's partner data. The scope is the environments on the ticket, usually all of them, with DR where built (STD-COLL-05).

## RB-04-2 — Find every rule for the partner

Using the tools, find every rule in `main` that names the partner in any form:

- its address range
- its partner IP group, `ipg-partner-<partner>`
- its host names, such as `api.<partner>.example`

Look in every collection type: network, application and DNAT.

## RB-04-3 — Delete the rules

Delete each matching rule, following RB-03-2 and RB-03-4. Deleting a DNAT rule also frees its public port on that firewall.

## RB-04-4 — Do not delete the IP group

The agent never creates, changes or deletes an IP group. Once the rules are gone, write on the ticket that the partner's IP group can now be removed through the IP group process. A group cannot be deleted while a rule still uses it.

## RB-04-5 — Escalate instead of drafting when

- the partner is not in the estate's partner data
- a rule names this partner together with another partner, so deleting it would cut off the other one too
- a rule for the partner is in the `hub` group
