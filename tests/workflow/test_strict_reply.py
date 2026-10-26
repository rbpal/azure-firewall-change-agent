"""Strict reply format: the {"reply": ...} wrapper the service is asked to enforce, and the unchanged check after it.

agents/reply.strict.schema.json must stay inside the structured-output subset Azure documents, must never refuse
a correct answer, and must make the recorded action failures impossible to write. Whatever it cannot express
(empty lists, patterns, lengths) is still refused by agents/reply.schema.json, which runs on the inner reply
unchanged. Each check here must be able to fail.
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from workflow.agent import REPLY_SCHEMA, STRICT_SCHEMA, AgentError, parse_agent_text, parse_reply

REPO = Path(__file__).resolve().parents[2]
WIRE = jsonschema.Draft202012Validator(STRICT_SCHEMA)
# Keywords the Azure OpenAI structured-output subset does not support, plus combinators outside its type list.
UNSUPPORTED = {"minLength", "maxLength", "pattern", "format", "minimum", "maximum", "multipleOf", "patternProperties",
               "unevaluatedProperties", "propertyNames", "minProperties", "maxProperties", "unevaluatedItems",
               "contains", "minContains", "maxContains", "minItems", "maxItems", "uniqueItems",
               "allOf", "oneOf", "not", "if", "then", "else", "const", "dependentRequired"}
VALIDATION = sorted((REPO / "evals" / "requests" / "validation").glob("*.yaml"))  # never the sealed test split
RULE = {"env_site": "prod-eastus2", "spoke": "sett", "collection": "allow-sett-network-rules", "name": "r",
        "sources": ["10.100.14.0/25"], "destinations": ["203.0.113.80/28"], "ports": ["22"], "protocol": "TCP"}
DNAT = {**RULE, "collection": "allow-sett-dnat-rules", "translated_address": "10.100.14.4", "translated_port": "22"}
# The drafter's own invalid replies, verbatim (v4 and v5 runs, 2026-10-25); explanations shortened only.
RECORDED = {
    "v4 0061 action on a stop": {"outcome": "stop_and_ask", "reason": "both_ends_onprem", "action": "remove",
                                 "rules": [], "explanation": "Both ends are on-prem."},
    "v5 0065 action on a stop": {"outcome": "stop_and_ask", "reason": "rule_allows_more", "action": "remove",
                                 "rules": [], "explanation": "The matching rule allows more."},
    "v5 0065 action null": {"outcome": "stop_and_ask", "reason": "rule_allows_more", "action": None, "rules": [],
                            "explanation": "The matching rule allows more."},
    "v5 0061 placeholder key": {"outcome": "stop_and_ask", "reason": "both_ends_onprem", "action omitted": None,
                                "rules": [], "explanation": "Both ends are on-prem."},
    "v5 0065 question-mark key": {"outcome": "stop_and_ask", "reason": "rule_allows_more", "action?": "omit",
                                  "rules": [], "explanation": "The matching rule allows more."},
    "v3 0050 stop without a reason": {"outcome": "stop_and_ask", "rules": [], "explanation": "Clarify the env-site."},
}


def walk(node):
    """Every schema dict under node."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def depth(node, seen=()):
    """How many objects deep node goes, following $ref into $defs."""
    if isinstance(node, list):
        return max((depth(v, seen) for v in node), default=0)
    if not isinstance(node, dict):
        return 0
    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        return 0 if name in seen else depth(STRICT_SCHEMA["$defs"][name], seen + (name,))
    below = max((depth(v, seen) for k, v in node.items() if k != "$defs"), default=0)
    return below + (1 if node.get("type") == "object" else 0)


# --- inside the documented subset --------------------------------------------

def test_the_root_is_one_object_not_any_of():
    assert STRICT_SCHEMA["type"] == "object" and "anyOf" not in STRICT_SCHEMA
    assert STRICT_SCHEMA["required"] == ["reply"] and list(STRICT_SCHEMA["properties"]) == ["reply"]


def test_every_object_is_closed_and_requires_every_property():
    objects = [n for n in walk(STRICT_SCHEMA) if n.get("type") == "object"]
    assert len(objects) == 7
    for node in objects:
        assert node["additionalProperties"] is False
        assert sorted(node["required"]) == sorted(node["properties"])


def test_no_unsupported_keyword_is_used():
    assert not {k for n in walk(STRICT_SCHEMA) for k in n} & UNSUPPORTED


def test_it_stays_under_100_properties_and_5_levels():
    assert sum(len(n.get("properties", {})) for n in walk(STRICT_SCHEMA)) <= 100
    assert depth(STRICT_SCHEMA) == 3  # root -> reply shape -> rule


# --- never refuses a correct answer ------------------------------------------

