"""whoami: report who called, as gate 2 saw it.

A diagnostic tool. It proves the path from caller to tool works end to end:
Entra token, built-in auth, the claims header, the role check.
"""

from auth import Caller


def whoami(caller: Caller, arguments: dict | None = None) -> dict:
    return {
        "object_id": caller.object_id,
        "client_app_id": caller.client_app_id,
        "roles": list(caller.roles),
        "auth_type": caller.auth_type,
    }
