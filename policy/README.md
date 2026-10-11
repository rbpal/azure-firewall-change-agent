# policy

Tier 1 checks: deterministic Python that reads one env-site's `terraform show -json` plan and returns findings. No model is involved, so the same plan always gets the same answer.

`tier1.py` runs these checks:

| Standard | Check | Result |
| --- | --- | --- |
| STD-COLL-04 | DNAT rule open to `0.0.0.0/0`, `*` or `Any`, or with no source | block |
| STD-COLL-02 | `*` or `0.0.0.0/0` in a network or application rule; wildcard FQDNs; web categories | caution |
| STD-COLL-01 | Group priority 200; DNAT 1000, network 2000, application 3000; never Deny | caution |
| STD-COLL-06 | DNAT goes to this site's hub public IP, translates inside this site, each public port once | caution |
| STD-NAME-01 to 05 | Group, collection, rule key and IP group names; indexes from 001 with no gaps; no ticket numbers | caution |
| STD-COLL-07 | A rule the plan adds is already allowed by an existing rule (`duplicate` or `covers`), asked of `duplicate_rule_check`, the agent's own tool | caution |
| STD-COLL-08 | Existing rules stay unchanged and in order; new rules go at the end; deleting a rule is fine | caution |
| SERVICE-TAG | An address that is not an IP, range, CIDR or `*` must be in `service_tags.txt`, and a regional tag must match the policy's region | caution |

Run it on a saved plan:

```bash
cd infra/envs/dev-eastus2
terraform show -json step.tfplan > "$TMPDIR/plan.json"
cd ../../..
python -m policy.tier1 "$TMPDIR/plan.json"
```

It prints one line per finding and exits 2 if anything blocks. Keep plan JSON out of the repo: it holds real resource IDs.

STD-COLL-07 and 08 read `resource_changes` in the plan, so they only fire on rules this plan adds or changes. A plan with no changes gives neither.

`service_tags.txt` is the list of Azure service tag names from `az network list-service-tags`. Refresh it when Azure adds tags; an unknown tag is only a caution.

The checks that need a ticket (STD-COLL-03, 05) come later, with the ticket workflow.
