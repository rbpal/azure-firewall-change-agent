# evals

The eval harness. Tier 2 scores the agent on the labelled requests in `requests/`. Tier 3 attacks it with red-team prompts.

- `requests/validation/`: labelled requests that prompts and thresholds are tuned against.
- `requests/test/`: labelled requests kept back for the final score. Nothing is tuned against them.

Each request is one YAML file, `validation_RITM00110xx.yaml` or `test_RITM00120xx.yaml`, with a `ticket:` block and an `expected:` label. `make_requests.py` writes the tickets: 60 requests across 13 categories, the same every run. It never writes a label and never overwrites a file; every `expected:` block is written by hand.

There is no training set: the model's weights are never trained here.
