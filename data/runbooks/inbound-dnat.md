# RB-02 — Inbound DNAT request

Use for: a partner needs to reach an internal server from outside, such as an SFTP server. The ticket's source is a partner address and its destination is an internal address with an environment and site.
Do not use for: outbound access (use RB-01) or removing a rule (use RB-03).

## RB-02-1 — Check what already exists

Call `duplicate_rule_check`, as in RB-01-1. If it lists a DNAT rule that already publishes the same internal host and port to the same partner range, no change is needed: tell the requester the rule name and stop.

## RB-02-2 — Take the details from the approved ticket

From the ticket, take exactly:

- the source: the partner's range or partner IP group
- the destination: the internal host, one per environment and site
- the port, from `ports`: the partner connects on it at the firewall's public IP, and it is translated to the same port on the internal host
- the protocol: TCP or UDP

Never widen the source. A source of `0.0.0.0/0` or `*` is never drafted (STD-COLL-04).

## RB-02-3 — Use the firewall's public IP from the network data

The rule's destination address is the public IP of the hub firewall at that environment and site. Take it from the routing data, never from the ticket (STD-COLL-06).

Check that the port is not already published on that firewall. If it is, escalate. Two DNAT rules cannot share one public IP and port.

## RB-02-4 — Place and name the rule

Put the rule in the DNAT collection of the spoke that owns the internal host (STD-COLL-01). Name it by STD-NAME-03, with the partner as the source and the spoke plus role as the destination, such as `sftp-northwind-to-xferSftp`.

Azure Firewall adds a matching allow rule for the translated traffic itself. Do not draft a separate network rule for it.

## RB-02-5 — Escalate instead of drafting when

Each item gives the reason code the reply carries when it stops. An item marked *no code yet* has none; the reply stops and says why in words.

- the source is `0.0.0.0/0` or `*` (STD-COLL-04; the only hard block): *no code yet*
- the destination is not a single internal host: *no code yet*
- the host is not in the address plan: `address_not_in_plan`
- the host belongs to an environment or site other than the one the ticket gives it: `env_mismatch` (RB-01-6)
- the port is already published on that firewall: `port_already_published`
- a selected site has no internal host: `site_without_address`
- a host belongs to a site the ticket does not select: `address_for_unselected_site`
- the protocol is anything other than TCP or UDP: *no code yet*

## RB-02-6 — Draft, but mark a caution, when

- the partner's source range is wider than a `/24`
- any Tier 1 check does not pass

The engineer sees the caution and approves or rejects. The agent does not decide.