@pytest.mark.parametrize("path", VALIDATION, ids=lambda p: p.name)
def test_every_labelled_validation_answer_fits_the_wrapper_and_comes_back_unchanged(path):
    expected = yaml.safe_load(path.read_text())["expected"]
    reply = {k: copy.deepcopy(expected[k]) for k in ("outcome", "reason", "action", "rules") if k in expected}
    reply.setdefault("rules", [])
    reply["explanation"] = "Plain words for the engineer."
    assert parse_agent_text(json.dumps({"reply": reply})) == reply


@pytest.mark.parametrize("reply", [
    {"outcome": "draft", "rules": [RULE], "explanation": "x"},
    {"outcome": "draft", "action": "remove", "rules": [RULE], "explanation": "x"},
    {"outcome": "draft", "rules": [DNAT], "explanation": "x"},
    {"outcome": "already_allowed", "rules": [RULE], "explanation": "x"},
    {"outcome": "stop_and_ask", "reason": "rule_allows_more", "rules": [], "explanation": "x"},
], ids=["add", "remove", "dnat", "already allowed", "stop keeps rules []"])
def test_each_valid_shape_passes_both_checks_unchanged(reply):
    before = copy.deepcopy(reply)
    assert parse_agent_text(json.dumps({"reply": reply})) == before


# --- the recorded failures cannot be written ---------------------------------

@pytest.mark.parametrize("reply", RECORDED.values(), ids=RECORDED.keys())
def test_a_recorded_invalid_reply_is_outside_the_strict_schema(reply):
    assert list(WIRE.iter_errors({"reply": reply}))
    with pytest.raises(AgentError, match="agents/reply.strict.schema.json"):
        parse_agent_text(json.dumps({"reply": reply}))


@pytest.mark.parametrize("reply", [
    {"outcome": "already_allowed", "action": "remove", "rules": [RULE], "explanation": "x"},
    {"outcome": "draft", "reason": "hub_rule", "rules": [RULE], "explanation": "x"},
    {"outcome": "draft", "action": "add", "rules": [RULE], "explanation": "x"},
    {"outcome": "draft", "rules": [{**RULE, "env_site": "prod-westus2"}], "explanation": "x"},  # v4 0049 guessed it
    {"outcome": "draft", "rules": [{**RULE, "action": "Allow"}], "explanation": "x"},
    {"outcome": "stop_and_ask", "reason": "hub_rule", "explanation": "x"},  # rules missing
], ids=["action on already allowed", "reason on a draft", "action add", "made-up env-site", "unknown rule field",
        "stop without rules"])
def test_other_broken_shapes_are_outside_the_strict_schema(reply):
    assert list(WIRE.iter_errors({"reply": reply}))


# --- what strict mode cannot say, the unchanged check still refuses ----------

@pytest.mark.parametrize("reply, why", [
    ({"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [RULE], "explanation": "x"}, "rules"),
    ({"outcome": "draft", "rules": [], "explanation": "x"}, "rules"),
    ({"outcome": "draft", "rules": [{**RULE, "spoke": "SETT"}], "explanation": "x"}, "spoke"),
    ({"outcome": "draft", "rules": [{**RULE, "sources": []}], "explanation": "x"}, "sources"),
    ({"outcome": "draft", "rules": [{**RULE, "name": ""}], "explanation": "x"}, "name"),
    ({"outcome": "stop_and_ask", "reason": "Not A Code", "rules": [], "explanation": "x"}, "reason"),
    ({"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "explanation": "x" * 2001}, "explanation"),
], ids=["stop with a rule", "draft with no rule", "spoke pattern", "empty sources", "empty name", "reason pattern",
        "explanation too long"])
def test_strict_mode_lets_these_through_and_the_unchanged_check_refuses_them(reply, why):
    assert not list(WIRE.iter_errors({"reply": reply}))
    with pytest.raises(AgentError, match="agents/reply.schema.json") as raised:
        parse_agent_text(json.dumps({"reply": reply}))
    assert why in str(raised.value)
    with pytest.raises(AgentError):
        parse_reply(json.dumps(reply))  # the same verdict as the reply check alone


# --- the wrapper itself -------------------------------------------------------

def test_an_unwrapped_reply_is_refused_and_its_raw_text_kept():
    text = json.dumps({"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "explanation": "x"})
    with pytest.raises(AgentError, match="'reply' is a required property") as raised:
        parse_agent_text(text)
    assert raised.value.raw == text


def test_a_second_top_level_key_is_refused():
    stop = {"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "explanation": "x"}
    with pytest.raises(AgentError, match="action"):
        parse_agent_text(json.dumps({"reply": stop, "action": None}))


def test_not_json_is_refused_as_before():
    with pytest.raises(AgentError, match="not JSON"):
        parse_agent_text("I cannot help with that.")


def test_the_reply_check_still_forbids_action_on_a_stop_and_requires_a_reason():
    stop = REPLY_SCHEMA["allOf"][0]["then"]
    assert stop["required"] == ["reason"] and stop["properties"]["action"] is False
    assert REPLY_SCHEMA["additionalProperties"] is False
