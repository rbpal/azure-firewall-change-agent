"""Gate 2: refuse a tool call unless the caller holds the Tools.Read app role.

Gate 1 is the function app's built-in Entra auth. It rejects any request
without a valid token for our API from an allowed caller, then adds the
caller's claims to the request as the X-MS-CLIENT-PRINCIPAL header. The MCP
extension copies the request headers into the tool's context under
transport.properties.headers. This module reads that header and checks the
role. Anything missing or unreadable is refused.

The header is only trustworthy while built-in auth is on, because built-in
auth is what writes it. If built-in auth were switched off, anyone could send
a forged header. So every call is refused unless App Service reports built-in
auth as enabled, through the WEBSITE_AUTH_ENABLED environment variable.
"""

import base64
import binascii
import json
import os
from dataclasses import dataclass

REQUIRED_ROLE = "Tools.Read"
PRINCIPAL_HEADER = "x-ms-client-principal"
AUTH_ENABLED_ENV = "WEBSITE_AUTH_ENABLED"

# Claim types App Service may use for roles. The principal names its own in
# "role_typ"; these are the two Entra uses.
ROLE_CLAIM_TYPES = ("roles", "http://schemas.microsoft.com/ws/2008/06/identity/claims/role")


class Unauthorized(Exception):
    """The call is refused. The message says why, without echoing any token."""


@dataclass(frozen=True)
class Caller:
    object_id: str | None
    client_app_id: str | None
    roles: tuple[str, ...]
    auth_type: str | None


def _get(mapping, key):
    """Case-insensitive lookup, because JSON key casing can differ by language."""
    if not isinstance(mapping, dict):
        return None
    for k, v in mapping.items():
        if isinstance(k, str) and k.lower() == key:
            return v
    return None


def principal_header(context: dict) -> str:
    transport = _get(context, "transport")
    headers = _get(_get(transport, "properties"), "headers")
    if not isinstance(headers, dict):
        raise Unauthorized("no request headers in the tool context")
    value = _get(headers, PRINCIPAL_HEADER)
    if not isinstance(value, str) or not value:
        raise Unauthorized("no caller principal: built-in auth did not identify the caller")
    return value


def decode_principal(value: str) -> dict:
    try:
        principal = json.loads(base64.b64decode(value, validate=True))
    except (binascii.Error, ValueError) as exc:
        raise Unauthorized("caller principal is not readable") from exc
    if not isinstance(principal, dict) or not isinstance(principal.get("claims"), list):
        raise Unauthorized("caller principal has no claims")
    return principal


def caller_from_principal(principal: dict) -> Caller:
    role_types = {principal.get("role_typ"), *ROLE_CLAIM_TYPES} - {None}
    roles, claims = [], {}
    for claim in principal["claims"]:
        if not isinstance(claim, dict):
            continue
        typ, val = claim.get("typ"), claim.get("val")
        if typ in role_types and isinstance(val, str):
            roles.append(val)
        elif isinstance(typ, str) and isinstance(val, str):
            claims.setdefault(typ, val)
    return Caller(
        object_id=claims.get("http://schemas.microsoft.com/identity/claims/objectidentifier") or claims.get("oid"),
        client_app_id=claims.get("azp") or claims.get("appid"),
        roles=tuple(roles),
        auth_type=principal.get("auth_typ"),
    )


def require_role(context: dict, role: str = REQUIRED_ROLE) -> Caller:
    """Return the caller if it holds the role; raise Unauthorized otherwise."""
    if os.environ.get(AUTH_ENABLED_ENV, "").lower() != "true":
        raise Unauthorized("built-in auth is not enabled on this app, so the caller cannot be trusted")
    caller = caller_from_principal(decode_principal(principal_header(context)))
    if role not in caller.roles:
        raise Unauthorized(f"caller does not hold the {role} role")
    return caller
