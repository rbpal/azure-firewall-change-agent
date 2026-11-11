"""Every test runs offline: no test reaches the drafter on Foundry by accident."""

import pytest


@pytest.fixture(autouse=True)
def no_live_agent(monkeypatch):
    """Clear the Foundry endpoint, so a command without --reply refuses instead of calling a model."""
    monkeypatch.delenv("FWAGENT_PROJECT_ENDPOINT", raising=False)
    import workflow.lifecycle as lifecycle
    monkeypatch.setattr(lifecycle, "whoami", lambda gh=None: "tester")  # no test asks GitHub who you are
    monkeypatch.setattr(lifecycle, "run_gh", lambda *a: "[]")  # no test reaches GitHub: no pull requests
    monkeypatch.setattr(lifecycle, "azure_synced",  # no test reads Azure: the merge counts as synced
                        lambda repo, commit, container=None: {"commit": commit, "files_checked": 0,
                                                              "bytes_match_git": True, "agent_version": "test"})
    import workflow.tool_server as tool_server

    def no_tool_server(*_a, **_k):
        """Fail any test that would call the deployed tool server."""
        raise AssertionError("a test tried to reach the deployed tool server")
    monkeypatch.setattr(tool_server, "deployed_code", no_tool_server)
    monkeypatch.setattr(tool_server, "check",  # no test reaches the tool server: its code counts as main's
                        lambda repo, commit, reader=None: {"code_sha256": "test", "files": 0})


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
