# azure-firewall-change-agent
Agentic firewall change requests on Microsoft Foundry: agent drafting, deterministic policy gates, human approval, Terraform apply.

## Problem

Turning an approved firewall change request into a correct Azure Firewall change is slow, manual work. A large organisation can handle hundreds or thousands of these requests a month, depending on how much it runs in the cloud. For each one, an engineer finds where the source and destination addresses belong, checks whether access already exists, and writes rules into the right Terraform files for the primary and disaster recovery (DR) sites.

Mistakes are costly in a regulated environment. An overly broad rule grants unapproved access. A missed site leaves primary and DR out of step.

This project has an AI agent investigate each request and draft the rules. Code checks the draft, and engineers approve every step.

## Scope

In scope:

- **Requests:** approved firewall change requests and rule removals. Each ticket selects environments (lab, dev, stage, prod) and sites (primary, DR).
- **Firewall estate:** eight environment-sites in Virtual WAN secured hubs, East US 2 (primary) and Central US (DR), each with its own Terraform folder in `infra/envs/`. Each spoke landing zone has its own rule collection group file, such as `sett.tfvars`.
- **Rule types:** network rules (TCP, UDP, ICMP, Any), application rules (HTTP, HTTPS) and DNAT rules.
- **Destinations:** IP addresses, CIDR ranges, IP groups and FQDNs. A network rule to an FQDN is resolved through DNS to IPv4 addresses.
- **Agent work:** one Foundry agent drafts rules that follow the project's security standards. Five read-only tools locate addresses, check for existing access, check DNAT ports, look up DNS and resolve environment-sites. When a ticket is ambiguous or inconsistent, the agent stops and asks the engineer.
- **Code checks:** the draft is compared with the ticket. Rules wider than approved, attempts to bypass the process and conflicting free text are stopped before any file is written.
- **Pull request:** the description names the ticket, environments, sites, Terraform files, rule collections and every rule added, changed or removed. It adds a packet-flow diagram, security-policy risks, the FQDN and its resolved addresses, an AI-assistance notice, tracking details, and the agent version, tokens, tool calls, runtime and estimated cost.
- **Delivery:** CI checks (tests, Tier 1 policy checks, Terraform plans), pull request review and a Terraform apply from `main`.
- **Observability:** each agent run is traced to Log Analytics. A workbook shows the run, every tool call, its arguments and answers, and token counts.

Out of scope for the demo:

- **Deploying beyond dev:** only the two dev firewall policies exist in Azure and are applied. Lab, stage and prod are Terraform folders the agent drafts into, not deployed policies.
- **Cost and correctness in Azure:** cost is estimated from tokens locally, and review outcomes stay in local records.

The demo's other limits are in [Trade-offs](#trade-offs): the YAML ticket in place of ServiceNow, intake on the laptop, GitHub Actions in place of Azure DevOps, one person in every role and no firewall attached.

## The demo

![Demo flow in nine steps: a YAML ticket and demo branch on the laptop, sync and the Foundry agent in Azure, a GitHub pull request, review and merge, an apply from main to the dev firewall policies, then archive](docs/images/demo-flow-steps.png)

The demo runs the same agent, workflow code and checks as the enterprise flow, on a personal Azure subscription. You run each step from your laptop with local demo scripts, helped by a coding assistant in VS Code. Step 4 sends the ticket to the Foundry agent.

### Walkthrough: one network ticket

Each step shows what happens to ticket RITM0013525 and the script that does it.

#### Step 1: Ticket

RITM0013525: the reporting batch servers in dev (`10.104.15.0/24` in East US 2, `10.105.15.0/24` in Central US) read public reference articles from `www.wikipedia.org`, on HTTPS 443. Approved. `step_01_01_make_demo_network_ticket.py` writes it as YAML to `01-waiting/`, where it waits for step 2. Edit the values at the top of the script, then run it. It writes only if the number is new, both sources are subnets in the address plan at their dev site, and intake finds nothing blocking.

![Ticket RITM0013525 as YAML: rprt dev sources 10.104.15.0/24 and 10.105.15.0/24 to www.wikipedia.org on HTTPS 443, approved by security, network and project](docs/images/demo-step-01-ticket-ritm0013525.png)

#### Step 2: Demo branch

`step_02_create_branch_for_demo_ticket.py` creates the local branch `demo/RITM0013525` from GitHub `main`. It stops if the ticket is missing or the working tree has changes. It never commits or pushes. Set `TICKET_NUMBER` at the top, then run it.

![Step 2 output: ticket found, working tree clean, branch demo/RITM0013525 created at origin/main de92f36ca73b, nothing pushed](docs/images/demo-step-02-branch-ritm0013525-output.png)

#### Step 3: Verify and sync

