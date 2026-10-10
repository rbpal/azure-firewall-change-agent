"""Gate 2. Every refusal here must be able to fail: each test breaks if the
check it guards is removed or loosened."""

import base64
import json

import pytest

import auth
import gateway
from auth import Unauthorized, require_role

OID = "http://schemas.microsoft.com/identity/claims/objectidentifier"


@pytest.fixture(autouse=True)
def built_in_auth_on(monkeypatch):
    """App Service sets this when built-in auth is enabled. Tests that need it
    off remove it themselves."""
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")


def principal(roles=("Tools.Read",), role_typ="roles", extra=()):
    claims = [{"typ": role_typ, "val": r} for r in roles]
    claims += [{"typ": OID, "val": "obj-1"}, {"typ": "azp", "val": "client-1"}, *extra]
    return {"auth_typ": "aad", "role_typ": role_typ, "claims": claims}


def encode(p) -> str:
    return base64.b64encode(json.dumps(p).encode()).decode()


def context(header_value=None, header_name="X-MS-CLIENT-PRINCIPAL", arguments=None):
    headers = {"Content-Type": "application/json"}
    if header_value is not None:
        headers[header_name] = header_value
    return {
        "name": "whoami",
        "arguments": arguments or {},
        "transport": {"name": "http-streamable", "properties": {"headers": headers}},
    }


# ---- allowed

def test_caller_with_role_is_allowed():
    caller = require_role(context(encode(principal())))
    assert caller.roles == ("Tools.Read",)
    assert caller.object_id == "obj-1"
    assert caller.client_app_id == "client-1"


def test_header_name_is_case_insensitive():
    assert require_role(context(encode(principal()), header_name="x-ms-client-principal"))


def test_context_keys_are_case_insensitive():
    ctx = {"Transport": {"Properties": {"Headers": {"X-MS-CLIENT-PRINCIPAL": encode(principal())}}}}
    assert require_role(ctx).roles == ("Tools.Read",)


def test_long_role_claim_type_is_read():
    long_typ = "http://schemas.microsoft.com/ws/2008/06/identity/claims/role"
    assert require_role(context(encode(principal(role_typ=long_typ)))).roles == ("Tools.Read",)


# ---- refused

def test_no_transport_is_refused():
    with pytest.raises(Unauthorized):
        require_role({"name": "whoami", "arguments": {}})


def test_no_principal_header_is_refused():
    with pytest.raises(Unauthorized, match="no caller principal"):
        require_role(context(None))


def test_empty_principal_header_is_refused():
    with pytest.raises(Unauthorized):
        require_role(context(""))


def test_header_that_is_not_base64_is_refused():
    with pytest.raises(Unauthorized, match="not readable"):
        require_role(context("not base64 !!"))


def test_base64_that_is_not_json_is_refused():
    with pytest.raises(Unauthorized, match="not readable"):
        require_role(context(base64.b64encode(b"plain text").decode()))


def test_principal_without_claims_is_refused():
    with pytest.raises(Unauthorized, match="no claims"):
        require_role(context(encode({"auth_typ": "aad"})))


def test_caller_without_any_role_is_refused():
    with pytest.raises(Unauthorized, match="Tools.Read"):
        require_role(context(encode(principal(roles=()))))


def test_caller_with_another_role_is_refused():
    with pytest.raises(Unauthorized, match="Tools.Read"):
        require_role(context(encode(principal(roles=("Tools.Write",)))))


def test_role_match_is_exact_case():
    with pytest.raises(Unauthorized):
        require_role(context(encode(principal(roles=("tools.read",)))))


def test_role_in_a_non_role_claim_is_ignored():
    p = principal(roles=(), extra=[{"typ": "name", "val": "Tools.Read"}])
    with pytest.raises(Unauthorized):
        require_role(context(encode(p)))


def test_role_in_tool_arguments_is_ignored():
    """The agent controls the arguments, so a role there must count for nothing."""
    with pytest.raises(Unauthorized):
        require_role(context(None, arguments={"roles": ["Tools.Read"], "x-ms-client-principal": encode(principal())}))


# ---- the gateway

def test_gateway_runs_tool_for_allowed_caller():
    out = gateway.run(json.dumps(context(encode(principal()))), lambda caller: {"ok": caller.object_id})
    assert json.loads(out) == {"ok": "obj-1"}


def test_gateway_does_not_run_tool_for_refused_caller():
    called = []
    out = gateway.run(json.dumps(context(None)), lambda caller: called.append(caller))
    assert called == []
    assert json.loads(out)["error"] == "forbidden"


def test_gateway_refuses_unreadable_context():
    called = []
    out = gateway.run("{not json", lambda caller: called.append(caller))
    assert called == [] and json.loads(out)["error"] == "forbidden"


def test_refusal_never_echoes_the_header():
    header_value = encode(principal(roles=("Other",)))
    out = gateway.run(json.dumps(context(header_value)), lambda caller: {})
    assert header_value not in out


# ---- built-in auth must be on, or the header could be forged

def test_refused_when_built_in_auth_flag_is_missing(monkeypatch):
    monkeypatch.delenv("WEBSITE_AUTH_ENABLED")
    with pytest.raises(Unauthorized, match="built-in auth is not enabled"):
        require_role(context(encode(principal())))


def test_refused_when_built_in_auth_flag_is_false(monkeypatch):
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "False")
    with pytest.raises(Unauthorized, match="built-in auth is not enabled"):
        require_role(context(encode(principal())))


def test_two_principal_headers_joined_by_comma_are_refused():
    """If a forged header and the real one were both sent, the extension joins
    them with a comma. That is not valid base64, so the call fails closed."""
    joined = encode(principal()) + "," + encode(principal(roles=("Other",)))
    with pytest.raises(Unauthorized, match="not readable"):
        require_role(context(joined))


def test_required_role_is_tools_read():
    assert auth.REQUIRED_ROLE == "Tools.Read"
