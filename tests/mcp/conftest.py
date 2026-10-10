"""mcp/ is the Functions app root, so its modules import each other as top-level
names (auth, gateway, tools.whoami). The tests import them the same way."""

import sys
from pathlib import Path

MCP = Path(__file__).resolve().parents[2] / "mcp"
sys.path.insert(0, str(MCP))
