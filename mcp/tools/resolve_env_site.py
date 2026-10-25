"""resolve_env_site: the env-site name for an environment and an Azure site, without an address.

Example: environment "prod" and site "dr" give prod-centralus, with its region, hub
firewall, policy and public IP, read from routing.yaml at the pinned commit.

Why the agent uses it: duplicate_rule_check and every rule need an env-site name,
and locate_address_for_env_site gives one only for an internal address. A ticket
whose source is an IP group and whose destination is a partner has no such address,
so on 2026-10-25 the drafter made up "prod-dr" for RITM0011050. This tool takes the
ticket's own environment and site fields instead.

Safety rule: it never guesses. It matches the two values exactly (ignoring case and
spaces), never reads an IP group's name, and never maps a word such as "secondary".
No match, or more than one, answers resolved false with the reason and the pairs
routing.yaml does list, so the agent stops and the engineer clarifies.
"""

from data_readers.read_addressplan_routing import ROUTING, Source, load_hubs, load_places
from errors import BadArguments

ARGUMENTS = ("environment", "site")


def _value(arguments: dict, name: str) -> str:
    """One argument, trimmed and lower-cased; refuse a missing or non-string value."""
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise BadArguments(f"{name} must be a non-empty string, such as {'prod' if name == 'environment' else 'dr'}")
    return value.strip().lower()


def resolve_env_site(caller, arguments: dict, source: Source) -> dict:
    """The tool: the one env-site routing.yaml gives this environment and site, or why there is none."""
    if not isinstance(arguments, dict) or set(arguments) - set(ARGUMENTS):
        raise BadArguments("only two arguments are accepted: environment and site")
    environment, site = _value(arguments, "environment"), _value(arguments, "site")
    places = load_places(source)
    hits = [p for p in places if (p.environment.lower(), p.site.lower()) == (environment, site)]
    result = {"input": {"environment": environment, "site": site}, "resolved": len(hits) == 1}
    if len(hits) == 1:
        place, hub = hits[0], load_hubs(source)[hits[0].env_site]
        result["match"] = {"env_site": place.env_site, "environment": place.environment, "site": place.site,
                           "region": place.region, "firewall": hub.firewall, "firewall_policy": hub.firewall_policy,
                           "firewall_public_ip": hub.public_ip}
    else:
        result["match"] = None
        result["reason"] = (f"routing.yaml lists no env-site for environment {environment!r} and site {site!r}"
                            if not hits else
                            f"routing.yaml lists {len(hits)} env-sites for environment {environment!r} and site "
                            f"{site!r} ({', '.join(p.env_site for p in hits)}), so the tool will not pick one")
        result["known"] = [{"environment": p.environment, "site": p.site, "env_site": p.env_site} for p in places]
    result["source"] = {"files": [ROUTING], "commit": source.commit}
    return result
