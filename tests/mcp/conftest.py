"""mcp/ is the Functions app root, so its modules import each other as top-level
names (auth, gateway, tools.whoami). The tests import them the same way."""

import base64
import json
import sys
from pathlib import Path

import pytest

MCP = Path(__file__).resolve().parents[2] / "mcp"
sys.path.insert(0, str(MCP))


@pytest.fixture
def allowed_context(monkeypatch):
    """Build a tool context that passes gate 2: built-in auth on, caller holds Tools.Read."""
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")
    principal = {"auth_typ": "aad", "role_typ": "roles", "claims": [{"typ": "roles", "val": "Tools.Read"}]}
    header = base64.b64encode(json.dumps(principal).encode()).decode()

    def make(arguments):
        return json.dumps({"arguments": arguments,
                           "transport": {"properties": {"headers": {"X-MS-CLIENT-PRINCIPAL": header}}}})
    return make
