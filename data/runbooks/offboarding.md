# RB-04 — Offboarding

Use for: a relationship with an external party has ended, and every rule for that party must go.
Do not use for: removing one rule while the external party stays (use RB-03).

## RB-04-1 — Confirm the external party and the scope

The ticket names the external party and gives its addresses. The scope is the selected sites of the environments on the ticket, usually all of them at both sites (STD-COLL-05). Rules at sites the ticket does not select stay.

## RB-04-2 — Find every rule for the external party

Using the tools, find every rule in `main` that names the external party in any form. `duplicate_rule_check` finds rules that allow a given flow; check each of these:

- the address ranges the ticket gives
- the host names the ticket gives, such as `api.<name>.example`

Look in every collection type: network, application and DNAT.

## RB-04-3 — Delete the rules

Delete each matching rule, following RB-03-2 and RB-03-4. Deleting a DNAT rule also frees its public port on that firewall.

## RB-04-4 — Escalate instead of drafting when

Each item gives the reason code the reply carries when it stops. Every stop carries a code.

- a rule names this external party together with another one, so deleting it would cut off the other one too: `rule_shared_with_another_party`
- a rule for the external party is in the `hub` group, which serves every spoke: `hub_rule`
