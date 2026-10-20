# evals

The eval harness. Tier 2 scores the agent on the labelled requests in `requests/`. Tier 3 attacks it with red-team prompts.

- `requests/validation/`: labelled requests that prompts and thresholds are tuned against.
- `requests/test/`: labelled requests kept back for the final score. Nothing is tuned against them.

Each request is one YAML file, `validation_RITM00110xx.yaml` or `test_RITM00120xx.yaml`, with a `ticket:` block and an `expected:` label. `make_requests.py` writes the tickets: 71 requests across 19 categories, the same every run. Each ticket says which sites it changes, primary, DR or both, and the categories cover all three for adds and removals. A ticket asks for an IP group by name or for CIDRs, never one in place of the other (STD-COLL-03). Removals cover both: RITM0011049 removes a rule written with the CIDR the ticket gives, and RITM0011050 a rule written with the IP group the ticket names. It never writes a label and never overwrites a file; every `expected:` block is written by hand.

Two scorers read an agent reply shaped like `expected:` and need no model:

- `least_privilege.py`: fails a draft that allows more than the ticket in any field. Allowing less is reported as incomplete. A removal must match the labelled rules exactly. Hostnames and IP groups are compared by name and never expanded (STD-COLL-03).
- `abstention.py`: fails a reply that misses a stop, stops with the wrong reason, writes rules while stopping, or stops when the label proceeds.

There is no training set: the model's weights are never trained here.

## Labels pending review

A label with `review: pending` in its `expected:` block has not yet been checked by a person against the network files. The runner counts these on the score sheet ("Labels pending human review"), so a score that rests on unchecked keys says so. Delete the line once the label is checked. To list the ones still pending: `grep -l "review: pending" evals/requests/*/*.yaml`.

## Versions

Scores from different versions are not comparable. Each version is fixed by a commit.

| Version | Date | Requests | Categories | Commit |
|---|---|---|---|---|
| v1 | 2026-10-13 | 60 (40 validation, 20 test) | 13 | tickets `8958eb5`, labels `bd8588b` |
| v2 | 2026-10-18 | 72 (48 validation, 24 test) | 17 | `be7d135` |
| v3 | 2026-10-18 | 71 (47 validation, 24 test) | 19 | the commit that adds RITM0011049 and RITM0011050 |

v1 stays readable in git, for example `git show bd8588b:evals/requests/test/test_RITM0012015.yaml`.

What changed in v2:

1. **New field.** Every ticket gained `change_sites`. The 60 v1 tickets were given primary, plus DR where DR is built, which is what v1 assumed. For 56 of them nothing else changed, so their meaning and labels are the same.
2. **Renamed.** Category `dr-answer-contradicts-sources` became `sites-contradict-addresses`. Stop reason `dr_yes_no_source` became `site_without_address`, and `dr_no_but_dr_source` became `address_for_unselected_site`. RITM0011027 changed only by this rename.
3. **Changed meaning.** RITM0011028, RITM0011029 and RITM0012015 said "DR not built" for a spoke whose DR site exists, and gave a DR source. Two stop reasons fitted. In v2 they say DR is built, select primary only, and still give a DR source, so only `address_for_unselected_site` fits.
4. **New.** Twelve requests in four new categories: add primary only with DR built, add DR only, remove primary only, remove DR only. Each has 2 validation and 1 test request.

What changed in v3 (2026-10-18):

1. **Retired.** RITM0011022, RITM0011024 and RITM0011047 gave CIDRs but pointed at rules written with IP groups that each hold exactly one CIDR. Real IP groups hold many prefixes, and a ticket asks for either a group or CIDRs, so these cases do not occur. `make_requests.py` lists them in `RETIRED`: it still plans them, so every other number keeps its ticket, but never writes them.
2. **New.** RITM0011049 (`removal-cidr-source`) removes a prod DR ledg rule written as `source_addresses = ["10.101.16.0/24"]`, on a ticket that gives that CIDR. RITM0011050 (`removal-ip-group-source`) removes a prod DR ledg rule written with `ipg-ledg-prod-dr`, on a ticket that names that group.
3. **Reworded.** RITM0012022 (test, `add-dr-only`): the justification named the xfer spoke's role, "SFTP and partner file transfer", while the ticket asks for TCP 5671. It now asks for AMQPS messaging on TCP 5671 from the stage DR xfer subnet to Fourth Coffee. The structured fields and the label are unchanged. `make_requests.py` holds the new text in `REVISED_JUSTIFICATIONS`.

The test split changed in v2 (RITM0012015 and four new requests) and in v3 (the RITM0012022 wording). No agent, real or stand-in, has been scored on the test split under any version, so no result was tuned against it.

## What has been measured

No real model has been scored yet. The two stand-in agents in `stand_in_agents.py` check the scoring code only:

- `perfect` replays the labels. It passes 47 of 47 validation requests, which shows that the runner and scorers add no mistakes of their own. It says nothing about any model.
- `always_stop` stops on every request. It passes 3 of 47. That is a baseline, not a floor.

The first real score comes after the agent and its model are configured.
