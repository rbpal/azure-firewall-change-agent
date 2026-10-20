# RB-05 — On-prem access request

Use for: on-prem users reach an Azure workload, or an Azure workload reaches on-prem users. The on-prem side is an on-prem CIDR with its `location`, or the IP group `ipg-onprem-primary` or `ipg-onprem-secondary`.
Do not use for: a partner (use RB-01 or RB-02) or removing a rule (use RB-03).

## RB-05-1 — Find where each address lives

Call `locate_address_for_env_site` for every CIDR on the ticket. An Azure address answers with its environment, site and spoke. An on-prem user subnet answers with its data centre (`location`) and its ExpressRoute connection, and with no env-site of its own. Never decide either yourself.

## RB-05-2 — Check what already exists

Call `duplicate_rule_check` for each selected site, as in RB-01-1. Only a like-for-like match means the flow is already allowed: a rule that names the same IP group, or one written with addresses for a CIDR ticket (STD-COLL-03).

## RB-05-3 — Take the addresses from the approved ticket

Use the ticket's values in the ticket's type (STD-COLL-03). An on-prem IP group goes in by name. An on-prem CIDR goes in as an address. Never put a spoke IP group in place of an on-prem group: spoke groups hold only their spoke's subnet, and on-prem users are only in `ipg-onprem-primary` and `ipg-onprem-secondary`.

## RB-05-4 — Choose the firewall and the group

Each on-prem data centre connects to every hub over ExpressRoute. The rule goes at the env-site of the ticket's Azure address, at each site the ticket selects.

This rests on an assumption that has not been verified: only that spoke's own hub firewall inspects the traffic. Connections to every hub do not prove it. It also needs on-prem routers to prefer the direct hub's routes, routing intent on every hub, and no path through a second hub. If traffic crossed a second hub, that hub's firewall would need the rule too.

- On-prem source, Azure destination: the rule goes in the group of the spoke that owns the destination (STD-COLL-01).
- Azure source, on-prem destination: the rule goes in the source spoke's group, as usual.

Use a network rule; on-prem flows name addresses, not hostnames. Name it by STD-NAME-03.

## RB-05-5 — Escalate instead of drafting when

Each item gives the reason code the reply carries when it stops. An item marked *no code yet* has none; the reply stops and says why in words.

- an on-prem CIDR is not in the address plan's on-prem list: `address_not_in_plan`
- an on-prem CIDR belongs to the other data centre than its `location` says: `env_mismatch` (RB-01-6). Stop and ask which source is intended; never change the CIDR or the location yourself
- both ends are on-prem: that traffic never reaches an Azure firewall: *no code yet*
- the Azure address is at a site the ticket does not select: `address_for_unselected_site`
- a selected site has no Azure address: `site_without_address`
- any reason in RB-01-6 that applies, with the code given there: a skip-approval request, free text naming another environment, or an IP group that does not exist