`step_03_verify_and_sync_main_to_azure_storage.py` runs six checks that Azure matches GitHub `main`: the snapshot of network data in Azure Storage, its ready marker, the agent version and the tool server's code. All six passed, so no sync was needed. If one fails, it asks before starting the `sync-network` workflow.

*Why: the agent's tools read the network data and current rules from Azure Storage, not GitHub. If someone else merged to `main` and the sync has not run yet, Azure holds an older copy. This step confirms Azure matches GitHub `main`, so the tools return accurate results.*

![Step 3 output: six checks passed for origin/main de92f36ca73b, 73 files in Git and Azure, agent fwagent-drafter v20 with definition 412d5c398cd04be8, tool code hash 212dcb2abf50, already synced and ready for drafting](docs/images/demo-step-03-verify-ritm0013525-output.png)

#### Step 4: Accept and send to the agent

`step_04_verify_and_submit_to_foundry.py` checks the ticket, reruns step 3's six checks, shows what it will send and asks once. After `y` it records the engineer's acceptance of this exact ticket version and sends it to the Foundry agent once. The agent drafted one rule per site, `https-rprt-to-wikipedia`: TCP 443 from that site's reporting subnet to `wikipedia.org`. It removed the ticket's `www.`, and the rule names the FQDN, not its addresses. It used 14,423 input and 711 output tokens and 6 tool calls. The reply is saved in `02-submit/`; no rule file is written yet.

*Why: the engineer approves the exact ticket before any model call, and the agent's tools only read. It returns a JSON draft, never files.*

![Step 4 output: ticket RITM0013525 accepted and sent once to fwagent-drafter v20; draft rule https-rprt-to-wikipedia at dev-eastus2 and dev-centralus, TCP 443 to wikipedia.org; 14423 input and 711 output tokens, 6 tool calls](docs/images/demo-step-04-submit-ritm0013525-output.png)

#### Step 5: Write the dev rule files

`step_05_write_draft_rules_to_dev_tfvars.py` writes the saved draft into `rprt.tfvars` at both dev sites, on the demo branch. It uses the workflow's own writer, so the same scope, address, protocol and port checks run again. It shows the diff and writes only after `y`. It commits nothing.

*Why: rule files change only through code the engineer reviews, never by the agent.*

![Step 5 output: rule https-rprt-to-wikipedia added to rprt.tfvars at dev-eastus2 (key 011) and dev-centralus (key 010), TCP 443 to destination_fqdns wikipedia.org, nothing committed](docs/images/demo-step-05-write-ritm0013525-output.png)

#### Step 6: Pull request

