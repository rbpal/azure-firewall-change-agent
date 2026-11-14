# evals

## 1. Purpose

The evaluation measures whether the drafting agent gives the right answer to an approved firewall ticket. A right answer is one of three outcomes: draft the rules the ticket approves, report that existing rules already allow it, or stop and ask the engineer, with the right reason.

It measures the agent and the model together, through the same tools the workflow uses. It does not test the workflow code; the software tests in `tests/` do that.

## 2. How it works

The runner, `run_eval.py`, runs on a laptop. For each ticket it sends the `ticket:` block to the drafter agent hosted on Azure AI Foundry. The agent calls its read-only tools on the Azure Function `func-fwagentic-dev`, which read one pinned snapshot of the network data from Blob storage. The reply comes back to the laptop and is scored there against the ticket's `expected:` block.

The agent never receives `expected:`, the answer key. It gets only the ticket and the engineer's recorded acceptance, as the workflow would give them. Scoring uses plain Python and no model, so the same reply always gets the same score.

A ticket **passes** only when all four checks pass:

1. **Outcome.** The reply's outcome word (`draft`, `already_allowed` or `stop_and_ask`) matches the label.
2. **Rule scope** (`least_privilege.py`). No rule allows more than the ticket in any field: source, destination, ports, protocol, or DNAT translation. A rule the label does not have fails. Addresses are compared by containment, hostnames and IP groups by exact name. A removal must match the labelled rules exactly.
3. **Stops** (`abstention.py`). A stop must give the labelled reason and no rules. A draft where the label stops is a **missed stop**. A stop where the label drafts is an **over-abstain**.
4. **Required tools** (`required_tools.py`). The agent must have made every call its instructions require: a location lookup for each source and destination given as a CIDR or IP group (except on a removal), the duplicate check at each labelled site, the DNAT port check for a DNAT rule, and the DNS lookup when the label lists it. A skipped call fails the ticket, even when the answer is right.

A pass is **complete** when the draft is not narrower than approved and no labelled rule is missing. Rules are matched by env-site, spoke and collection. A new rule's name is not scored.

## 3. Dataset

There are 90 requests: 58 in validation and 32 in the test split, across 44 categories. `make_requests.py` writes the tickets, the same every run.

| Split | Requests | Draft | Already allowed | Stop and ask | Purpose |
|---|---|---|---|---|---|
| `requests/validation/` | 58 | 32 | 2 | 24 | Tune and gate the agent. A definition must pass here before it may draft. |
| `requests/test/` | 32 | 23 | 2 | 7 | Held back for one final score per definition. Nothing is tuned against it. The runner refuses it without `--allow-test-split`. |

Retired numbers are listed in `make_requests.py` under `RETIRED`, with a reason, so every other number keeps its ticket.

**Who wrote and reviewed the answer keys.** The `expected:` blocks are written for this project and checked against the network data and tools. `make_requests.py` never writes them. 48 of the 90 date from the first set, of 2026-10-13, and no review record of them survives. The other 42 were added from 2026-10-18 on. The project owner approved 27 of them by number, between 2026-10-18 and 2026-10-22. The remaining 15 have no recorded by-number approval. No label carries the `review: pending` marker.

**Software tests are not LLM evaluations.** `pytest` runs the software tests in `tests/`. They check the code, including the runner and scorers, and call no model. `tests/evals/` runs the runner with two stand-in agents from `stand_in_agents.py`. `perfect` replays the labels and passes 58 of 58, which shows the scorers add no mistakes of their own. `always_stop` passes 3 of 58. Neither says anything about a model. Only a run with `--agent foundry` evaluates the LLM.

## 4. Examples

Validation and test tickets share one format, a `ticket:` block plus an `expected:` block. They differ only in purpose. An address may be a CIDR, an IP group, a hostname or a URL. In a CIDR, each of the four numbers is 0 to 255.

### Validation ticket, expected to draft: RITM0011001

The ticket blocks below are shortened. The requester, dates, approvals and assignee are left out.

