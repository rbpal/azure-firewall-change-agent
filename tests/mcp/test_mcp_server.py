"""Structure rules for mcp/. These read the source, so they need no Azure
Functions packages, and they fail if a tool skips gate 2."""

import ast
import json
from pathlib import Path

import pytest

MCP = Path(__file__).resolve().parents[2] / "mcp"


def tool_functions():
    tree = ast.parse((MCP / "function_app.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                if isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "mcp_tool_trigger":
                    yield node, d


def test_at_least_one_tool_is_registered():
    assert list(tool_functions())


@pytest.mark.parametrize("fn,deco", list(tool_functions()), ids=lambda x: getattr(x, "name", ""))
def test_every_tool_returns_through_the_gateway(fn, deco):
    """The body must be exactly `return run(context, ...)`, so no tool can do work before gate 2."""
    assert len(fn.body) == 1 and isinstance(fn.body[0], ast.Return), f"{fn.name} must only return run(...)"
    call = fn.body[0].value
    assert isinstance(call, ast.Call) and getattr(call.func, "id", "") == "run", f"{fn.name} must call run()"
    arg_name = next(k.value.value for k in deco.keywords if k.arg == "arg_name")
    assert isinstance(call.args[0], ast.Name) and call.args[0].id == arg_name


def test_tool_names_are_unique():
    names = [next(k.value.value for k in d.keywords if k.arg == "tool_name") for _, d in tool_functions()]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("path", ["auth.py", "gateway.py", "errors.py", "estate.py", *[str(p.relative_to(MCP)) for p in (MCP / "tools").glob("*.py")]])
def test_logic_does_not_import_azure_functions(path):
    tree = ast.parse((MCP / path).read_text())
    for node in ast.walk(tree):
        names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        assert not any(n.startswith("azure.functions") for n in names), f"{path} imports azure.functions"


def test_host_json_makes_built_in_auth_the_only_door():
    host = json.loads((MCP / "host.json").read_text())
    assert host["extensions"]["mcp"]["system"]["webhookAuthorizationLevel"] == "Anonymous"
    assert host["extensionBundle"]["version"].startswith("[4.")


def test_requirements_pin_the_mcp_capable_library():
    req = (MCP / "requirements.txt").read_text()
    assert "azure-functions>=1.24.0" in req
