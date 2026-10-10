# mcp

The MCP server, an Azure Functions app in Python that uses the Functions MCP extension. This folder is the unit that gets deployed to `func-fwagentic-dev`.

| Path | Holds |
| --- | --- |
| `function_app.py` | Registers each tool with the MCP extension |
| `gateway.py` | Runs every tool behind the role check; a refused call never reaches the tool |
| `auth.py` | Refuses a call unless the caller's token holds the `Tools.Read` role |
| `host.json` | Runtime settings; the MCP webhook is anonymous, because the app's built-in Entra auth checks every request first |
| `requirements.txt` | Python packages for the app |
| `tools/` | The tool logic |

Every call passes two checks. Built-in auth on the function app rejects a request without a valid Entra token from an allowed caller. Then `auth.py` rejects a caller without `Tools.Read`. It reads the caller's claims from the `X-MS-CLIENT-PRINCIPAL` header, which built-in auth adds and the MCP extension passes to the tool in its context.

That header is only trustworthy while built-in auth is on, so `auth.py` also refuses every call unless App Service reports built-in auth as enabled (`WEBSITE_AUTH_ENABLED`). If built-in auth is ever switched off, the tools stay shut.

Tests live in `tests/mcp/`.
