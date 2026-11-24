## SR details

**SR number:** RITM0013525
**Requested by:** Morgan Lee (Contoso reporting)
**Demo data:** the ticket file marks its names and addresses as synthetic.

## AI disclaimer

These rules were drafted with AI assistance. Check every rule against the ticket and the security policy before you approve.

## Summary

**Branch changes:** The reporting batch servers in dev read public reference articles from www.wikipedia.org over HTTPS 443. This branch adds 2 network rules: primary (eastus2) and DR (centralus). Each names the FQDN `wikipedia.org`; the ticket's `www.` is removed. It adds 14 lines across 2 rule files. No existing rule changes.

**DNS lookup:** FQDN `wikipedia.org` → public IP `208.80.154.224`

## Changed files and rules

**dev-eastus2 (primary, eastus2)**

- **Path:** `infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/rprt.tfvars`
- **Rule collection:** `allow-rprt-network-rules` (priority 2000, Allow)
- **Rule key:** `011-https-rprt-to-wikipedia`

**dev-centralus (dr, centralus)**

- **Path:** `infra/envs/dev-centralus/firewall_policy_rule_collection_groups/rprt.tfvars`
- **Rule collection:** `allow-rprt-network-rules` (priority 2000, Allow)
- **Rule key:** `010-https-rprt-to-wikipedia`

## Packet flow

```text
PRIMARY: Azure Region Eastus2

                        ┌────────────────────────┐
10.104.15.0/24 ────────→│ Azure Firewall         │────→ wikipedia.org
Dev reporting           │ dev-eastus2            │      External FQDN
                        │ Allow outbound TCP 443 │
                        └────────────────────────┘
```

```text
DR: Azure Region Centralus

                        ┌────────────────────────┐
10.105.15.0/24 ────────→│ Azure Firewall         │────→ wikipedia.org
Dev reporting           │ dev-centralus          │      External FQDN
                        │ Allow outbound TCP 443 │
                        └────────────────────────┘
```

## Security-policy risks

- Any server later placed in 10.104.15.0/24 or 10.105.15.0/24 can reach wikipedia.org on TCP 443.
- Clients should use the firewall's DNS proxy; otherwise their answers for wikipedia.org may differ.
- TCP 443 does not enforce HTTPS; any service on that port passes.

## Tracking

```text
RITM0013525 | 2026-11-24 | dev | eastus2 | https-rprt-to-wikipedia
RITM0013525 | 2026-11-24 | dev | centralus | https-rprt-to-wikipedia
```

## Observability

**15,134 tokens · 6 tool calls · about $0.0018 (estimate) · 70 seconds**

- **Agent:** `fwagent-drafter` version 20 on `gpt-6-luna-agent` (gpt-6-luna)
- **Estimated cost:** about $0.0018 (input $0.0014 + output $0.0004)
- **Run time:** 00:10:12 to 00:11:22 UTC
- **Foundry response:** `resp_0769f1742dd2ee57006b04d5f6dc2c8197b4d76444f7ca1f23`

The cost is an estimate at gpt-6-luna list prices ($0.10 in, $0.50 out per 1M; eastus2, recorded 2026-10-15). The Azure bill is the real figure.

**This ticket**

```text
Tokens (15,134)

Input   ██████████████████████████████  14,423   95%
Output  █                                  711    5%

Tool calls (6)

locate_address_for_env_site  ■■■  3
dns_lookup_for_fqdn          ■    1
duplicate_rule_check         ■■   2
```
