# azure-firewall-change-agent
Agentic firewall change requests on Microsoft Foundry: agent drafting, deterministic policy gates, human approval, Terraform apply.

## Problem

Turning an approved firewall change request into an accurate Azure Firewall change is a slow, manual process. In a financial organisation handling around 100 Azure Firewall tickets each month, engineers must identify where the source and destination addresses belong, check whether access already exists, and write rules into the correct Terraform files for the requested primary and disaster recovery (DR) sites.

This demo models eight environment-site combinations across paired Azure regions, using Azure Virtual WAN secured hubs. Each spoke landing zone has a separate Terraform variables (.tfvars) file for its rule collection group. In a highly regulated financial environment, errors can have serious consequences: an overly broad rule can grant unapproved access, while a missed site can leave primary and DR configurations inconsistent.

The demo uses locally created tickets to represent approved firewall requests. An AI agent investigates each request and drafts the required rules, supported by code-based validation. It checks address ownership and existing rules, follows the project's security standards, and asks the DevOps engineer for clarification when a request is ambiguous or inconsistent. For supported FQDN destinations, it performs a DNS lookup and includes the requested hostname or URL and resolved IP addresses in the PR description for traceability and review.

The project also generates a PR description identifying the ticket, affected environments and sites, exact Terraform files, rule collections, and rules added, changed or removed. Packet-flow diagrams illustrate the proposed access, while a risk analysis highlights concerns such as broad address ranges and the limits of port-based filtering.

Each PR includes an AI-assistance notice, ticket-tracking details, and execution metrics covering the agent version, token usage, tool calls, runtime and estimated cost. The change then follows the approval process through PR review, a single build and a release approval gate.

A future integration with ServiceNow could replace the locally created demo tickets with approved requests from an enterprise ticketing workflow.

## The demo

![Demo flow in eleven steps: a YAML ticket and demo branch on the laptop, sync and the Foundry agent in Azure, then a GitHub pull request, review and merge, and an apply from main to the dev firewall policies](docs/images/demo-flow-steps.png)

The demo runs the same agent, workflow code and checks as the enterprise flow. A DevOps engineer runs it on a personal Azure subscription, so a few things change:

- A YAML file stands in for the ServiceNow ticket.
- You run each step from your laptop with the scripts in `evals/raj-demo/00-script`, helped by a coding assistant in VS Code. Step 4 sends the ticket to the Foundry agent.
- GitHub Actions stands in for Azure DevOps for the pull request checks.
- For the demo only, Terraform applies main to the dev firewall policies from VS Code. The enterprise flow uses a release pipeline.
- You hold every human role at the four gates: accept the ticket, write the draft, review and merge, and apply.

### Cost

Estimates for the demo, checked against Microsoft pricing pages on 2026-11-17. Every resource uses its free tier or lowest plan, and the resource group has a $100 budget alert. That alert warns; it does not stop spending.

| Item | Plan or tier | Estimated monthly cost |
|---|---|---|
| Firewall policies (8) and IP groups | Basic policy, no firewall attached | $0. A policy with zero or one firewall association is free. |
| Function app (MCP tools) | Flex Consumption (FC1), 512 MB, no always-ready instances | $0 within the free grant of 250,000 executions and 100,000 GB-s a month |
| Storage account | Standard LRS | Under $0.10. It holds the function package and a few KB per network snapshot. |
| Log Analytics and Application Insights | Pay-as-you-go, daily cap 0.16 GB each | $0 within the free 5 GB a month per billing account |
| Foundry account and project | S0 | $0 for the resources. The model is billed per token. |
| Managed identities, Entra apps, federated credentials, MCP connection | n/a | $0 |

**LLM tokens.** The agent runs on `gpt-6-luna` (Global Standard, eastus2) at $0.10 per million input tokens and $0.50 per million output tokens. One demo ticket uses about 14,000 tokens, about $0.002. Every evaluation and live run so far used 2,643,604 input and 136,343 output tokens, about $0.33. Each PR description reports its own tokens and estimated cost.

**Cost per request (approximations).** The agent makes one model call per ticket. The tokens grow a little with each site, because it checks addresses and existing rules at every environment-site it drafts for.

