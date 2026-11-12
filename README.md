# azure-firewall-change-agent
Agentic firewall change requests on Microsoft Foundry: agent drafting, deterministic policy gates, human approval, Terraform apply.

## How a request flows

![Enterprise flow: a ServiceNow ticket moves through group approval, the Foundry agent's draft, code checks, engineer review, PR review, one build and eight releases](docs/images/enterprise-flow.png)

A requester asks for a firewall change in ServiceNow, and security, network and the project approve it.
The agent drafts the rule and code checks it. An engineer and the DevOps reviewers then approve it before a release pipeline changes the firewall.

## The demo

![Demo flow: a YAML ticket, fwagent on the laptop, the same Foundry agent, a GitHub pull request and GitHub Actions build and release workflows](docs/images/demo-flow.png)

The demo runs the same agent, workflow code and checks as the enterprise flow.
One person runs it on a personal Azure subscription, so a few things change.
A YAML file stands in for the ServiceNow ticket.
You start the workflow from your laptop with `fwagent submit`.
GitHub Actions stands in for Azure DevOps, and you hold every human role.

### Status

Built and running in the demo:

- **Agent:** one Foundry agent (version 11) inside a fixed workflow. It reads the network data through five read-only MCP tools and returns a draft. It never holds write access to Azure or the repo.
- **Evaluation:** version 11 passed the validation set, 65 of 65 scored tickets, with 0 of 25 missed stops. On the held-out test set, scored once, it passed 32 of 34, with 0 of 7 missed stops and no rule wider than approved. Both misses were stops, not wrong rules. One was the agent being too cautious. The other came from a tool deployment that lagged behind `main`; it was redeployed on 2026-11-10.
- **Changes:** 18 firewall change tickets went through the flow. Each was drafted, reviewed, checked in CI (tests, Tier 1 policy checks, Terraform plans for both dev sites), merged as a pull request and applied to both dev firewall policies.

Not built yet:

- **Release workflow:** the engineer applies each merge with Terraform from the laptop. The release step in the diagram is not automated yet.
- **ServiceNow adapter:** a YAML file stands in for the ticket.
- **Prompt Shields:** designed in ADR 0002, not built.
- **Azure DevOps pipelines** for the enterprise flow.

### Trade-offs

| Bend | What it gives up | Why |
| --- | --- | --- |
| **Ticket:** a YAML file in `data/tickets/` | No real catalog item, group approval or work notes in ServiceNow. | There is no ServiceNow instance for the demo. The file adapter has the same four actions a ServiceNow adapter has: get the ticket, add a work note, change the state, close it. The workflow cannot tell which one it is using. |
| **Intake:** `fwagent` on the laptop | The Azure endpoint, queue, worker and 15-minute sweep are not built, so they stay unverified. The agent call and `terraform plan` run as you, so the audit trail shows your name, not a managed identity. | Without ServiceNow, nothing pushes tickets to an endpoint. |
| **Platform:** GitHub Actions | Per-group reviewer counts and the 72-hour approval expiry become custom code. | There is no Azure DevOps access. Environment approvals are free on a public GitHub repo. |
| **People:** you hold every role | No separation of duties in the demo run. | One person runs the demo. Every demo ticket is created with its security, network and project approvals already marked approved, and the ticket schema refuses one with an approval missing or pending. The enterprise rule, a DevOps manager plus two DevOps reviewers on each pull request, is not built in the demo. Its config, and tests with synthetic identities, are planned. |
| **Firewall:** policies only, Basic SKU | No firewall is attached, so the test ends when the rule is in the policy. Basic has no DNS proxy and no FQDN filtering in network rules. | The subscription runs on a $150 monthly credit. |

## Synthetic data only

Every name, address and rule in this repo is fictional. A leak gate checks every commit and push for real company data, GUIDs and email addresses. To turn it on in a fresh clone:

```sh
git config core.hooksPath .githooks
mkdir -p ~/.config/leak-gate && $EDITOR ~/.config/leak-gate/terms.txt   # one real term per line; never committed
```

If the block list is missing, the gate refuses the commit rather than letting it through.
