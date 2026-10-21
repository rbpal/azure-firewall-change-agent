# RB-01 — Partner egress request

Use for: a workload needs to reach a partner system, outbound.
Do not use for: inbound access from a partner (use RB-02) or removing a rule (use RB-03).

## RB-01-1 — Check what already exists

Call the `duplicate_rule_check` tool for each selected site on the ticket. It reads the rule files in `main`, which are the source of truth. If it lists a rule, that rule already allows the flow: no change is needed there. Tell the requester the rule name and stop. Never decide this by reading rules yourself; the tool does the address and port maths (STD-COLL-07).

A rule that exists only in the live policy does not count. It was added outside the pipeline, and the next release to its group deletes it. Draft the rule anyway, and list the live-only rule on the draft note.

## RB-01-2 — Take the ranges from the approved ticket

The ticket is already approved, and that approval covers which systems may talk to each other. Do not re-check it or go back to the partner. Take the source, destination and ports from the ticket exactly as approved. Never widen, narrow or swap them.

Put the ticket's addresses into the rule as given, in the ticket's type (STD-COLL-03). A CIDR on the ticket goes into the rule as that CIDR. An IP group goes in only when the ticket names it, and then by name. The two never mix: never put a group in place of a CIDR, or a CIDR in place of a group. Groups are approved through their own process. If the named group does not exist, escalate rather than create it.

## RB-01-3 — Name the ports

The ticket names each destination port. "All ports", or a range wider than ten ports, goes back to the requester for detail.

## RB-01-4 — Choose network or application rule

HTTPS to a named host: an application rule, by FQDN. Anything else, or HTTPS to a bare IP: a network rule.

For every hostname on the ticket, call the `dns_lookup_for_fqdn` tool first. Never judge a hostname yourself. If the tool refuses the URL, escalate under RB-01-6. If it answers `resolves: false`, draft the rule anyway and mark a caution under RB-01-7. Never change the URL yourself, even for an obvious typing mistake: the approved ticket is the scope.

Check first that no broader network rule already matches. A matching network rule stops evaluation before any application rule runs (STD-COLL-07).

## RB-01-5 — Place and name the rule

Put the rule in the source spoke's group, in the collection for its type (STD-COLL-01). Name it by STD-NAME-03.

## RB-01-6 — Escalate instead of drafting when

Escalating means the reply's outcome is `stop_and_ask`: the request waits for the engineer's review. It is never a rejection; the engineer rejects, edits or accepts it (RB-01-8).

Each item gives the reason code the reply carries when it stops. An item marked *no code yet* has none; the reply stops and says why in words.

- the ticket asks for a DNAT rule with a source of `0.0.0.0/0` or `*` (STD-COLL-04; the only hard block): *no code yet*
- the requester asks for the change to skip approval: `skip_approval_requested`
- an Azure address sits inside an env-site, but no spoke or shared range owns it (`locate_address_for_env_site` answers `no_owner`), as with a spoke that is planned but not built: `planned_address`. Preparing policy before a spoke exists can be valid. Ask the engineer to confirm the CIDR, environment, site, firewall policy and rule placement; never pick a spoke yourself. An on-prem source is not this case; it follows RB-05
- an address is wider than the plan range it belongs to, or spans several (`locate_address_for_env_site` answers `wider_than_plan`): `wider_than_plan`. Name the plan ranges and the extra blocks the tool lists, with their address count; never narrow the address yourself. An address narrower than its range, inside one owner's range, is not a reason to stop
- the ticket names an IP group that does not exist: *no code yet*
- a selected site has no source: `site_without_address`
- a source belongs to a site the ticket does not select: `address_for_unselected_site`
- the free text names a different environment from the ticket's fields: `free_text_conflict`
- an address is not in the address plan, Azure or on-prem: `address_not_in_plan`
- an address belongs to an environment, an Azure site (primary or DR) or an on-prem location other than the one the ticket gives it: `env_mismatch`. This one code covers all three conflicts. Stop and ask which is intended; never correct the address or the place yourself
- the ticket's "DR site built" answer disagrees with Azure: DR "Yes" with no DR policy or spoke, or DR "No" with a DR spoke in place: `dr_policy_not_built`. This answer only says whether DR exists; DR is changed only when "Sites to change" selects it
- the URL is not valid (`dns_lookup_for_fqdn` refuses it), the lookup could not run, or the hostname resolves to a private address: *no code yet*
- non-HTTP traffic to a hostname, which on the Basic SKU means pinning addresses that can change: *no code yet*

## RB-01-7 — Draft, but mark a caution, when

- the ticket's destination is `*`, `0.0.0.0/0` or a web category
- the ticket's FQDN has a wildcard, such as `*.northwind.example` (STD-COLL-02)
- any Tier 1 check does not pass
- the hostname does not resolve (`dns_lookup_for_fqdn` answers `resolves: false`). The engineer has three choices: correct the URL on the ticket and run it again, reject the ticket because the URL may be wrong, or approve anyway with a reason, for example a DNS record the partner creates at go-live. An approval past this caution is written into the PR description

The engineer sees the caution and approves or rejects. The agent does not decide.

## RB-01-8 — Engineer review

Every request that cannot be drafted waits for the engineer. Nothing is rejected without the engineer's decision.

Code checks the ticket before the agent sees it. A malformed or incomplete ticket is saved for review and never reaches the agent:

1. **Invalid ticket.** A field breaks the ticket schema, such as a missing `change_sites`.
2. **Invalid address.** A CIDR that cannot exist, such as a `/33` prefix (IPv4 has 32 bits), or one with host bits set: an address that is not the first address of its prefix. That one has two readings, a single host (`/32`) or the whole subnet, and the workflow picks neither.
3. **Missing address.** A VNet or subnet named with no CIDR or IP group. A VNet name found in the address plan is shown as a suggestion with its file, never applied.

The engineer then decides:

- **Reject.** The request closes and nothing is implemented.
- **Edit.** The engineer supplies the corrected ticket. Every check runs again on it, and the draft uses only the confirmed values. The edit and its author are recorded. An edit never changes the ticket's state or approvals.
- **Accept.** The engineer approves the request as it stands, with a reason; the name, time and reason are recorded. Accept is possible only for `wider_than_plan`, `planned_address`, `address_not_in_plan` and `skip_approval_requested`. An unknown or planned address also needs the engineer's record of its CIDR, environment, site, firewall policy and placement. The draft still passes every scope check, so acceptance never adds an address or a site.

An invalid, missing or contradictory value can only be cleared by an edit with a valid value. Acceptance alone never makes it executable, and the agent never invents a correction.

When a planned address is placed in a spoke that does not exist yet, the request waits for the platform change. The workflow lists what that spoke still needs at each site: its rules file, its Terraform variable and map entry, its IP group if the ticket names one, and its entries in the routing and address plan.
