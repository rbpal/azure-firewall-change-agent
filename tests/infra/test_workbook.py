"""Checks on the observability workbook in infra/04-monitoring/workbook/.

Example: uv run pytest tests/infra/test_workbook.py
Why: the workbook is built from a template and one KQL file per query, so a renamed file,
a leaked prompt column or a cost figure shown too early would otherwise reach Azure unnoticed.
Safety rule: these tests read files only; they never call Azure or Terraform.
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2] / "infra" / "04-monitoring"
TEMPLATE = ROOT / "workbook" / "fwagent-observability.workbook.json.tftpl"
KQL = ROOT / "workbook" / "kql"
SHARED = KQL / "_agent_runs.kql"
INCLUDE = "// @include agent_runs"
PLACEHOLDER = re.compile(r'\$\{jsonencode\(queries\["([a-z_]+)"\]\)\}')
CONTENT_FIELDS = ("InputMessages", "OutputMessages", "SystemInstructions", "gen_ai.input.messages",
                  "gen_ai.output.messages", "gen_ai.system_instructions")
STAGE2 = "AWAITING STAGE 2 DATA"


def queries() -> dict[str, str]:
    """Every query as Terraform builds it: the file text with the shared block pasted in."""
    shared = SHARED.read_text()
    return {p.stem: p.read_text().replace(INCLUDE, shared) for p in KQL.glob("*.kql") if not p.name.startswith("_")}


def render(text: str | None = None) -> dict:
    """The workbook JSON as Terraform's templatefile() renders it."""
    text = TEMPLATE.read_text() if text is None else text
    built = queries()
    text = PLACEHOLDER.sub(lambda m: json.dumps(built[m.group(1)]), text)
    text = text.replace("${jsonencode(workspace_id)}", json.dumps("/subscriptions/x/workspaces/law"))
    text = text.replace("${jsonencode(daily_cap_mb)}", json.dumps("160"))
    return json.loads(text)


def items(kind: int) -> list[dict]:
    """Workbook items of one kind (1 text, 3 query), leaving out parameters that share the number."""
    return [n for n in walk(render()) if n.get("type") == kind and "content" in n and "name" in n]


def walk(node):
    """Every dict inside the workbook JSON, depth first."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def test_the_template_renders_valid_workbook_json():
    """The rendered template parses and is a Notebook/1.0 workbook."""
    workbook = render()
    assert workbook["version"] == "Notebook/1.0"
    assert workbook["items"]


def test_the_template_has_no_interpolation_terraform_would_misread():
    """Only the three known placeholders use ${...}; any other one would break or change the render."""
    text = PLACEHOLDER.sub("", TEMPLATE.read_text())
    text = text.replace("${jsonencode(workspace_id)}", "").replace("${jsonencode(daily_cap_mb)}", "")
    assert "${" not in text and "%{" not in text


def test_every_named_query_has_a_file_and_every_file_is_used():
    """A query named in the template exists as a .kql file, and no .kql file is left unused."""
    named = set(PLACEHOLDER.findall(TEMPLATE.read_text()))
    assert named == set(queries())


def test_an_unknown_query_name_fails_the_render():
    """A placeholder naming a missing file is caught, as Terraform's map lookup would be."""
    with pytest.raises(KeyError):
        render(TEMPLATE.read_text() + '${jsonencode(queries["no_such_query"])}')


def test_prompt_and_reply_text_are_read_only_inside_the_shared_block():
    """Only _agent_runs.kql reads message content, and its output columns carry none of it."""
    for path in KQL.glob("*.kql"):
        if path != SHARED:
            assert not any(field in path.read_text() for field in CONTENT_FIELDS), path.name
    final = SHARED.read_text().split("let agent_runs")[1]
    columns = re.search(r"\| project ([^\n]+)", final).group(1)
    assert not {"inmsg", "outmsg"} & {c.strip() for c in columns.split(",")}


