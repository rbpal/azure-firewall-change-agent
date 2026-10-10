# STD-COLL — Rule collection standard

Where each rule goes, which priorities are used, and what is never allowed.

## STD-COLL-01 — Groups, collections and priorities

Each environment and site has its own firewall policy. It holds one rule collection group per spoke, plus `hub` for shared hub rules. Every group uses the same priorities.

| Level | Name | Priority |
| --- | --- | --- |
| Group | `<spoke>` or `hub` | 200 |
| DNAT collection | `allow-<spoke>-dnat-rules` | 1000 |
| Network collection | `allow-<spoke>-network-rules` | 2000 |
| Application collection | `allow-<spoke>-app-rules` | 3000 |

A rule goes in the group of the spoke that owns its source. A DNAT rule goes in the group of the spoke that owns its translated address. A group leaves out any collection it has no rules for.

Network and application collections use the action `Allow`. DNAT collections use `Dnat`. No collection uses `Deny`. With Allow only, the order of the groups that share priority 200 cannot change which traffic passes. A Deny rule would make that order matter, so it fails this check.

Azure Firewall always checks DNAT rules first, then network rules, then application rules, whatever the priority numbers say.
Enforced: Tier 1

## STD-COLL-02 — Wildcards are flagged

These always raise a caution:

- `*` or `0.0.0.0/0` as a source or destination
- any FQDN with a wildcard in an application rule: a bare `*`, a whole top-level domain such as `*.com`, or one company's domain such as `*.northwind.example`
- web categories

A wildcard on one company's domain is sometimes needed, but it covers every subdomain, including ones that do not exist yet. So the engineer approves it on purpose, with a reason the PR reviewers see.
Enforced: Tier 1

## STD-COLL-03 — Addresses match the ticket

A rule uses the IP addresses, subnets or CIDRs the approved ticket gives, exactly as written. If the ticket names an IP group, the rule uses that group, and the group must already exist. No address in the rule may be missing from the ticket.
Enforced: Tier 1

## STD-COLL-04 — No open DNAT

No DNAT rule may use `0.0.0.0/0` or `*` as its source.

This is the only standard that blocks a draft. Every other Tier 1 standard raises a caution the engineer can approve past with a reason.
Enforced: Tier 1 (blocking)

## STD-COLL-05 — Scope matches the ticket

The change touches the primary site of every environment on the ticket, and the DR site of each one the ticket marks "DR site built: Yes". It touches nothing anywhere else.

A missing DR rule where DR is built fails this check. So does a DR rule where DR is not built.
Enforced: Tier 1

## STD-COLL-06 — DNAT targets and public ports

A DNAT rule translates to one internal host, inside the environment and site of the policy it is in. Its destination is that site's hub firewall public IP, taken from the estate data, never from the ticket.

Each public port is used once per firewall. A DNAT rule that reuses a port already published on that firewall fails this check.
Enforced: Tier 1

## STD-COLL-07 — No duplicate or shadowed rules

A new rule must not repeat a rule that already exists. It must not be covered by a broader rule either, because then it can never match.

The check compares across collection types, not only within one. A network rule that allows traffic stops evaluation, so an application rule for the same traffic below it never runs.
Enforced: Tier 1

## STD-COLL-08 — A removal deletes only the matched rules

On a remove ticket, the change deletes the rules that match the ticket's flow, at the env-sites in scope. The rules after each deleted rule in the same collection move down to close the gap, in the same order (STD-NAME-03).

Nothing else changes. Every remaining rule keeps its name and fields, only its index may change, and other collections keep their numbers.
Enforced: Tier 1
