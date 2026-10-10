# STD-NAME — Firewall naming standard

Applies to every object in the Contoso firewall policies. Names are lower case, hyphen-separated and plain ASCII, except where a standard below says lowerCamelCase.

## STD-NAME-01 — Rule collection groups

One group per spoke, named by the spoke code: four lower-case letters, such as `sett`. Shared hub rules go in the group `hub`.

The environment and site come from the file's folder, never from the name. So a group has the same name in all eight policies.
Enforced: Tier 1

## STD-NAME-02 — Rule collections

Pattern: `allow-<spoke>-<type>-rules`, where `<type>` is `dnat`, `network` or `app`. The type must match the kind of rules the collection holds.
Example: `allow-sett-network-rules`
Enforced: Tier 1

## STD-NAME-03 — Rules

Map key: `<index>-<service>-<source>-to-<destination>`. The rule's `name` is the key without the index.

- `<service>` is the lower-case service or protocol, such as `https`, `ssh` or `sftp`.
- `<source>` and `<destination>` are lowerCamelCase: a spoke code, a spoke plus a role, or a partner plus a system. Hub rules use `spokes` as the source.

Examples: `024-https-sett-to-northwindFs`, `001-https-sett-to-northwindApi`, `001-sftp-northwind-to-xferSftp`

The index is three digits, zero-padded, and unique within its collection. Each collection in a group, DNAT, network and application, counts on its own from `001`. The numbers run from `001` with no gaps. A new rule takes the next number after the last one. When a rule is removed, every rule after it in the same collection moves down one number, in the same order (STD-COLL-08).

The workflow code assigns the index from the latest `main` when it writes the rule, and renumbers the collection when it deletes one. A draft gives the name only, without an index.

The rules are stored as a map, and Terraform reads map keys in sorted order. So the index fixes the order rules are listed in, and a new rule always lands at the end of the diff. Zero-padding matters: without it, `10-` sorts before `9-`. Three digits allow 999 rules per collection.

The Azure rule name leaves the index out, so the name in the portal stays readable. The key keeps it, so the order and the diff stay stable. Renumbering therefore changes only keys in the tfvars file. The firewall sees the same rule names, in the same order.

A DR file mirrors its primary, so the same rule has the same key at both sites.
Enforced: Tier 1

## STD-NAME-04 — IP groups

Internal: `ipg-<spoke>-<env>[-dr]`, such as `ipg-sett-prod` or `ipg-sett-dev-dr`.
Partner: `ipg-partner-<partner>`, such as `ipg-partner-northwind`.

IP groups are created through their own approval process, never through a rule request.
Enforced: Tier 1

## STD-NAME-05 — No ticket numbers in rules

A rule name says who talks to whom, on what. It never contains a ticket number or a date. A rule has no ticket field either.

The ticket number lives in the change record: the branch name, the commit message and the pull request title. Following a rule's commit in git leads to its ticket.
Enforced: Tier 1