```yaml
ticket:
  number: RITM0011001
  item: Firewall Change Request
  state: approved
  environments: [prod]
  dr_site_built: {prod: true}
  change_sites:
    prod: [primary, dr]
  sources:
  - {environment: prod, site: primary, cidr: 10.100.16.0/24}
  - {environment: prod, site: dr, cidr: 10.101.16.0/24}
  destination:
  - {cidr: 198.51.100.32/28}
  protocol: TCP
  ports: ['22']
  external_party: Proseware
  justification: The ledger databases in prod send files to Proseware.
```

Expected answer, never sent to the agent:

```yaml
expected:
  outcome: draft
  rules:
  - {env_site: prod-eastus2, spoke: ledg, collection: allow-ledg-network-rules, name: sftp-ledg-to-prosewareSftp,
     sources: [10.100.16.0/24], destinations: [198.51.100.32/28], ports: ['22'], protocol: TCP}
  - {env_site: prod-centralus, spoke: ledg, collection: allow-ledg-network-rules, name: sftp-ledg-to-prosewareSftp,
     sources: [10.101.16.0/24], destinations: [198.51.100.32/28], ports: ['22'], protocol: TCP}
  tools:
  - {tool: locate_address_for_env_site, address: 10.100.16.0/24}
  - {tool: locate_address_for_env_site, address: 10.101.16.0/24}
  - {tool: duplicate_rule_check, env_site: prod-eastus2}
  - {tool: duplicate_rule_check, env_site: prod-centralus}
```

Rule `005-amqps-ledg-to-prosewareMq` already links the same addresses, but on TCP 5671 only. TCP 22 is a new rule at each site, not an edit to rule 005 (STD-COLL-08).

### Test-split ticket, already allowed: RITM0012014

```yaml
ticket:
  number: RITM0012014
  item: Firewall Change Request
  state: approved
  environments: [dev]
  dr_site_built: {dev: true}
  change_sites:
    dev: [primary, dr]
  sources:
  - {environment: dev, site: primary, cidr: 10.104.16.0/24}
  - {environment: dev, site: dr, cidr: 10.105.16.0/24}
  destination:
  - {cidr: 203.0.113.64/28}
  protocol: TCP
  ports: ['443']
  external_party: Litware
  justification: The ledger databases need Litware in dev.
```

Expected answer: `already_allowed`, with no new rule. The reply names the existing `https-ledg-to-litwareFs` rule (key `001`) at `dev-eastus2` and `dev-centralus`, the rule that already allows this flow at each site.

### Intake check, not part of the LLM evaluation: an octet above 255

This is a software check, not an eval request, and it is not counted in the 90. Intake code (`workflow/intake.py`) holds the ticket for the engineer before any agent call. The source below is RITM0011041 with one octet set to 256:

```yaml
sources:
- {environment: stage, site: primary, cidr: 10.102.256.0/24}
```

Expected result: the status is `awaiting_review`, with this finding:

```text
invalid_address at sources/0/cidr: 10.102.256.0/24: each of the four numbers must be 0 to 255
```

The finding cannot be accepted as it stands. Only an engineer's edit with a valid address clears it. The address is never corrected, no agent is called, no rule is drafted and no policy file changes. `tests/workflow/test_review.py` checks this in sources and destination, in each octet position, for a second entry, for an on-prem CIDR, after an edit, and with two bad addresses at once.

## 5. Latest results

**Validation did not pass. The test split was not run for this definition.**

| Item | Value |
|---|---|
| Run | Validation split, 2026-11-14 02:04 to 03:01 UTC (2026-11-13, 9:04 to 10:01 PM US Eastern) |
| Agent | `fwagent-drafter` version 12, definition `d241077b820a1889` |
| Model | Deployment `gpt-6-luna-agent`: model `gpt-6-luna`, version `2026-09-22`, GlobalStandard, capacity 200. The definition sets no temperature or sampling values, so the service defaults apply. The reply must match a strict JSON schema. |
| Tickets and network snapshot | Commit `f22275d`, ready for drafting, 73 files checked byte for byte against Git |
| Tools | `func-fwagentic-dev`, deployed 2026-11-14 01:59 UTC from `mcp/` at commit `d25ab7d`, identical to `mcp/` at `f22275d` |
| Runner settings | `--token-budget 1500000 --pace-tokens 48000`, with defaults of at least 60 s between calls and up to 3 attempts per ticket |
| Tokens | 746,871 input and 38,917 output, over 57 calls and 254 tool calls |

