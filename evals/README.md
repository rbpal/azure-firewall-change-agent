# evals

The eval harness. Tier 2 scores the agent on the labelled requests in `requests/`. Tier 3 attacks it with red-team prompts.

- `requests/validation/`: labelled requests that prompts and thresholds are tuned against.
- `requests/test/`: labelled requests kept back for the final score. Nothing is tuned against them.

There is no training set: the model's weights are never trained here.
