"""Runs a tool behind gate 2. Every tool in function_app.py goes through run()."""

import json
import logging

from auth import Unauthorized, require_role


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
    return json.dumps(tool(caller, **kwargs))
