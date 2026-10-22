"""dns_lookup_for_fqdn: input parsing, the merged answer, and the gateway path.
Unit tests use a fake resolver. The live tests ask real DNS for real public
names and run only with LIVE_DNS=1, so CI never depends on the internet."""

import json
import os
import re

import dns.resolver
import pytest

import gateway
from errors import BadArguments
from tools import dns_lookup_for_fqdn as mod
from tools.dns_lookup_for_fqdn import Reply, dns_lookup_for_fqdn, dnspython_lookup, parse_target


def fake(records: dict):
    """Build a lookup that answers from a dict keyed by (host, rdtype) and logs each call."""
    calls = []

    def lookup(host, rdtype):
        """Return the canned reply, or NXDOMAIN when there is none."""
        calls.append((host, rdtype))
        return records.get((host, rdtype), Reply(rcode="NXDOMAIN"))
    lookup.calls = calls
    return lookup


WWW = fake({
    ("www.google.com", "A"): Reply("NOERROR", [], ["142.250.80.4", "142.250.80.36"], 300),
    ("www.google.com", "AAAA"): Reply("NOERROR", [], ["2607:f8b0:4006:80f::2004"], 120),
    ("www.cnn.com", "A"): Reply("NOERROR", ["cnn-tls.map.fastly.net"], ["151.101.3.5", "151.101.67.5"], 30),
    ("www.cnn.com", "AAAA"): Reply("NOERROR", ["cnn-tls.map.fastly.net"], [], None),
})


# --- parse_target --------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("https://www.google.com/search?q=x", ("www.google.com", 443, "https")),
    ("http://www.cnn.com/world", ("www.cnn.com", 80, "http")),
    ("https://www.cnn.com:8443/", ("www.cnn.com", 8443, "https")),
    ("www.google.com", ("www.google.com", None, None)),
    ("WWW.Google.COM.", ("www.google.com", None, None)),
    ("www.google.com:8080", ("www.google.com", 8080, None)),
    ("  https://www.google.com  ", ("www.google.com", 443, "https")),
])
def test_parse_target_keeps_only_host_port_scheme(text, expected):
    assert parse_target(text) == expected


@pytest.mark.parametrize("text, message", [
    ("", "non-empty"),
    (None, "non-empty"),
    (42, "non-empty"),
    ("ftp://www.google.com", "scheme"),
    ("file:///etc/passwd", "scheme"),
    ("https://user:pw@localhost/", "user name or password"),
    ("https://10.1.2.3/", "IP address"),
    ("https://[::1]/", "IP address"),
    ("*.google.com", "wildcard"),
    ("localhost", "not a valid hostname"),
    ("www.goo gle.com", "not a valid hostname"),
    ("-bad.google.com", "not a valid hostname"),
    ("a" * 64 + ".com", "not a valid hostname"),
    ("https://www.google.com:99999/", "not a URL or hostname"),
    ("https:///path", "no hostname"),
])
def test_parse_target_refuses(text, message):
    with pytest.raises(BadArguments, match=message):
        parse_target(text)


# --- the answer ----------------------------------------------------------

def test_answer_merges_a_and_aaaa_and_takes_the_lowest_ttl():
    out = dns_lookup_for_fqdn(None, {"target": "https://www.google.com/x"}, lookup=WWW)
    assert out["host"] == "www.google.com" and out["port"] == 443 and out["scheme"] == "https"
    assert out["rcode"] == "NOERROR" and out["resolves"] is True and out["reason"] is None
    assert out["a"] == ["142.250.80.4", "142.250.80.36"]
    assert out["aaaa"] == ["2607:f8b0:4006:80f::2004"]
    assert out["ttl"] == 120
    assert out["cname_chain"] == []


def test_answer_carries_the_cname_chain():
    out = dns_lookup_for_fqdn(None, {"target": "www.cnn.com"}, lookup=WWW)
    assert out["cname_chain"] == ["cnn-tls.map.fastly.net"]
    assert out["aaaa"] == [] and out["ttl"] == 30


def test_addresses_are_sorted_numerically_not_as_text():
    lookup = fake({("x.example.com", "A"): Reply("NOERROR", [], ["10.0.0.10", "10.0.0.9", "10.0.0.9"], 60),
                   ("x.example.com", "AAAA"): Reply("NOERROR")})
    assert dns_lookup_for_fqdn(None, {"target": "x.example.com"}, lookup=lookup)["a"] == ["10.0.0.9", "10.0.0.10"]


def test_nxdomain_is_an_answer_and_skips_the_aaaa_query():
    lookup = fake({})
    out = dns_lookup_for_fqdn(None, {"target": "api.northwind.example"}, lookup=lookup)
    assert out["resolves"] is False and "NXDOMAIN" in out["reason"]
    assert out["rcode"] == "NXDOMAIN" and out["a"] == [] and out["aaaa"] == [] and out["ttl"] is None
    assert lookup.calls == [("api.northwind.example", "A")]


def test_name_without_addresses_does_not_resolve():
    """NOERROR with an empty answer (NODATA): the name exists but gives no IP."""
    lookup = fake({("mail.example.com", "A"): Reply("NOERROR"), ("mail.example.com", "AAAA"): Reply("NOERROR")})
    out = dns_lookup_for_fqdn(None, {"target": "mail.example.com"}, lookup=lookup)
    assert out["rcode"] == "NOERROR" and out["resolves"] is False
    assert out["reason"] == "the name exists but has no A or AAAA record"


