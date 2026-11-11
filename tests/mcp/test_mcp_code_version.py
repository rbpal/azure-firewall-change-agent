"""The code_version tool behind the gateway. Each test fails if the tool skips gate 2, hashes the wrong
files, or stops matching the hash the workflow computes for main."""

import json

import gateway
from tools.code_version import ROOT, app_files, code_version


def test_the_tool_hashes_its_own_app_root():
    assert ROOT.name == "mcp" and "function_app.py" in app_files(ROOT)


def test_through_the_gateway_it_answers_the_hash_of_this_folder(allowed_context):
    answer = json.loads(gateway.run(allowed_context({}), code_version))
    assert answer == code_version(None)
    assert {"function_app.py", "gateway.py", "auth.py", "host.json", "requirements.txt",
            "tools/code_version.py"} <= set(answer["files"])
    assert not any(p.endswith(".md") or "__pycache__" in p for p in answer["files"])


def test_without_the_role_it_is_refused(monkeypatch):
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")
    assert json.loads(gateway.run(json.dumps({"arguments": {}}), code_version))["error"] == "forbidden"
