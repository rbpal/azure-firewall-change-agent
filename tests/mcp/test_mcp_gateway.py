"""Gate 2 in gateway.run(), with a stand-in tool that echoes the caller it was given. Each test fails if the
gateway hands a tool the wrong caller, or calls a tool for a request that has no principal."""

import base64
import json

import pytest

import gateway

OID = "http://schemas.microsoft.com/identity/claims/objectidentifier"


@pytest.fixture(autouse=True)
def built_in_auth_on(monkeypatch):
    """App Service reports built-in auth as on, as it is on func-fwagentic-dev."""
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")


def echo(caller, arguments=None):
    """A stand-in tool: return the caller the gateway passed in."""
    return {"object_id": caller.object_id, "client_app_id": caller.client_app_id,
            "roles": list(caller.roles), "auth_type": caller.auth_type}


def test_the_gateway_passes_the_tool_the_principal_from_the_header():
    principal = {"auth_typ": "aad", "role_typ": "roles", "claims": [
        {"typ": "roles", "val": "Tools.Read"},
        {"typ": OID, "val": "obj-from-header"},
        {"typ": "azp", "val": "client-from-header"},
    ]}
    context = {"name": "code_version", "arguments": {}, "transport": {"properties": {"headers": {
        "X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(principal).encode()).decode()}}}}
    out = json.loads(gateway.run(json.dumps(context), echo))
    assert out == {"object_id": "obj-from-header", "client_app_id": "client-from-header",
                   "roles": ["Tools.Read"], "auth_type": "aad"}


def test_the_gateway_never_calls_the_tool_without_a_principal():
    called = []
    context = {"name": "code_version", "arguments": {}, "transport": {"properties": {"headers": {}}}}
    out = json.loads(gateway.run(json.dumps(context), lambda c, a=None: called.append(c)))
    assert out["error"] == "forbidden" and called == []