def test_ipv6_only_name_resolves():
    lookup = fake({("v6.example.com", "A"): Reply("NOERROR"),
                   ("v6.example.com", "AAAA"): Reply("NOERROR", [], ["2001:db8::1"], 60)})
    assert dns_lookup_for_fqdn(None, {"target": "v6.example.com"}, lookup=lookup)["resolves"] is True


def test_answer_names_the_resolver_and_the_time():
    out = dns_lookup_for_fqdn(None, {"target": "www.google.com"}, lookup=WWW)
    assert out["resolver"] == "168.63.129.16"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", out["queried_at"])
    assert out["input"] == "www.google.com"


def test_answer_has_exactly_these_fields():
    out = dns_lookup_for_fqdn(None, {"target": "www.google.com"}, lookup=WWW)
    assert set(out) == {"input", "host", "port", "scheme", "resolves", "reason", "rcode", "cname_chain", "a", "aaaa",
                        "ttl", "resolver", "queried_at"}
    json.dumps(out)


@pytest.mark.parametrize("arguments", [None, [], {}, {"target": "www.google.com", "extra": 1}, {"host": "x.com"}])
def test_bad_argument_shapes_are_refused(arguments):
    with pytest.raises(BadArguments):
        dns_lookup_for_fqdn(None, arguments, lookup=WWW)


def test_refused_input_never_reaches_dns():
    lookup = fake({})
    with pytest.raises(BadArguments):
        dns_lookup_for_fqdn(None, {"target": "https://10.0.0.1/"}, lookup=lookup)
    assert lookup.calls == []


def test_the_tool_never_fetches_anything():
    """Lookup only: the module imports no HTTP or socket client of its own."""
    source = open(mod.__file__).read()
    for banned in ("urllib.request", "http.client", "requests", "httpx", "aiohttp", "import socket"):
        assert banned not in source


def test_default_lookup_asks_azure_dns(monkeypatch):
    seen = {}

    def spy(nameserver, timeout=5.0):
        """Record the nameserver the tool picked and answer from the fake."""
        seen["nameserver"] = nameserver
        return WWW
    monkeypatch.setattr(mod, "dnspython_lookup", spy)
    dns_lookup_for_fqdn(None, {"target": "www.google.com"})
    assert seen["nameserver"] == "168.63.129.16"


# --- behind the gateway --------------------------------------------------

def test_gateway_returns_the_answer(allowed_context):
    ctx = allowed_context({"target": "https://www.cnn.com/"})
    out = json.loads(gateway.run(ctx, dns_lookup_for_fqdn, lookup=WWW))
    assert out["host"] == "www.cnn.com" and out["a"] == ["151.101.3.5", "151.101.67.5"]


def test_gateway_turns_bad_input_into_bad_arguments(allowed_context):
    ctx = allowed_context({"target": "ftp://www.cnn.com"})
    out = json.loads(gateway.run(ctx, dns_lookup_for_fqdn, lookup=WWW))
    assert out["error"] == "bad_arguments"


# --- live: real DNS, real public names ------------------------------------

live = pytest.mark.skipif(os.environ.get("LIVE_DNS") != "1", reason="set LIVE_DNS=1 to query real DNS")


def _system_nameserver() -> str:
    """Return this machine's first configured nameserver; the laptop cannot reach Azure DNS."""
    return dns.resolver.Resolver().nameservers[0]


@live
@pytest.mark.parametrize("target", ["https://www.google.com/", "https://www.cnn.com/"])
def test_live_public_names_resolve(target):
    """Checks the shape, never specific IPs: CDN answers change by region and hour."""
    ns = _system_nameserver()
    out = dns_lookup_for_fqdn(None, {"target": target}, lookup=dnspython_lookup(ns), resolver_name=ns)
    assert out["rcode"] == "NOERROR" and out["resolves"] is True
    assert out["a"], out
    assert out["ttl"] is not None and out["ttl"] >= 0


@live
def test_live_fake_partner_name_is_nxdomain():
    ns = _system_nameserver()
    out = dns_lookup_for_fqdn(None, {"target": "api.northwind.example"}, lookup=dnspython_lookup(ns), resolver_name=ns)
    assert out["rcode"] == "NXDOMAIN" and out["resolves"] is False


# --- the eval's controlled DNS (RITM0011063) ------------------------------

@pytest.mark.parametrize("fault", ["timeout", "servfail"])
def test_a_controlled_dns_failure_reaches_the_agent_as_tool_failed(allowed_context, fault):
    """The eval resolver raises what dnspython raises, so the agent sees what it would in Azure: the lookup could not run."""
    from evals.run_eval import controlled_dns
    ctx = allowed_context({"target": "https://exchange.northwind.example/v1/upload"})
    out = json.loads(gateway.run(ctx, dns_lookup_for_fqdn, lookup=controlled_dns({"exchange.northwind.example": fault})))
    assert out == {"error": "tool_failed"}


def test_a_name_without_a_dns_condition_is_nxdomain_as_in_real_dns(allowed_context):
    """Every other name, such as api.litware.example in RITM0011015, gets NXDOMAIN: a caution, not a failure."""
    from evals.run_eval import controlled_dns
    ctx = allowed_context({"target": "https://api.litware.example/v1/upload"})
    out = json.loads(gateway.run(ctx, dns_lookup_for_fqdn, lookup=controlled_dns({"exchange.northwind.example": "timeout"})))
    assert out["rcode"] == "NXDOMAIN" and out["resolves"] is False
