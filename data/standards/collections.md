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

A rule goes in the group of the spoke that owns its source. A DNAT rule goes in the group of the spoke that owns its translated address. A rule whose source is on-prem goes in the group of the spoke that owns its destination, at the destination's env-site (RB-05-4). A group leaves out any collection it has no rules for.

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

A rule uses the addresses the approved ticket gives, exactly as written, and in the same type; a URL gives its hostname, as below. The ticket gives each source and destination as one type: a CIDR, an IP group, a hostname or a URL. That type is part of what the groups approved.

- A CIDR approves that CIDR. The rule writes it as an address (`source_addresses`, `destination_addresses`).
- An IP group approves that group, by name. The ticket must name it, and the rule writes it as an IP group (`source_ip_groups`, `destination_ip_groups`). The group must already exist.
- The two never mix. A ticket asks for a group or for CIDRs, and the rule uses exactly that. This holds for sources and destinations alike.
- The on-prem user groups `ipg-onprem-primary` and `ipg-onprem-secondary` follow the same rule. Either, or both together, may be a source or a destination when the ticket names them. They may be used at any Azure site the ticket selects: "primary" and "secondary" name the on-prem data centre, not the Azure site. A group holds many prefixes, and its members change through its own process, so it is a different approval from any CIDR.
- An exact FQDN, public or internal, approves that FQDN, cleaned, on a network rule (`destination_fqdns`): any `https://` or `http://`, path, space and leading `www.` is dropped, so `www.mozilla .org` and `https://www.mozilla.org/doc/index.html` are drafted as `mozilla.org`, with the ticket's sources, transport protocol and ports; HTTP and HTTPS become TCP. It must resolve through `dns_lookup_for_fqdn` when the rule is drafted, and each IPv4 address (A record) it returns passes the same checks as an address on the ticket (RB-01-4). The rule never lists the returned addresses, and the FQDN stays on the ticket. The firewall resolves the FQDN using its configured DNS servers; clients should use its DNS proxy.
- A wildcard domain pattern approves that pattern, on an HTTP or HTTPS application rule only (`destination_fqdns`), never on a network rule.
- A URL approves the FQDN extracted from it, handled as an exact FQDN, and the ticket's port, on a destination only. The URL itself, path included, stays on the ticket; the rule does not restrict the path. Never correct or substitute the FQDN, apart from that cleaning. On an HTTP or HTTPS ticket, the URL's scheme must be the ticket's protocol, and a port the URL states must be the ticket's one port; if either disagrees, the request goes back to the engineer (`url_port_conflict`, RB-01-6), and neither value is picked.
- This holds for removals too. A CIDR ticket matches only rules written with addresses, and an IP-group ticket only rules that name that group.

No address or FQDN in the rule may be missing from the ticket. The workflow code also refuses to write a draft whose rule uses a value or type the ticket does not approve, names an exact FQDN that did not resolve, or names one whose resolved address fails the scope checks.
Enforced: Tier 1

## STD-COLL-04 — No open DNAT

No DNAT rule may use `0.0.0.0/0` or `*` as its source.

Every way of writing "everyone" counts: a zero-length prefix written with extra zeros, as an all-zero dotted mask, or after any address; the IPv6 all-addresses range; `Any`; a range over every address; several CIDRs that together cover every address; or an IP group whose members do. The workflow code refuses to write such a rule even when the approved ticket asks for it, and Tier 1 blocks it in the plan. Removing such a rule is always allowed, because it closes the hole.

This is the only standard that blocks a draft. Every other Tier 1 standard raises a caution the engineer can approve past with a reason.
Enforced: Tier 1 (blocking)

## STD-COLL-05 — Scope matches the ticket

The ticket answers two separate questions for each environment. "DR site built" says whether the DR site exists. "Sites to change" says which sites this ticket changes: primary only, DR only, or both. The change touches exactly the selected sites of every environment on the ticket. It touches nothing anywhere else, including a DR site that exists but is not selected.

A missing rule at a selected site fails this check. So does a rule at a site the ticket does not select, and a DR change where DR is not built.

Primary and DR do not have to hold the same rules. A rule that exists at an unselected site is left alone and is not a reason to stop.
Enforced: Tier 1

## STD-COLL-06 — DNAT targets and public ports

A DNAT rule translates to one internal host, inside the environment and site of the policy it is in. Its destination is that site's hub firewall public IP, taken from the network data, never from the ticket.

Each public port is used once per firewall public IP and protocol. A DNAT rule fails this check when its destination IP, protocol and port range overlap a rule already on that firewall. TCP 22 and UDP 22 do not conflict.
Enforced: Tier 1

## STD-COLL-07 — No duplicate or shadowed rules

A new rule must not repeat a rule that already exists. It must not be covered by a broader rule either, because then it can never match.

The check compares across collection types, not only within one. A network rule that allows traffic stops evaluation, so an application rule for the same traffic below it never runs.
Enforced: Tier 1

## STD-COLL-08 — A removal deletes only the matched rules

On a remove ticket, the change deletes the rules that match the ticket's flow, at the env-sites in scope. The rules after each deleted rule in the same collection move down to close the gap, in the same order (STD-NAME-03).

Nothing else changes. Every remaining rule keeps its name and fields, only its index may change, and other collections keep their numbers.
Enforced: Tier 1
