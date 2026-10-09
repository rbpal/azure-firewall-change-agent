# azure-firewall-change-agent
Agentic firewall change requests on Microsoft Foundry: agent drafting, deterministic policy gates, human approval, Terraform apply.

## Synthetic data only

Every name, address and rule in this repo is fictional. A leak gate checks every commit and push for real company data, GUIDs and email addresses. To turn it on in a fresh clone:

```sh
git config core.hooksPath .githooks
mkdir -p ~/.config/leak-gate && $EDITOR ~/.config/leak-gate/terms.txt   # one real term per line; never committed
```

If the block list is missing, the gate refuses the commit rather than letting it through.
