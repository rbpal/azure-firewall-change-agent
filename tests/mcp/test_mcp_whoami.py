"""The whoami tool, on its own and behind the gateway. Each test fails if
whoami drops, renames or invents a field."""

import base64
import json

import pytest

import gateway
from auth import Caller
from tools.whoami import whoami

OID = "http://schemas.microsoft.com/identity/claims/objectidentifier"


@pytest.fixture(autouse=True)
def built_in_auth_on(monkeypatch):
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")


def test_whoami_reports_the_caller():
    caller = Caller(object_id="obj-1", client_app_id="client-1", roles=("Tools.Read",), auth_type="aad")
    assert whoami(caller) == {
        "object_id": "obj-1",
        "client_app_id": "client-1",
        "roles": ["Tools.Read"],
        "auth_type": "aad",
    }


def test_whoami_returns_only_these_four_fields():
    """Nothing else, so no header, token or claim can leak through it."""
    caller = Caller(object_id="o", client_app_id="c", roles=(), auth_type="aad")
    assert set(whoami(caller)) == {"object_id", "client_app_id", "roles", "auth_type"}


def test_whoami_output_is_json_serialisable():
    caller = Caller(object_id=None, client_app_id=None, roles=("Tools.Read",), auth_type=None)
    json.dumps(whoami(caller))


def test_whoami_through_the_gateway_reads_the_real_principal():
    principal = {"auth_typ": "aad", "role_typ": "roles", "claims": [
        {"typ": "roles", "val": "Tools.Read"},
        {"typ": OID, "val": "obj-from-header"},
        {"typ": "azp", "val": "client-from-header"},
    ]}
    context = {"name": "whoami", "arguments": {}, "transport": {"properties": {"headers": {
        "X-MS-CLIENT-PRINCIPAL": base64.b64encode(json.dumps(principal).encode()).decode()}}}}
    out = json.loads(gateway.run(json.dumps(context), whoami))
    assert out == {"object_id": "obj-from-header", "client_app_id": "client-from-header",
                   "roles": ["Tools.Read"], "auth_type": "aad"}


def test_whoami_through_the_gateway_refuses_without_principal():
    context = {"name": "whoami", "arguments": {}, "transport": {"properties": {"headers": {}}}}
    out = json.loads(gateway.run(json.dumps(context), whoami))
    assert out["error"] == "forbidden" and "object_id" not in out
