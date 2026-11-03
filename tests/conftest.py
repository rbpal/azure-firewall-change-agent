"""Every test runs offline: no test reaches the drafter on Foundry by accident."""

import pytest


@pytest.fixture(autouse=True)
def no_live_agent(monkeypatch):
    """Clear the Foundry endpoint, so a command without --reply refuses instead of calling a model."""
    monkeypatch.delenv("FWAGENT_PROJECT_ENDPOINT", raising=False)


OFFLINE_MAIN = "a" * 40  # the main commit the offline stand-in pretends to draft from


@pytest.fixture
def offline_main(monkeypatch):
    """Stand in for drafting from GitHub main: the repo itself is the ticket branch; no git fetch, no Azure."""
    import workflow.cli as cli
    from workflow.mainline import Draft

    def stand_in(repo, worktrees, number, ticket, review, make_agent, container, **_):
        """Build the agent through make_agent, as the real loop does, and draft once at OFFLINE_MAIN."""
        agent = make_agent(repo, OFFLINE_MAIN, {"commit": OFFLINE_MAIN, "agent": {"version": "7"}}, None)
        reply = agent(ticket, engineer_review=review)
        audit = {"attempts": [], "branch": f"agent/{number}-aaaaaaa", "worktree": str(repo),
                 "main_commit": OFFLINE_MAIN, "snapshot": OFFLINE_MAIN, "agent_version": getattr(agent, "version", "7")}
        return Draft(reply, OFFLINE_MAIN, audit["branch"], repo, audit)

    monkeypatch.setattr(cli, "draft_from_main", stand_in)
    monkeypatch.setattr(cli, "snapshot_container", lambda: None)
