# RB-02 — Inbound DNAT request

Use for: a partner needs to reach an internal server from outside, such as an SFTP server. The ticket's direction is `inbound`.
Do not use for: outbound access (use RB-01) or removing a rule (use RB-03).

## RB-02-1 — Check what already exists

Read the rule files in `main`, as in RB-01-1. If a DNAT rule already publishes the same internal host and port to the same partner range, no change is needed: tell the requester the rule name and stop.

## RB-02-2 — Take the details from the approved ticket

From the ticket, take exactly:

- the source: the partner's range or partner IP group
- the destination: the internal host, one per environment and site
- the internal port, from `ports`
- the public port the partner connects to, from `public_port`
- the protocol: TCP or UDP

Never widen the source. A source of `0.0.0.0/0` or `*` is never drafted (STD-COLL-04).

## RB-02-3 — Use the firewall's public IP from the estate data

The rule's destination address is the public IP of the hub firewall at that environment and site. Take it from the estate's routing data, never from the ticket (STD-COLL-06).

Check that the public port is not already published on that firewall. If it is, escalate. Two DNAT rules cannot share one public IP and port.

## RB-02-4 — Place and name the rule

Put the rule in the DNAT collection of the spoke that owns the internal host (STD-COLL-01). Name it by STD-NAME-03, with the partner as the source and the spoke plus role as the destination, such as `sftp-northwind-to-xferSftp`.

Azure Firewall adds a matching allow rule for the translated traffic itself. Do not draft a separate network rule for it.

## RB-02-5 — Escalate instead of drafting when

- the source is `0.0.0.0/0` or `*` (STD-COLL-04; the only hard block)
- the destination is not a single internal host, or the host is not in the address plan
- the public port is already published on that firewall
- the ticket marks "DR site built: Yes" but gives no DR host, or gives a DR host where DR is not built
- the protocol is anything other than TCP or UDP

## RB-02-6 — Draft, but mark a caution, when

- the partner's source range is wider than a `/24`
- any Tier 1 check does not pass

The engineer sees the caution and approves or rejects. The agent does not decide.
