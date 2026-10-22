"""Every test runs offline: no test reaches the drafter on Foundry by accident."""

import pytest


@pytest.fixture(autouse=True)
def no_live_agent(monkeypatch):
    """Clear the Foundry endpoint, so a command without --reply refuses instead of calling a model."""
    monkeypatch.delenv("FWAGENT_PROJECT_ENDPOINT", raising=False)
