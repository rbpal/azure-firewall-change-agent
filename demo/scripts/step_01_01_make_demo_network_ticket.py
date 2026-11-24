"""Create one fictitious dev network-rule ticket (dev subnets to an external CIDR) for the manual demo.

Example: set the values below, then run
    uv run python demo/scripts/step_01_01_make_demo_network_ticket.py
It writes demo/01-waiting/<TICKET_NUMBER>.yaml.

Why: the demo needs a fresh ticket, outside the eval sets, to review before step 4 submits it.

Safety rule: it writes only if the number is new to the demo folder, both sources are subnets in the address plan
at their dev site, and intake raises nothing blocking. It never overwrites.
"""

# ===== CHANGE THESE FOR EACH NEW TICKET =====
TICKET_NUMBER = "RITM0013525"
REQUESTED_FOR = "Morgan Lee (Contoso reporting)"
PRIMARY_SOURCE_CIDR = "10.104.15.0/24"  # dev primary, East US 2
DR_SOURCE_CIDR = "10.105.15.0/24"  # dev DR, Central US
DESTINATION_CIDR = ""  # the external address, as the ticket gives it; leave empty when DESTINATION_FQDN is set
DESTINATION_FQDN = "www.wikipedia.org"  # a hostname the agent resolves through DNS; leave empty when DESTINATION_CIDR is set
DESTINATION_URL = ""  # a URL, written https://<site>/; leave empty unless used
PROTOCOL = "HTTPS"
PORTS = ["443"]
JUSTIFICATION = "The reporting batch servers in dev read public reference articles from www.wikipedia.org over HTTPS 443."

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))

import demo_ticket as demo  # noqa: E402


def build_ticket(opened: str) -> dict:
    """Return the ticket made from the values at the top, opened at this time."""
    sources = [demo.dev("primary", PRIMARY_SOURCE_CIDR), demo.dev("dr", DR_SOURCE_CIDR)]
    return demo.build(TICKET_NUMBER, opened, REQUESTED_FOR, sources, [{"url": DESTINATION_URL} if DESTINATION_URL else {"fqdn": DESTINATION_FQDN} if DESTINATION_FQDN else {"cidr": DESTINATION_CIDR}],
                      PROTOCOL, PORTS, JUSTIFICATION)


def problems(ticket: dict) -> list[str]:
    """List every source the address plan does not place at its dev site."""
    return demo.subnet_problems(ticket["sources"])


def main(argv: list[str] | None = None) -> int:
    """Check the ticket from the top values and write it to 01-waiting if nothing is wrong."""
    return demo.run(build_ticket, problems, argv)


if __name__ == "__main__":
    raise SystemExit(main())
