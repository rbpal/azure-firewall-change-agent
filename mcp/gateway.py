"""Runs a tool behind gate 2. Every tool in function_app.py goes through run().

The tool receives the caller and the agent's arguments only after gate 2
passes. Arguments are untrusted: each tool checks its own.
"""

import json
import logging

from auth import Unauthorized, require_role
from errors import BadArguments


def run(context_json: str, tool, **kwargs) -> str:
    try:
        context = json.loads(context_json)
    except (TypeError, ValueError):
        return json.dumps({"error": "forbidden", "reason": "tool context is not readable"})
    try:
        caller = require_role(context)
    except Unauthorized as exc:
        # The reason never includes header or token values.
        logging.warning("tool call refused: %s", exc)
        return json.dumps({"error": "forbidden", "reason": str(exc)})
    arguments = context.get("arguments") or {}
    try:
        return json.dumps(tool(caller, arguments, **kwargs))
    except BadArguments as exc:
        return json.dumps({"error": "bad_arguments", "reason": str(exc)})
    except Exception:
        # Details stay in the log; the agent only learns that the tool failed.
        logging.exception("tool failed")
        return json.dumps({"error": "tool_failed"})
