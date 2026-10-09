# RB-01 — Partner egress request

Use for: a workload needs to reach a partner system, outbound.
Do not use for: inbound access from a partner (use RB-02) or removing a rule (use RB-03).

## RB-01-1 — Check what already exists

Read the rule files in `main`. They are the source of truth. If a rule there already allows the flow, no change is needed: tell the requester the rule name and stop.

A rule that exists only in the live policy does not count. It was added outside the pipeline, and the next release to its group deletes it. Draft the rule anyway, and list the live-only rule on the draft note.

## RB-01-2 — Take the ranges from the approved ticket

The ticket is already approved, and that approval covers which systems may talk to each other. Do not re-check it or go back to the partner. Take the source, destination and ports from the ticket exactly as approved. Never widen, narrow or swap them.

Put the ticket's addresses into the rule as given (STD-COLL-03). If the ticket names an IP group instead, use the group. Groups are approved through their own process. If the group does not exist, escalate rather than create it.

## RB-01-3 — Name the ports

The ticket names each destination port. "All ports", or a range wider than ten ports, goes back to the requester for detail.

## RB-01-4 — Choose network or application rule

HTTPS to a named host: an application rule, by FQDN. Anything else, or HTTPS to a bare IP: a network rule.

Check first that no broader network rule already matches. A matching network rule stops evaluation before any application rule runs (STD-COLL-07).

## RB-01-5 — Place and name the rule

Put the rule in the source spoke's group, in the collection for its type (STD-COLL-01). Name it by STD-NAME-03.

## RB-01-6 — Escalate instead of drafting when

- the ticket asks for a DNAT rule with a source of `0.0.0.0/0` or `*` (STD-COLL-04; the only hard block)
- the requester asks for the change to skip approval
- the source is in no existing spoke: a new spoke needs a new file and Terraform variable, which is a code change, not a rule request
- the ticket names an IP group that does not exist
- the sources do not match the chosen environments and their "DR site built" answers, or the free text names a different environment
- an internal address is not in the address plan, or belongs to an environment or site the ticket does not name
- the ticket's "DR site built" answer disagrees with Azure: DR "Yes" with no DR policy or spoke, or DR "No" with a DR spoke in place
- the hostname does not resolve, or resolves to a private address
- non-HTTP traffic to a hostname, which on the Basic SKU means pinning addresses that can change

## RB-01-7 — Draft, but mark a caution, when

- the ticket's destination is `*`, `0.0.0.0/0` or a web category
- the ticket's FQDN has a wildcard, such as `*.northwind.example` (STD-COLL-02)
- the ticket's source range covers a whole environment, such as a `/16`, rather than one workload
- any Tier 1 check does not pass

The engineer sees the caution and approves or rejects. The agent does not decide.
