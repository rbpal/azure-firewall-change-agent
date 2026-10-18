# evals

The eval harness. Tier 2 scores the agent on the labelled requests in `requests/`. Tier 3 attacks it with red-team prompts.

- `requests/validation/`: labelled requests that prompts and thresholds are tuned against.
- `requests/test/`: labelled requests kept back for the final score. Nothing is tuned against them.

Each request is one YAML file, `validation_RITM00110xx.yaml` or `test_RITM00120xx.yaml`, with a `ticket:` block and an `expected:` label. `make_requests.py` writes the tickets: 72 requests across 17 categories, the same every run. Each ticket says which sites it changes, primary, DR or both, and the categories cover all three for adds and removals. It never writes a label and never overwrites a file; every `expected:` block is written by hand.

Two scorers read an agent reply shaped like `expected:` and need no model:

- `least_privilege.py`: fails a draft that allows more than the ticket in any field. Allowing less is reported as incomplete. A removal must match the labelled rules exactly. Hostnames and IP groups are compared by name and never expanded (STD-COLL-03).
- `abstention.py`: fails a reply that misses a stop, stops with the wrong reason, writes rules while stopping, or stops when the label proceeds.

There is no training set: the model's weights are never trained here.

## Labels pending review

A label with `review: pending` in its `expected:` block has not yet been checked by a person against the network files. The runner counts these on the score sheet ("Labels pending human review"), so a score that rests on unchecked keys says so. Delete the line once the label is checked. Twelve labels carry it today: RITM0011041 to RITM0011048 and RITM0012021 to RITM0012024.

## Versions

Scores from different versions are not comparable. Each version is fixed by a commit.

| Version | Date | Requests | Categories | Commit |
|---|---|---|---|---|
| v1 | 2026-10-13 | 60 (40 validation, 20 test) | 13 | tickets `8958eb5`, labels `bd8588b` |
| v2 | 2026-10-18 | 72 (48 validation, 24 test) | 17 | the commit that adds `change_sites` |

v1 stays readable in git, for example `git show bd8588b:evals/requests/test/test_RITM0012015.yaml`.

What changed in v2:

1. **New field.** Every ticket gained `change_sites`. The 60 v1 tickets were given primary, plus DR where DR is built, which is what v1 assumed. For 56 of them nothing else changed, so their meaning and labels are the same.
2. **Renamed.** Category `dr-answer-contradicts-sources` became `sites-contradict-addresses`. Stop reason `dr_yes_no_source` became `site_without_address`, and `dr_no_but_dr_source` became `address_for_unselected_site`. RITM0011027 changed only by this rename.
3. **Changed meaning.** RITM0011028, RITM0011029 and RITM0012015 said "DR not built" for a spoke whose DR site exists, and gave a DR source. Two stop reasons fitted. In v2 they say DR is built, select primary only, and still give a DR source, so only `address_for_unselected_site` fits.
4. **New.** Twelve requests in four new categories: add primary only with DR built, add DR only, remove primary only, remove DR only. Each has 2 validation and 1 test request.

The test split changed in v2 (RITM0012015 and four new requests). No agent, real or stand-in, has been scored on the test split under either version, so no result was tuned against it.

## What has been measured

No real model has been scored yet. The two stand-in agents in `stand_in_agents.py` check the scoring code only:

- `perfect` replays the labels. It passes 48 of 48 validation requests, which shows that the runner and scorers add no mistakes of their own. It says nothing about any model.
- `always_stop` stops on every request. It passes 3 of 48. That is a baseline, not a floor.

The first real score comes after the agent and its model are configured.