| Result | Count |
|---|---|
| Attempted and scored | 57 of 58 |
| Not run | 1: RITM0011069 needs a controlled DNS answer the hosted tool cannot get |
| Passed and complete | 55 of 57 |
| Failed | 2 of 57: RITM0011035 and RITM0011064 (section 6) |
| Missed stops | 2 of 23 (the gate requires 0) |
| Too wide | 2 of 57, the same two tickets |
| Over-abstain, wrong stop reason, stop that wrote rules, skipped required tool, agent error | 0 each |
| Throttled or other infrastructure errors | 0 |

Version 12 is not in `agents/evaluated-definitions.json`, so the workflow refuses to draft with it. That file records the earlier passing definition, version 11, and its later runs. Those runs scored the earlier 100- and 102-request sets, so they are not comparable with this one.

## 6. Failures and limitations

The agent's answer is what the eval scores. The workflow's draft check is a separate code guard that runs before any policy file is written. A guard that blocks a wrong draft protects the policy files, but the agent's answer still counts as a failure.

**RITM0011064: missed stop, blocked by the draft check.** The ticket asks for AMQPS (TCP 5671) to the hostname `api.tailspin.example`. This project's Basic firewall policy cannot filter a hostname in a network rule, so the agent should stop with `non_http_to_hostname`. It drafted two network rules to the hostname instead, and called the failed DNS lookup a caution. Its recorded reply, replayed through the workflow's draft check on a clean copy of the repo at `f22275d`, was refused at both sites ("api.tailspin.example is a hostname, but the rule's protocol is TCP"). No policy file changed, and the ticket returns to the engineer. The likely cause is the order of the egress runbook. RB-01-4 says that anything other than HTTPS to a host becomes a network rule, and that a hostname which does not resolve is drafted anyway. The stop appears only later, in RB-01-6. This ticket passed on 2026-11-03 and failed on 2026-11-11 and 2026-11-13.

**RITM0011035: missed stop, not blocked by any code guard.** The ticket's fields say lab, and its justification says "Needed in dev before the dev release next week." The agent should stop with `free_text_conflict`. It drafted a lab rule and did not mention the dev wording. Replayed the same way, the draft check accepted the reply and wrote the rule into the copy's `lab-eastus2` `rprt.tfvars`. In the workflow, only the engineer's review of the draft would catch it. Its twin, RITM0011036, which names prod, stopped correctly in the same run. Version 11 passed RITM0011035 on 2026-11-03 and 2026-11-11.

**Limitations**

- A pass does not guarantee every future answer is right. The same definition gives different answers on different runs, as RITM0011064 shows.
- RITM0011069 cannot run against the hosted tools, so a DNS timeout is untested in the LLM evaluation.
- 63 of the 90 answer keys have no surviving by-number review record (section 3).
- The network data is synthetic test data, not a real estate.
- New rule names are not scored (section 8).

## 7. How to run and supporting evidence

**Prerequisites**

- `uv` with Python 3.11.
- An `az login` account that can call the Foundry project's agent, and Storage Blob Data Reader on the snapshot container (`docs/snapshots.md`).
- A `main` commit marked ready for drafting by the `sync-network` workflow. The checkout's `data/network` and `infra/envs` must match it.