def test_queries_that_use_agent_runs_include_the_shared_block():
    """A query that names agent_runs pastes in the shared block that defines it."""
    for path in KQL.glob("*.kql"):
        text = path.read_text()
        if path != SHARED and "agent_runs" in text.replace(INCLUDE, ""):
            assert INCLUDE in text, path.name


def test_rows_ingested_twice_count_once():
    """Each query that counts spans or requests collapses them by Id first."""
    for name, text in queries().items():
        if re.search(r"\b(AppDependencies|AppRequests)\b", text) and name != "agent_version_values":
            assert re.search(r"arg_min\(TimeGenerated, \*\) by (Id|span_id)|distinct OperationId", text), name


def test_no_panel_shows_cost_correctness_or_a_drift_verdict_before_stage_2():
    """No query computes cost, a pass/fail verdict or a drift result, and the waiting panels say why."""
    for name, text in queries().items():
        code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("//"))
        assert not re.search(r"\w*(cost|price|usd|passed|correct|drift)\w*\s*=", code, re.I), name
    texts = [n["content"]["json"] for n in items(1)]
    waiting = [t for t in texts if STAGE2 in t]
    assert any("cost" in t for t in waiting)
    assert any("correctness" in t for t in waiting)
    assert any("drift" in t for t in waiting)


def test_reply_outcome_is_kept_apart_from_policy_validation():
    """The outcome panel says it is the agent's answer, and validation waits for stage 2."""
    titles = [n["content"]["title"] for n in items(3)]
    assert any("not policy validation" in t for t in titles)
    texts = [n["content"]["json"] for n in items(1)]
    assert any(STAGE2 in t and "tier1-gate" in t for t in texts)


def test_every_query_reads_the_workspace_with_the_time_filter():
    """Each query panel targets the workspace and takes the time range from the filter."""
    panels = [n["content"] for n in items(3)]
    assert panels
    for content in panels:
        assert content["resourceType"] == "microsoft.operationalinsights/workspaces"
        assert content["crossComponentResources"] == ["/subscriptions/x/workspaces/law"]
        assert content["timeContextFromParameter"] == "TimeRange"
        assert "{TimeRange}" in content["query"]


def test_the_timeline_shows_what_each_tool_answered():
    """Each tool row carries the tool's full result and a one-line answer, not only its arguments."""
    final = queries()["timeline"].rsplit("| project ", 1)[1]
    columns = {c.strip() for c in final.split("\n")[0].split(",") + final.split("\n")[1].split(",")}
    assert {"arguments", "answer", "result"} <= columns
    assert 'Properties["gen_ai.tool.call.result"]' in queries()["timeline"]


def test_the_timeline_names_both_sides_of_a_tool_call():
    """Foundry's wait and the Function App's run carry distinct labels and a service column."""
    timeline = queries()["timeline"]
    final = timeline.rsplit("| project ", 1)[1].split("\n")[0]
    assert "service" in {c.strip() for c in final.split(",")}
    assert '"Tool invocation — Foundry"' in timeline and '"Tool execution — Function App"' in timeline
    assert timeline.count("service = AppRoleName") == 2
    assert '"tool server"' not in timeline


def test_a_tool_result_opens_in_full_and_a_missing_one_says_so():
    """The result column links to Cell Details, and a tool call with no stored result reads 'no answer recorded'."""
    def items(node):
        """Every workbook item, nested groups included."""
        for item in node.get("items", []):
            yield item
            yield from items(item.get("content", {}))
    timeline = next(i for i in items(render()) if i.get("name") == "timeline")
    formatters = timeline["content"]["gridSettings"]["formatters"]
    link = next(f for f in formatters if f["columnMatch"] == "^result$")
    assert link["formatter"] == 7 and link["formatOptions"]["linkTarget"] == "CellDetails"
    assert '"no answer recorded"' in queries()["timeline"].split("| project TimeGenerated,", 1)[1]
