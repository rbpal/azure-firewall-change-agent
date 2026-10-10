# RB-03 — Rule removal request

Use for: a ticket with change type `remove_rule`. The traffic is no longer needed.
Do not use for: a partner leaving altogether (use RB-04).

## RB-03-1 — Find the rules that match the flow

The ticket describes the traffic to remove: source, destination, protocol and ports. At every environment and site in scope, find the rules in `main` that allow exactly that traffic.

The ticket may also name the rule. Use the name to check your match, but the match decides, not the name.

## RB-03-2 — Delete only an exact match

If a rule matches the ticket's flow exactly, delete it. Delete it at every environment and site in scope, including DR where the ticket marks DR as built (STD-COLL-05).

If a rule allows more than the ticket's flow, such as an extra source or port, do not trim it. Removing part of a rule changes it, and nobody approved that change. Escalate.

## RB-03-3 — When nothing matches

If no rule in `main` matches, there is nothing to remove. Tell the requester and stop.

If the traffic is allowed only by a rule that exists in the live policy but not in `main`, say so on the ticket. The next release to that group deletes it anyway.

## RB-03-4 — Close the gap

Delete the rule's entry. The workflow code then renumbers the rules after it in the same collection, so the numbers run from `001` with no gaps (STD-NAME-03). Only the index moves. Every rule keeps its name, fields and order, and other collections keep their numbers (STD-COLL-08).

## RB-03-5 — Escalate instead of drafting when

- a matching rule also allows other traffic the ticket does not mention
- the rule is in the `hub` group, which serves every spoke
- the ticket asks to delete or change an IP group; IP groups have their own approval process
- the ticket's scope disagrees with where the rule exists, such as a rule found at a site the ticket does not name
