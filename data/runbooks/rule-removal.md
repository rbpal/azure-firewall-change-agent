# RB-03 — Rule removal request

Use for: a `Firewall Rule Removal` ticket. The traffic is no longer needed.
Do not use for: a partner leaving altogether (use RB-04).

## RB-03-1 — Find the rules that match the flow

The ticket describes the traffic to remove: source, destination, protocol and ports. Call `duplicate_rule_check` with that flow at every selected site: the environments on the ticket, and for each one the sites under "Sites to change". A rule it marks `duplicate` allows exactly that traffic, and only such a rule may be deleted. A rule marked `covers` allows more than the ticket's flow; see RB-03-2.

The ticket may also name the rule. Use the name only to confirm the match. The match decides, not the name.

Compare like with like (STD-COLL-03). A ticket that gives CIDRs matches only rules written with addresses. A ticket that names an IP group matches only rules that name that group. `duplicate_rule_check` expands groups into their addresses, so check the rule's type yourself; a rule of the other type is not a match.

## RB-03-2 — Delete only an exact match

If a rule matches the ticket's flow exactly, delete it. Delete it at every selected site, and only there (STD-COLL-05). A primary-only ticket leaves the DR copy in place, and a DR-only ticket leaves the primary copy. The copy at the other site is not a reason to stop.

For a DNAT rule, the ticket's `ports` are the ports the rule publishes on the firewall. The rule's translated address and translated port must match the stored rule exactly; take them from the matched rule, never change them. RB-02-2's "translated to the same port" applies to new rules only. So an older rule that publishes 2221 and translates to 22 is removed by a ticket for port 2221. A ticket for port 22 does not match it.

If a rule allows more than the ticket's flow, such as an extra source or port, do not trim it. Removing part of a rule changes it, and nobody approved that change. Escalate.

## RB-03-3 — When nothing matches

If no rule in `main` matches, there is nothing to remove. Tell the requester and stop.

If the traffic is allowed only by a rule that exists in the live policy but not in `main`, say so on the ticket. The next release to that group deletes it anyway.

## RB-03-4 — Close the gap

Delete the rule's entry. The workflow code then renumbers the rules after it in the same collection, in that file only, so the numbers run from `001` with no gaps (STD-NAME-03). Only the index moves. Every rule keeps its name, fields and order, and other collections keep their numbers (STD-COLL-08).

## RB-03-5 — Escalate instead of drafting when

Each item gives the reason code the reply carries when it stops. An item marked *no code yet* has none; the reply stops and says why in words.

- a matching rule also allows other traffic the ticket does not mention (`duplicate_rule_check` says `covers`): `rule_allows_more`
- the rule is in the `hub` group, which serves every spoke: `hub_rule`
- the ticket asks to delete or change an IP group; IP groups have their own approval process: `ip_group_change_requested`
- a selected site has no exact match while another selected site does; a rule at a site the ticket does not select is not a reason to escalate: `partial_site_match`
- any address check in RB-01-6 fails: the code given there