The two rule files are committed on `demo/RITM0013525`, pushed, and opened as [PR #73](https://github.com/rbpal/azure-firewall-change-agent/pull/73). The description comes from the saved records: rule keys, the DNS lookup, packet flow per site, three policy risks, and the agent's tokens, tool calls and estimated cost. CI then plans both dev sites and runs the policy checks and tests.

*Why: a person reviews and merges every rule change; the agent never pushes or merges.*

<details>
<summary>PR #73 description (Markdown)</summary>

````markdown
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
````

</details>

#### Step 7: Merge

PR #73 is merged into `main` at `d033dc8`, the commit CI tested. All 5 CI checks on the PR passed:

1. **validate:** `terraform fmt` found no formatting changes. `terraform validate` passed on all 9 Terraform roots. No Azure sign-in is needed.
2. **plan (dev-eastus2):** signs in to Azure with its own plan identity and first proves that identity cannot read another step's state file. The plan is `0 to add, 1 to change, 0 to destroy`: the `rprt` rule collection group, updated in place. The Tier 1 policy checks then read that plan: 2 cautions, 0 blocking. Both cautions are existing `*.cnn.com` and `*.google.com` rules in another app's file, not this change.
3. **plan (dev-centralus):** the same checks on the DR site, with the same results.
4. **pytest (push):** the full test suite on the branch: 2,907 passed, 3 skipped. It then mutation-tests the eval scorers: 45 of 45 planted bugs caught.
5. **pytest (pull request):** the same suite and mutation test on the PR merged with `main`, with the same results.

The demo branch is deleted. Merging changes no firewall; the rules reach Azure only when the apply runs.

*Why: the merge records the approved rule in `main`; the apply is a separate, deliberate step.*

![Step 7 output: PR #73 checks plan dev-centralus, plan dev-eastus2, two pytest runs and validate all pass; merged 2026-11-24 03:33 UTC, tested head d033dc8, merge commit dcd2573](docs/images/demo-step-07-merge-ritm0013525-output.png)

#### Step 8: Apply to both dev firewalls

Terraform planned each dev site from `main` and saved the plan: `0 to add, 1 to change, 0 to destroy`. The change adds one rule to the `rprt` rule collection group and removes nothing. After review, each saved plan was applied, primary first. A new plan at each site then showed no changes, so Azure matches `main`.

*Why: the engineer reviews the exact plan, and only that plan is applied.*

The portal shows `https-rprt-to-wikipedia` live at both sites: TCP 443 to `wikipedia.org`. The `https-sett-to-wikipedia` row below it is an older rule to the IP address.

![Step 8, dev-eastus2: afwp-hub-dev-eastus2 network rules filtered to wikipedia; https-rprt-to-wikipedia in allow-rprt-network-rules, source 10.104.15.0/24, TCP 443, destination wikipedia.org, Allow](docs/images/demo-step-08-portal-dev-eastus2-ritm0013525.png)

![Step 8, dev-centralus: afwp-hub-dev-centralus network rules filtered to wikipedia; https-rprt-to-wikipedia in allow-rprt-network-rules, source 10.105.15.0/24, TCP 443, destination wikipedia.org, Allow](docs/images/demo-step-08-portal-dev-centralus-ritm0013525.png)

#### Step 9: Archive

`step_09_archive_ticket.py` first checks on GitHub that PR #73 is merged. It moves the ticket, the agent's reply, the status file and the PR description into one numbered folder: `04-archive/024-2026-11-24-RITM0013525-rprt-to-wikipedia-tcp443/`. It then lists the leftovers and removes them after `y`: the agent's register entry, its worktree and its local branch.

*Why: a merged and applied ticket keeps its records in one place. A leftover register entry would block step 4 for the next ticket.*

![Step 9 output: RITM0013525's 4 files moved to archive folder 024; register entry, worktree and local branch agent/RITM0013525-de92f36 removed after y; nothing left over](docs/images/demo-step-09-archive-ritm0013525-output.png)

### Cost

Estimates for the demo, checked against Microsoft pricing pages on 2026-11-17. Every resource uses its free tier or lowest plan, and the resource group has a $100 budget alert. That alert warns; it does not stop spending.

| Item | Plan or tier | Estimated monthly cost |
|---|---|---|
| Firewall policies (2, dev primary and DR) and IP groups (13) | Basic policy, no firewall attached | $0. A policy with zero or one firewall association is free. |
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

So one request that adds a rule to every environment, including DR, costs about a third of a cent in tokens. At 100 requests a month, for example, that is about $0.30. The Azure side adds nothing per request: the tool calls fit in the Function app's free grant, and in this demo the firewall policies are free because no firewall is attached. In a real estate, the cost that matters is the Azure Firewall instances themselves, billed per hour whether or not a rule changes, and the engineer's review time.

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
- Tool results are not screened for injected instructions yet. This will be fixed in the next iteration, as part of the optimization work (see Optimization below). Until then the risk is limited: the network data and runbooks reach `main` only through a reviewed pull request, a draft's resolved addresses must match the DNS tool's answer exactly (`workflow/scope.py`), and the draft check below still applies.
- Before any rule is written, code checks the draft against the ticket (`workflow/scope.py`). A rule wider than approved is refused.
- Evaluation tickets test injection, including validation tickets RITM0011037 to 0011040. All passed on version 17. The held-back test split has two more, which passed on the version 16 rerun.

An engineer still accepts every ticket, approves every draft and reviews every pull request. The remaining security work is listed under Optimization below.

### Observability

Every agent run is traced to Log Analytics, and an Azure Monitor workbook reads the traces. It has seven tabs. The figures below cover the 7 days to 2026-11-19.

**Overview.** Shows how many runs Foundry received, how many succeeded, how long they took and what the agent answered. There were 345 runs, and 99.4% succeeded. The agent returned 208 drafts, 120 stops to ask and 15 already-allowed answers.

Run time is shown as percentiles; "p" means percentile.

- **p50 (median):** half of the runs finished faster than this, and half slower. It is 17.5 s, so a typical run takes about 17.5 seconds.
- **p95:** 95% of runs finished faster than this, and the slowest 5% took longer. It is 61.5 s, so about 1 run in 20 takes over a minute.

The p50 shows the normal case. The p95 shows how bad the slow cases get.

![Workbook Overview tab: 345 runs, 343 succeeded, 2 failed, 99.4% success, p50 17.5 s, p95 61.5 s, and reply outcomes draft, stop_and_ask, already_allowed and unknown](docs/images/workbook-overview.png)

**Tokens and cost.** Shows tokens per ticket and per day. Input tokens match the runner's own count. Output and cached tokens are partial, so the cost estimate uses the runner's counts.

![Workbook Tokens and cost tab: tokens per ticket with complete input tokens and partial output and cached tokens, and input tokens per day](docs/images/workbook-tokens-and-cost.png)

**Tools.** Shows each MCP tool's call count, p50 and p95 time, and errors. It also shows how each Function App request was linked to its tool call: exactly, or by name and time.

![Workbook Tools tab: calls, p50, p95, failed spans and returned errors for the five MCP tools, and tool-server requests split into exact and inferred links](docs/images/workbook-tools.png)

**Ticket drill-down.** Type a ticket number and select a run to see its timeline. Each tool call appears twice, once as Foundry asking for it and once as the Function App running it, with its arguments and answer.

![Workbook Ticket drill-down for RITM0013522: one draft run on agent version 17 taking 56.4 s, and its execution timeline of tool invocations and executions with arguments](docs/images/workbook-ticket-drill-down.png)

**Trends.** A row for the selected range sits above three daily charts. Its failure rate is total failed runs divided by total runs, and its p50 and p95 come from every run, not from daily figures. The charts show runs and failed runs, the failure rate, and p50 and p95 run time per day. They track volume, speed and reliability, not whether drafts became more correct.

![Workbook Trends tab: the selected-range row with 345 runs, 2 failed, 0.6% failure rate, p50 17.5 s and p95 61.5 s, then daily charts for runs and failed runs, failure rate, and p50 and p95 run time](docs/images/workbook-trends.png)

**Configuration.** Lists the agent versions seen in Foundry traces, with run counts and first and last seen. Version 17 has 156 runs since 2026-11-15. A check against the approved baseline waits for the next iteration's records.

![Workbook Configuration tab: agent versions 17, 16, 15, 14 and 12 with runs, first seen and last seen, and a notice that the drift check awaits data](docs/images/workbook-configuration.png)

**Platform health.** Shows the tool server's storage warnings and host stops per day, and Log Analytics ingestion against the 160 MB daily cap. The busiest day, 2026-11-14, used 61.4 MB, 38.4% of the cap.

![Workbook Platform health tab: tool-server storage warnings and host stops per day, and billable ingestion per day against the 160 MB daily cap](docs/images/workbook-platform-health.png)

Cost, correctness and workflow events are not in the workbook yet. The next iteration adds them; see [Status and Pending Optimization](#status-and-pending-optimization), item 7.

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

## Status and Pending Optimization

- **Evaluation:** agent version 17 passed all 60 validation tickets across two runs (56 on 2026-11-15, 4 on 2026-11-18). It then ran the test split once on 2026-11-19: 32 of 32 passed and complete, with 0 of 7 missed stops. Earlier versions were scored on the same test tickets, so this is a regression check, not unbiased held-out evidence. Details are in `evals/README.md`.

The work below is left for the next iterations. Each item is known and planned, not ignored.

1. **Tool-result screening.** Screen tool answers, including DNS answers and text fields such as `holds`, for instructions that try to steer the agent.
2. **Prompt Shields.** Screen the ticket text before the agent runs.
3. **Token limit per request.** Stop a request that uses more than a set number of tokens.
4. **Private network access to the tools.** Move the MCP tools behind a private endpoint in the enterprise design.
5. **Threat model status.** Update `docs/threat-model.md`, where several measures that are now built still say "Planned".
6. **Release pipeline.** Replace the demo's apply from VS Code with a release workflow that applies `main` per environment-site.
7. **Observability records.** Upload the laptop's run records to two new Log Analytics tables, so the workbook can show cost, correctness and workflow events.
   - `FwAgentAttempt_CL`, one row per agent run:
     - **Which run:** ticket, run ID, attempt number, start and end time.
     - **What happened:** answered, error or not sent, and the reply (draft, already allowed, stop and ask).
     - **Tokens:** input, cached, output and reasoning, taken from Foundry's own response. These are the complete counts the workbook lacks today.
     - **Eval verdict:** passed or incorrect, plus the scorer's mistake codes. This covers evaluation runs only; demo tickets get "not applicable".
     - **What it ran on:** agent version, definition hash, tool code hash and data snapshot commit.
   - `FwAgentWorkflowEvent_CL`, workflow steps after the draft: the rules written into the tfvars files and the Tier 1 policy check in CI. Each is marked succeeded, refused or failed, per environment-site.

   Prompts, replies, labels and test-split answers are never sent. With these rows, the workbook shows:
   - **Cost:** complete token counts multiplied by a dated price list. This is still an estimate; the real bill stays in Azure Cost Management.
   - **Correctness:** pass and fail rates for evaluation runs.
   - **Drift:** whether each run used the approved agent version and tools.
   - **Workflow:** whether drafts were written and passed the Tier 1 check.

   The engineer's review decision and the Terraform plan and apply are not included. They stay in the archive evidence files.