| Request | Evidence | Tokens | Tool calls | LLM cost |
|---|---|---|---|---|
| Dev primary and DR (2 environment-sites) | 15 demo PRs, RITM0013501–0013515 | 13,482–15,184 | 5–7 | $0.0016–$0.0021 |
| 4 environment-sites | 2 evaluation tickets, version 17 | about 17,200 | 11 | about $0.0023 |
| All four environments, primary (eastus2) and DR (centralus): 8 environment-sites | 1 evaluation ticket, version 17 | 19,131 | 17 | about $0.0027 |

So one request that adds a rule to every environment, including DR, costs about a third of a cent in tokens. At about 100 requests a month, that is about $0.30. The Azure side adds nothing per request: the tool calls fit in the Function app's free grant, and in this demo the firewall policies are free because no firewall is attached. In a real estate, the cost that matters is the Azure Firewall instances themselves, billed per hour whether or not a rule changes, and the engineer's review time.

**Coding assistant.** A coding assistant in VS Code helps run the demo steps. It is a flat monthly subscription billed outside Azure, so it is not included above.

Prices change and vary by region. Microsoft's own page shows the model rates only as placeholders; the token rates above come from third-party price trackers and match the rate recorded in `infra/07-foundry/deployments.tfvars` on 2026-10-15.

### Security

Security has two parts: who can sign in and act, and what the agent is allowed to believe.

**1. Entra ID authentication.** Every caller signs in with Entra ID, and no service holds a stored secret.

- The agent never has write access to Azure or the repo (ADR 0002). Only the pipeline changes the firewall.
- The MCP tools only read. Each call must carry an Entra token for the tools' app, with the `Tools.Read` app role. Three identities hold it: the Foundry agent's managed identity, the sync job's identity and, for the demo only, the person testing the tools.
- GitHub Actions signs in through federated credentials. The sync identity works only from `main`. The plan-gate identity works only for pull requests. A fork carries a different subject and is refused.
- The sync identity can deploy only the one function app (Website Contributor, scoped to that app).
- Terraform state uses Entra sign-in only, with shared access keys turned off.

**2. Prompt injection and tool results.** The ticket's structured fields are the approval. Its free text is untrusted.

- Text that asks to skip the engineer review, an approval or a required check is caught by code (`workflow/bypass.py`), not only by the agent. That finding can only be cleared by editing the ticket.
- Planted instructions that widen addresses, add ports or request extra flows are ignored. Free text that asks for traffic in an environment, site or location the ticket did not select stops the ticket with `free_text_conflict`.
- The agent takes facts from its tools, not from the text. The tools read one pinned snapshot of `main`, checked by hash before every request.
- Tool results are not screened for injected instructions. No guard reads a tool's answer for text that tries to steer the agent. The risk is limited, not removed: the network data and runbooks reach `main` only through a reviewed pull request, a draft's resolved addresses must match the DNS tool's answer exactly (`workflow/scope.py`), and the draft check below still applies.
- Before any rule is written, code checks the draft against the ticket (`workflow/scope.py`). A rule wider than approved is refused.
- Six evaluation tickets test injection: RITM0011037 to 0011040, RITM0012019 and RITM0012020. All passed on version 17 or on the version 16 test-split rerun.

An engineer still accepts every ticket, approves every draft and reviews every pull request. Planned, not built: Prompt Shields screening before the agent runs, a token limit per request, and private network access to the tools.

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

## How a request flows

![Enterprise flow: a ServiceNow ticket moves through group approval, the Foundry agent's draft, code checks, engineer review, PR review, one build and eight releases](docs/images/enterprise-flow.png)

A requester asks for a firewall change in ServiceNow, and security, network and the project approve it.
The agent drafts the rule and code checks it. An engineer and the DevOps reviewers then approve it before a release pipeline changes the firewall.

## Synthetic data only

Every name, address and rule in this repo is fictional. A leak gate checks every commit and push for real company data, GUIDs and email addresses. To turn it on in a fresh clone:

```sh
git config core.hooksPath .githooks
mkdir -p ~/.config/leak-gate && $EDITOR ~/.config/leak-gate/terms.txt   # one real term per line; never committed
```

If the block list is missing, the gate refuses the commit rather than letting it through.