```sh
# Check the scorers with the stand-in agents; no model is called
uv run --python 3.11 python -m evals.run_eval --agent perfect
uv run --python 3.11 python -m evals.run_eval --agent always_stop
# Sign in to Azure; the real run calls the hosted agent and reads the snapshot
az login
# Keep the run file outside the repository: it holds every reply and response ID
mkdir -p "$HOME/fwagent-runs"
# Replace YOUR-RESOURCE and YOUR-PROJECT with the Foundry project's endpoint
export FWAGENT_PROJECT_ENDPOINT="https://YOUR-RESOURCE.services.ai.azure.com/api/projects/YOUR-PROJECT"
# Score the hosted agent on the validation split, capped at 1.5 million tokens
uv run --python 3.11 python -m evals.run_eval --agent foundry --agent-version 12 --token-budget 1500000 --pace-tokens 48000 --out "$HOME/fwagent-runs/validation.json"
```

`--agent-version` refuses to run unless the published agent is that version. `FWAGENT_SNAPSHOT_COMMIT` pins a ready commit other than the checkout's. The test split needs `--split test --allow-test-split`. Run it once per definition, and only after that definition passes validation.

The run refuses to start when `data/network` or `infra/envs` differ from the snapshot. `--data-diff-ok` names each differing file, and `--not-run RITM…=reason` leaves out each ticket that depends on it. `--token-budget N` stops before the next ticket once N tokens are used. Every ticket left out is listed on the score sheet with its reason.

**Evidence**

- Scoring rules: `run_eval.py`, `least_privilege.py`, `abstention.py`, `required_tools.py`.
- Passing definitions: `agents/evaluated-definitions.json`. A definition is added only through a reviewed pull request, after its validation pass.
- Section 5 is copied from the run's score sheet. The per-ticket run file stays outside GitHub, because it holds every reply and the service response IDs. No sanitized per-ticket file is published yet (section 8).

## 8. Improvements for the next iteration

These are planned work, not failures. The confirmed failures are in section 6. All evidence comes from the 2026-11-13 validation run of version 12.

| Observation and evidence | Proposed improvement | Priority | Target | Success criterion |
|---|---|---|---|---|
| **DNAT port check on non-DNAT tickets.** `dnat_port_check` was called on 5 tickets with no DNAT rule: RITM0011001, 0011026, 0011035, 0011041 and 0011056. | State in the drafter instructions that the check is only for inbound DNAT tickets. | Medium | Version 13 | 0 DNAT port checks on non-DNAT tickets in the next validation run |
| **Tool calls beyond the required set.** 42 of 254 tool calls were not required by `required_tools.py`: 24 location lookups, 9 duplicate checks, 6 DNAT port checks and 3 env-site lookups. | Print calls beyond the required set on the score sheet, and review the cases. | Medium | Next runner change | The score sheet reports the count. The next run's count is at most this run's 42. |
| **Rule names differ from the labels.** 23 of 25 passed new-rule drafts used another name, such as `ssh-ledg-to-proseware` for `sftp-ledg-to-prosewareSftp`. Names are not scored. | Decide whether names should be scored. If yes, add STD-NAME-03 examples to the instructions. | Low | Version 13 decision | A recorded decision. If names are scored, at least 23 of 25 names match. |
| **Latency is not recorded.** The run took 57 minutes for 57 calls, paced at 60 s or more between starts. The time each call takes is not recorded. | Record each call's duration in the run file, and print the median and maximum. | Low | Next runner change | The score sheet shows the median and maximum call time. |
| **Token use.** The median was 13,593 tokens per ticket (minimum 11,855, maximum 22,543), mostly input. | Measure how much of the input is the fixed instructions before trying to shrink it. | Low | After version 13 | The median input per ticket is reported. Any reduction comes with no new failures. |
| **No published sanitized results.** Only the summary numbers are in this README. | Commit a sanitized per-ticket sheet per run: outcomes and mistakes, no reply text or response IDs. | Medium | Next runner change | Each run's sheet is in the repository. A test checks it holds no response IDs. |
| **Explanation clarity is not measured.** By a simple sentence count, no explanation broke the 1-to-3-sentence rule. Nothing checks clarity. | Add a review step for explanations on the failed and stopped tickets. | Low | After version 13 | A recorded review of each stop's explanation in the next run. |
