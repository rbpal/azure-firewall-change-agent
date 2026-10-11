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

Run it on a saved plan:

```bash
cd infra/envs/dev-eastus2
terraform show -json step.tfplan > "$TMPDIR/plan.json"
cd ../../..
python -m policy.tier1 "$TMPDIR/plan.json"
```

It prints one line per finding and exits 2 if anything blocks. Keep plan JSON out of the repo: it holds real resource IDs.

The checks that need a ticket (STD-COLL-03, 05) and the duplicate and removal checks (STD-COLL-07, 08) come in Step 02 Task 09.
