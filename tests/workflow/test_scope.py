"""Writing a reply into the selected sites only: primary, DR or both. Every check here must be able to fail."""

import copy
import shutil
from pathlib import Path

import pytest
import yaml

from workflow.scope import BACKUP, ApprovalError, PartialWriteError, ScopeError, apply_reply, selected_env_sites
from workflow.tfvars_writer import DraftError, parse_rules
from workflow.tickets import load_ticket, ticket_errors

REPO = Path(__file__).resolve().parents[2]
SPOKE_FILE = "infra/envs/{}/firewall_policy_rule_collection_groups/sett.tfvars"
PRIMARY, DR = "prod-eastus2", "prod-centralus"
SOURCE = {PRIMARY: "10.100.14.0/24", DR: "10.101.14.0/24"}
SITE = {"primary": PRIMARY, "dr": DR}
SCOPES = {"primary": ["primary"], "dr": ["dr"], "both": ["primary", "dr"]}
# In both prod files as 008, with 009-023 after it and the same fields apart from the source.
WINGTIP = {"name": "smtp-sett-to-wingtipSmtp", "destinations": ["198.51.100.80/28"], "ports": ["587"]}
NORTHWIND = {"name": "https-sett-to-northwindFs", "destinations": ["203.0.113.16/28"], "ports": ["443"]}


@pytest.fixture
def repo(tmp_path):
    """A copy of the network data and every env-site's files."""
    shutil.copytree(REPO / "data" / "network", tmp_path / "data" / "network")
    shutil.copytree(REPO / "infra" / "envs", tmp_path / "infra" / "envs")
    return tmp_path


def snapshot(root):
    """Every file under infra/, as bytes, keyed by its path inside the copy."""
    return {p.relative_to(root): p.read_bytes() for p in sorted((root / "infra").rglob("*")) if p.is_file()}


def changed(before, root):
    """The files whose bytes differ from the snapshot."""
    after = snapshot(root)
    assert after.keys() == before.keys()
    return {str(p) for p in after if after[p] != before[p]}


def ticket(scope, removal=False):
    """A prod-only sett ticket that selects the given sites; DR is built either way."""
    t = copy.deepcopy(load_ticket(REPO / "data" / "tickets" / "RITM0010042.yaml"))
    sites = SCOPES[scope]
    flow = WINGTIP if removal else NORTHWIND
    t.update(environments=["prod"], dr_site_built={"prod": True}, change_sites={"prod": sites},
             sources=[{"environment": "prod", "site": s, "cidr": SOURCE[SITE[s]]} for s in sites],
             destination=[{"cidr": flow["destinations"][0]}], ports=flow["ports"])
    if removal:
        t["item"] = "Firewall Rule Removal"
    assert ticket_errors(t) == []
    return t


def reply(env_sites, removal=False):
    """The agent's draft for the same flow at each named env-site."""
    flow = WINGTIP if removal else NORTHWIND
    rules = [{"env_site": e, "spoke": "sett", "collection": "allow-sett-network-rules", **flow,
              "sources": [SOURCE[e]], "protocol": "TCP"} for e in env_sites]
    return {"outcome": "draft", **({"action": "remove"} if removal else {}), "rules": rules}


def keys(root, env_site):
    """The network rule keys in one prod sett file, in file order."""
    rules = parse_rules((root / SPOKE_FILE.format(env_site)).read_text(), "sett", "x")
    return [r["key"] for c in rules["collections"] if c["name"] == "allow-sett-network-rules" for r in c["rules"]]


@pytest.mark.parametrize("scope", SCOPES)
def test_selected_env_sites_follow_change_sites_not_dr_built(repo, scope):
    assert selected_env_sites(repo, ticket(scope)) == {SITE[s] for s in SCOPES[scope]}


@pytest.mark.parametrize("scope", SCOPES)
def test_an_add_changes_only_the_selected_files(repo, scope):
    sites = [SITE[s] for s in SCOPES[scope]]
    before = snapshot(repo)
    written = apply_reply(repo, ticket(scope), reply(sites))
    assert changed(before, repo) == {SPOKE_FILE.format(e) for e in sites}
    assert [k for _, k in written] == ["024-https-sett-to-northwindFs"] * len(sites)
    for e in {PRIMARY, DR} - set(sites):
        assert "024-https-sett-to-northwindFs" not in keys(repo, e)


@pytest.mark.parametrize("scope", SCOPES)
def test_a_removal_changes_only_the_selected_files(repo, scope):
    # Primary-only and DR-only must not stop because the other site still holds the rule.
    sites = [SITE[s] for s in SCOPES[scope]]
    before = snapshot(repo)
    written = apply_reply(repo, ticket(scope, removal=True), reply(sites, removal=True))
    assert changed(before, repo) == {SPOKE_FILE.format(e) for e in sites}
    assert [k for _, k in written] == ["008-smtp-sett-to-wingtipSmtp"] * len(sites)
    for e in sites:
        assert len(keys(repo, e)) == 22 and keys(repo, e)[7] == "008-https-sett-to-fabrikamFs"
    for e in {PRIMARY, DR} - set(sites):
        assert "008-smtp-sett-to-wingtipSmtp" in keys(repo, e) and len(keys(repo, e)) == 23


def test_each_file_takes_its_own_next_index(repo):
    """After a DR-only removal, an add at both sites gets 024 at primary and 023 at DR."""
    apply_reply(repo, ticket("dr", removal=True), reply([DR], removal=True))
    written = dict(apply_reply(repo, ticket("both"), reply([PRIMARY, DR])))
    assert written == {repo / SPOKE_FILE.format(PRIMARY): "024-https-sett-to-northwindFs",
                       repo / SPOKE_FILE.format(DR): "023-https-sett-to-northwindFs"}


def test_a_removal_matches_by_name_and_fields_when_the_keys_differ(repo):
    """Once DR has lost 008, the same later rule has a different key at each site; both are found."""
    apply_reply(repo, ticket("dr", removal=True), reply([DR], removal=True))
    lamna = {"name": "https-sett-to-lamnaFs", "destinations": ["198.51.100.48/28"], "ports": ["443"]}
    t = ticket("both", removal=True)
    t["destination"] = [{"cidr": "198.51.100.48/28"}]
    t["ports"] = ["443"]
    r = reply([PRIMARY, DR], removal=True)
    for rule in r["rules"]:
        rule.update(lamna)
    assert sorted(k for _, k in apply_reply(repo, t, r)) == ["012-https-sett-to-lamnaFs", "013-https-sett-to-lamnaFs"]


REFUSED = {
    "rule at an unselected site": (lambda: (ticket("primary"), reply([PRIMARY, DR]))),
    "DR-only ticket, primary rule": (lambda: (ticket("dr"), reply([PRIMARY]))),
    "selected site with no rule": (lambda: (ticket("both"), reply([PRIMARY]))),
    "add reply on a removal ticket": (lambda: (ticket("both", removal=True), reply([PRIMARY, DR]))),
    "removal reply on an add ticket": (lambda: (ticket("both"), reply([PRIMARY, DR], removal=True))),
}


@pytest.mark.parametrize("make", REFUSED.values(), ids=REFUSED.keys())
def test_a_scope_mismatch_writes_nothing(repo, make):
    before = snapshot(repo)
    with pytest.raises(ScopeError):
        apply_reply(repo, *make())
    assert changed(before, repo) == set()


def test_a_failure_at_one_site_writes_no_site(repo):
    """DR already lost the rule; a both-sites removal stops, and primary keeps it too."""
    apply_reply(repo, ticket("dr", removal=True), reply([DR], removal=True))
    before = snapshot(repo)
    with pytest.raises(DraftError, match="no rule named"):
        apply_reply(repo, ticket("both", removal=True), reply([PRIMARY, DR], removal=True))
    assert changed(before, repo) == set()


def fail_on_call(real, *n):
    """Wrap a function so its n-th calls raise OSError, as a full disk would; other calls run normally."""
    calls = []

    def wrapped(*args, **kwargs):
        calls.append(args)
        if len(calls) in n:
            raise OSError(28, "No space left on device")
        return real(*args, **kwargs)
    return wrapped


@pytest.mark.parametrize("call", [2, 4], ids=["DR backup", "DR new text"])
def test_a_disk_failure_while_staging_writes_no_site(repo, monkeypatch, call):
    """Fsync order is backups, then new texts; whichever fails, no file changes and nothing is left behind."""
    import workflow.scope as scope
    monkeypatch.setattr(scope.os, "fsync", fail_on_call(scope.os.fsync, call))
    before = snapshot(repo)
    with pytest.raises(OSError):
        apply_reply(repo, ticket("both"), reply([PRIMARY, DR]))
    assert changed(before, repo) == set()


def test_a_failed_swap_puts_the_first_file_back(repo, monkeypatch):
    """Primary is swapped in, then DR's rename fails; primary gets its old bytes back."""
    import workflow.scope as scope
    monkeypatch.setattr(scope.os, "replace", fail_on_call(scope.os.replace, 2))
    before = snapshot(repo)
    with pytest.raises(OSError):
        apply_reply(repo, ticket("both"), reply([PRIMARY, DR]))
    assert changed(before, repo) == set()


def test_a_failed_undo_reports_the_changed_file_and_keeps_its_original(repo, monkeypatch):
    """DR's rename fails, then moving primary's backup back fails too.

    Primary holds an uncommitted edit before the run. The error must name exactly the
    primary file, its backup must hold the edited bytes (not git's), DR must be
    untouched, and moving the backup over the file must restore every byte.
    """
    import workflow.scope as scope
    primary, dr = repo / SPOKE_FILE.format(PRIMARY), repo / SPOKE_FILE.format(DR)
    primary.write_text(primary.read_text() + "# an uncommitted edit by the engineer\n")
    before = snapshot(repo)
    monkeypatch.setattr(scope.os, "replace", fail_on_call(scope.os.replace, 2, 3))  # 1 primary, 2 DR, 3 undo
    with pytest.raises(PartialWriteError) as caught:
        apply_reply(repo, ticket("both"), reply([PRIMARY, DR]))
    backup = caught.value.changed[primary]
    assert list(caught.value.changed) == [primary]
    assert str(primary) in str(caught.value) and str(backup) in str(caught.value)
    assert BACKUP in backup.name and backup.parent == primary.parent and not backup.name.endswith(".tfvars")
    assert backup.read_bytes() == before[primary.relative_to(repo)]
    assert b"024-https-sett-to-northwindFs" in primary.read_bytes()
    assert dr.read_bytes() == before[dr.relative_to(repo)]
    leftover = set(snapshot(repo)) - set(before)
    assert leftover == {backup.relative_to(repo)}, "only the kept backup may be left"
    monkeypatch.undo()
    backup.replace(primary)  # the recovery the error message gives
    assert changed(before, repo) == set()


def test_a_write_keeps_the_file_mode(repo):
    """The temp file is renamed over the target, so it must carry the target's permissions."""
    path = repo / SPOKE_FILE.format(PRIMARY)
    path.chmod(0o640)
    apply_reply(repo, ticket("primary"), reply([PRIMARY]))
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("outcome", ["stop_and_ask", "already_allowed"])
def test_a_reply_that_is_not_a_draft_writes_nothing(repo, outcome):
    before = snapshot(repo)
    assert apply_reply(repo, ticket("both"), {"outcome": outcome, "rules": []}) == []
    assert changed(before, repo) == set()


def _draft_labels():
    """Every labelled request whose answer changes files, in both splits."""
    out = []
    for p in sorted((REPO / "evals" / "requests").glob("*/*.yaml")):
        request = yaml.safe_load(p.read_text())
        if request["expected"]["outcome"] == "draft":
            out.append(pytest.param(request, id=p.stem))
    return out


@pytest.mark.parametrize("request_", _draft_labels())
def test_every_labelled_answer_changes_only_its_selected_files(repo, request_):
    t, expected = request_["ticket"], request_["expected"]
    selected = selected_env_sites(repo, t)
    before = snapshot(repo)
    apply_reply(repo, t, expected)
    want = {f"infra/envs/{r['env_site']}/firewall_policy_rule_collection_groups/{r['spoke']}.tfvars"
            for r in expected["rules"]}
    assert changed(before, repo) == want
    assert {Path(w).parts[2] for w in want} == selected


def _label(number):
    """One validation request's ticket and labelled answer."""
    data = yaml.safe_load((REPO / "evals/requests/validation" / f"validation_{number}.yaml").read_text())
    return data["ticket"], data["expected"]


@pytest.mark.parametrize("number, wrong", [("RITM0011049", "ipg-ledg-prod-dr"), ("RITM0011050", "10.101.16.0/24")],
                         ids=["CIDR ticket answered with the group", "group ticket answered with the CIDR"])
def test_a_removal_in_the_other_source_type_is_refused(repo, number, wrong):
    """ipg-ledg-prod-dr holds exactly 10.101.16.0/24, yet each ticket approves only its own type."""
    t, reply_ = _label(number)
    reply_["rules"][0]["sources"] = [wrong]
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="a type the ticket does not approve"):
        apply_reply(repo, t, reply_)
    assert changed(before, repo) == set()


def typed_ticket(side, kind):
    """A prod primary-only sett add ticket whose source or destination is given as a CIDR or an IP group."""
    t = ticket("primary")
    if side == "source" and kind == "ip_group":
        t["sources"] = [{"environment": "prod", "site": "primary", "ip_group": "ipg-sett-prod"}]
    if side == "destination" and kind == "ip_group":
        t["destination"] = [{"ip_group": "ipg-partner-northwind"}]
    assert ticket_errors(t) == []
    return t


SWAPS = {  # (side, ticket type, value the reply uses instead)
    "source: CIDR approved, group used": ("source", "cidr", "ipg-sett-prod"),
    "source: group approved, CIDR used": ("source", "ip_group", SOURCE[PRIMARY]),
    "destination: CIDR approved, group used": ("destination", "cidr", "ipg-partner-northwind"),
    "destination: group approved, CIDR used": ("destination", "ip_group", NORTHWIND["destinations"][0]),
}


@pytest.mark.parametrize("side, kind, value", SWAPS.values(), ids=SWAPS.keys())
def test_an_unapproved_type_swap_is_refused(repo, side, kind, value):
    r = reply([PRIMARY])
    r["rules"][0]["sources" if side == "source" else "destinations"] = [value]
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="a type the ticket does not approve"):
        apply_reply(repo, typed_ticket(side, kind), r)
    assert changed(before, repo) == set()


@pytest.mark.parametrize("side, field, group", [("source", "source_ip_groups", "ipg-sett-prod"),
                                                ("destination", "destination_ip_groups", "ipg-partner-northwind")])
def test_a_group_the_ticket_names_is_written_as_a_group(repo, side, field, group):
    """The positive case: the ticket names the group, the reply uses it, and the file gets it as an IP group."""
    r = reply([PRIMARY])
    r["rules"][0]["sources" if side == "source" else "destinations"] = [group]
    apply_reply(repo, typed_ticket(side, "ip_group"), r)
    text = (repo / SPOKE_FILE.format(PRIMARY)).read_text()
    block = text[text.index('"024-https-sett-to-northwindFs"'):]
    assert f'{field}' in block.split("}")[0] and group in block.split("}")[0]


@pytest.mark.parametrize("value, ok", [("10.100.14.0/25", True), ("10.100.0.0/16", False), ("10.100.15.0/24", False)],
                         ids=["narrower CIDR", "wider CIDR", "other CIDR"])
def test_a_cidr_must_sit_inside_the_approved_cidr(repo, value, ok):
    r = reply([PRIMARY])
    r["rules"][0]["sources"] = [value]
    if ok:
        apply_reply(repo, ticket("primary"), r)
    else:
        with pytest.raises(ApprovalError, match="is not on the ticket"):
            apply_reply(repo, ticket("primary"), r)


def test_a_source_from_the_other_site_is_refused(repo):
    """Each env-site may use only its own approved source: the DR CIDR is not approved in a primary rule."""
    r = reply([PRIMARY, DR])
    r["rules"][0]["sources"] = [SOURCE[DR]]
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="is not on the ticket"):
        apply_reply(repo, ticket("both"), r)
    assert changed(before, repo) == set()


def test_a_dnat_rule_must_translate_to_the_tickets_host(repo):
    """For DNAT the rule's destination is the firewall; the approved internal host is the translated address."""
    t, e = _label("RITM0011020")
    e["rules"][0]["translated_address"] = "10.102.20.99"
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="translated address 10.102.20.99 is not on the ticket"):
        apply_reply(repo, t, e)
    assert changed(before, repo) == set()


ONPREM_BOTH = [{"ip_group": "ipg-onprem-primary"}, {"ip_group": "ipg-onprem-secondary"}]


def onprem_ticket(scope, side, entries):
    """A prod sett add ticket whose sources or destination are the given on-prem entries, at the chosen Azure sites."""
    t = ticket(scope)
    if side == "source":
        t["sources"] = entries
    else:
        t["destination"] = entries
    assert ticket_errors(t) == []
    return t


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("side", ["source", "destination"])
def test_both_on_prem_groups_are_usable_at_any_selected_azure_site(repo, scope, side):
    """On-prem primary and secondary groups are not tied to Azure primary or DR: both go into every selected file."""
    sites = [SITE[s] for s in SCOPES[scope]]
    r = reply(sites)
    field = "sources" if side == "source" else "destinations"
    for rule in r["rules"]:
        rule[field] = ["ipg-onprem-primary", "ipg-onprem-secondary"]
    before = snapshot(repo)
    apply_reply(repo, onprem_ticket(scope, side, ONPREM_BOTH), r)
    assert changed(before, repo) == {SPOKE_FILE.format(e) for e in sites}
    for e in sites:
        text = (repo / SPOKE_FILE.format(e)).read_text()
        block = text[text.index('"024-https-sett-to-northwindFs"'):].split("}")[0]
        assert f'{side}_ip_groups' in block and "ipg-onprem-primary" in block and "ipg-onprem-secondary" in block


ONPREM_SWAPS = {  # (side, what the ticket names, what the reply uses)
    "source: group named, user CIDR used": ("source", [{"ip_group": "ipg-onprem-primary"}], "172.20.64.0/22"),
    "source: user CIDR named, group used": ("source", [{"cidr": "172.20.64.0/22"}], "ipg-onprem-primary"),
    "source: primary named, secondary used": ("source", [{"ip_group": "ipg-onprem-primary"}], "ipg-onprem-secondary"),
    "destination: group named, user CIDR used": ("destination", [{"ip_group": "ipg-onprem-secondary"}], "172.24.64.0/22"),
    "destination: user CIDR named, group used": ("destination", [{"cidr": "172.24.64.0/22"}], "ipg-onprem-secondary"),
    "destination: secondary named, primary used": ("destination", [{"ip_group": "ipg-onprem-secondary"}], "ipg-onprem-primary"),
}


@pytest.mark.parametrize("side, entries, value", ONPREM_SWAPS.values(), ids=ONPREM_SWAPS.keys())
def test_an_on_prem_group_is_never_inferred_or_swapped(repo, side, entries, value):
    """172.20.64.0/22 is in ipg-onprem-primary and 172.24.64.0/22 in ipg-onprem-secondary; neither stands in for the other."""
    r = reply([PRIMARY])
    r["rules"][0]["sources" if side == "source" else "destinations"] = [value]
    before = snapshot(repo)
    with pytest.raises(ApprovalError):
        apply_reply(repo, onprem_ticket("primary", side, entries), r)
    assert changed(before, repo) == set()


# Ports and protocol (security register 50.20): the draft must keep the ticket's flow, not only its addresses.

def flow_ticket(protocol="TCP", ports=("443",), destination=None, removal=False):
    """A prod primary-only sett ticket with the given protocol, ports and destination."""
    t = ticket("primary", removal)
    t.update(protocol=protocol, ports=list(ports))
    if destination:
        t["destination"] = [destination]
    assert ticket_errors(t) == []
    return t


def flow_reply(protocol="TCP", ports=("443",), destination=None, removal=False):
    """The primary-only draft, with its protocol, ports and destination replaced."""
    r = reply([PRIMARY], removal)
    r["rules"][0].update(protocol=protocol, ports=list(ports))
    if str(protocol).upper() in ("HTTP", "HTTPS"):
        r["rules"][0]["collection"] = "allow-sett-app-rules"
    if destination:
        r["rules"][0]["destinations"] = [destination]
    return r


ADD_REFUSED = {  # (ticket protocol, ticket ports, reply protocol, reply ports, the refusal names)
    "extra port 3389": ("TCP", ["443"], "TCP", ["443", "3389"], "port 3389 is not within"),
    "wildcard port": ("TCP", ["443"], "TCP", ["*"], r"port \* is not within"),
    "every port as a range": ("TCP", ["443"], "TCP", ["1-65535"], "port 1-65535 is not within"),
    "range one wider": ("TCP", ["443"], "TCP", ["443-444"], "port 443-444 is not within"),
    "range past the ticket's range": ("TCP", ["1000-2000"], "TCP", ["999-1500"], "port 999-1500 is not within"),
    "port beside two ticket ports": ("TCP", ["22", "23"], "TCP", ["22-24"], "port 22-24 is not within"),
    "UDP for TCP": ("TCP", ["443"], "UDP", ["443"], "protocol UDP is not the ticket's TCP"),
    "Any for TCP": ("TCP", ["443"], "Any", ["443"], "protocol Any is not the ticket's TCP"),
    "TCP for Any": ("Any", ["443"], "TCP", ["443"], "protocol TCP is not the ticket's Any"),
    "HTTPS for TCP": ("TCP", ["443"], "HTTPS", ["443"], "protocol HTTPS is not the ticket's TCP"),
    "HTTP for HTTPS": ("HTTPS", ["443"], "HTTP", ["443"], "protocol HTTP is not the ticket's HTTPS"),
    "TCP for HTTP": ("HTTP", ["80"], "TCP", ["80"], "protocol TCP is not the ticket's HTTP"),
    "no protocol": ("TCP", ["443"], "", ["443"], r"protocol \(none\) is not"),
}


@pytest.mark.parametrize("t_proto, t_ports, r_proto, r_ports, why", ADD_REFUSED.values(), ids=ADD_REFUSED.keys())
def test_an_add_wider_than_the_tickets_ports_or_another_protocol_is_refused(repo, t_proto, t_ports, r_proto, r_ports, why):
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match=why):
        apply_reply(repo, flow_ticket(t_proto, t_ports), flow_reply(r_proto, r_ports))
    assert changed(before, repo) == set()


MALFORMED_PORTS = {
    "leading zero": ["0443"], "leading space": [" 443"], "trailing newline": ["443\n"], "decimal": ["443.0"],
    "zero": ["0"], "above 65535": ["70000"], "high to low": ["444-443"], "words": ["https"],
    "true": [True], "a JSON float": [443.0], "empty list": [], "not a list": "443", "missing": None,
}


@pytest.mark.parametrize("ports", MALFORMED_PORTS.values(), ids=MALFORMED_PORTS.keys())
def test_a_malformed_reply_port_is_refused_never_read_as_a_port(repo, ports):
    r = flow_reply()
    if ports is None:
        del r["rules"][0]["ports"]
    else:
        r["rules"][0]["ports"] = ports
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="are not written as a ticket writes ports"):
        apply_reply(repo, flow_ticket(), r)
    assert changed(before, repo) == set()


ADD_ALLOWED = {  # (ticket protocol, ticket ports, reply protocol, reply ports, destination for both)
    "same port": ("TCP", ["443"], "TCP", ["443"], None),
    "port as a JSON number": ("TCP", ["443"], "TCP", [443], None),
    "protocol in lower case": ("TCP", ["443"], "tcp", ["443"], None),
    "ticket * kept as *": ("TCP", ["*"], "TCP", ["*"], None),
    "ticket * written as 1-65535": ("TCP", ["*"], "TCP", ["1-65535"], None),
    "narrower port inside a ticket range": ("TCP", ["1000-2000"], "TCP", ["1500"], None),
    "two ticket ports as one range": ("TCP", ["22", "23"], "TCP", ["22-23"], None),
    "UDP kept": ("UDP", ["53"], "UDP", ["53"], None),
    "Any kept, any case": ("Any", ["443"], "ANY", ["443"], None),
    "ICMP kept": ("ICMP", ["*"], "ICMP", ["*"], None),
    "HTTPS to an address as a TCP network rule (RB-01-4)": ("HTTPS", ["443"], "TCP", ["443"], None),
    "HTTPS to a hostname kept as HTTPS": ("HTTPS", ["443"], "HTTPS", ["443"], "files.northwind.example"),
}


@pytest.mark.parametrize("t_proto, t_ports, r_proto, r_ports, host", ADD_ALLOWED.values(), ids=ADD_ALLOWED.keys())
def test_an_add_inside_the_tickets_flow_is_written(repo, t_proto, t_ports, r_proto, r_ports, host):
    before = snapshot(repo)
    apply_reply(repo, flow_ticket(t_proto, t_ports, host and {"fqdn": host}), flow_reply(r_proto, r_ports, host))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}


def test_https_to_a_hostname_as_a_tcp_rule_is_refused(repo):
    """RB-01-4 allows TCP only for HTTPS to an address; to a hostname it would be non-HTTP traffic to a name."""
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="protocol TCP is not the ticket's HTTPS"):
        apply_reply(repo, flow_ticket("HTTPS", destination={"fqdn": "files.northwind.example"}),
                    flow_reply("TCP", destination="files.northwind.example"))
    assert changed(before, repo) == set()


REMOVAL_REFUSED = {  # (ticket protocol, ticket ports) for a reply that deletes the TCP 587 rule, and the refusal
    "ticket asks for 443": ("TCP", ["443"], r"ports \['587'\] are not exactly the ticket's \['443'\]"),
    "ticket asks for a wider set": ("TCP", ["587", "588"], "are not exactly the ticket's"),
    "ticket asks for every port": ("TCP", ["*"], "are not exactly the ticket's"),
    "ticket asks for UDP": ("UDP", ["587"], "protocol TCP is not the ticket's UDP"),
    "ticket asks for Any": ("Any", ["587"], "protocol TCP is not the ticket's Any"),
}


@pytest.mark.parametrize("t_proto, t_ports, why", REMOVAL_REFUSED.values(), ids=REMOVAL_REFUSED.keys())
def test_a_removal_of_a_rule_for_other_ports_or_protocol_is_refused(repo, t_proto, t_ports, why):
    """The file's rule allows TCP 587; deleting it is approved only by a ticket for exactly that flow."""
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match=why):
        apply_reply(repo, flow_ticket(t_proto, t_ports, removal=True), flow_reply("TCP", ["587"], removal=True))
    assert changed(before, repo) == set()


def test_a_removal_with_the_tickets_ports_in_another_form_is_written(repo):
    """Ticket 587-587 and rule 587 name the same single port, so the rule is deleted."""
    before = snapshot(repo)
    apply_reply(repo, flow_ticket("TCP", ["587-587"], removal=True), flow_reply("TCP", ["587"], removal=True))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}


DNAT_REFUSED = {  # one field of the labelled DNAT rule changed, and the refusal
    "extra public port": ({"ports": ["22", "2222"]}, "port 2222 is not within"),
    "wildcard public port": ({"ports": ["*"]}, r"port \* is not within"),
    "translated to another port": ({"translated_port": "2222"}, "translated port '2222' is not the one port"),
    "translated to every port": ({"translated_port": "*"}, r"translated port '\*' is not the one port"),
    "UDP for TCP": ({"protocol": "UDP"}, "protocol UDP is not the ticket's TCP"),
}


@pytest.mark.parametrize("change, why", DNAT_REFUSED.values(), ids=DNAT_REFUSED.keys())
def test_a_dnat_rule_publishes_and_translates_only_the_tickets_port(repo, change, why):
    t, e = _label("RITM0011020")
    e["rules"][0].update(change)
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match=why):
        apply_reply(repo, t, e)
    assert changed(before, repo) == set()


STAGE_XFER = ["infra/envs/stage-eastus2/firewall_policy_rule_collection_groups/xfer.tfvars",
              "infra/envs/stage-centralus/firewall_policy_rule_collection_groups/xfer.tfvars"]


def dnat_from(ticket_sources, rule_sources, removal=False):
    """The labelled stage DNAT request (RITM0011020, both sites) with the ticket's and both rules' sources replaced."""
    t, e = _label("RITM0011020")
    t["sources"] = ticket_sources
    for rule in e["rules"]:
        rule["sources"] = rule_sources
    if removal:
        t["item"], e["action"] = "Firewall Rule Removal", "remove"
    return t, e


def add_ip_group(root, name, cidrs):
    """Add one IP group to both stage env-sites' ip-groups.tfvars in the copy."""
    for env_site in ("stage-eastus2", "stage-centralus"):
        path = root / "infra" / "envs" / env_site / "ip-groups.tfvars"
        text = path.read_text().rstrip()
        members = ", ".join(f'"{c}"' for c in cidrs)
        path.write_text(text[:-1] + f'  {name} = {{\n    name  = "{name}"\n    cidrs = [{members}]\n  }}\n}}\n')


OPEN_DNAT = {  # (ticket sources, reply sources): the ticket approves each, and each lets in everyone
    "0.0.0.0/0": ([{"cidr": "0.0.0.0/0"}], ["0.0.0.0/0"]),
    "padded prefix 0.0.0.0/00": ([{"cidr": "0.0.0.0/0"}], ["0.0.0.0/00"]),
    "dotted mask 0.0.0.0/0.0.0.0": ([{"cidr": "0.0.0.0/0"}], ["0.0.0.0/0.0.0.0"]),
    "host bits 8.8.8.8/0": ([{"cidr": "0.0.0.0/0"}], ["8.8.8.8/0"]),
    "two halves": ([{"cidr": "0.0.0.0/1"}, {"cidr": "128.0.0.0/1"}], ["0.0.0.0/1", "128.0.0.0/1"]),
    "hostname *": ([{"fqdn": "*"}], ["*"]),
    "IP group holding every address": ([{"ip_group": "ipg-partner-anyone"}], ["ipg-partner-anyone"]),
}


@pytest.mark.parametrize("t_sources, r_sources", OPEN_DNAT.values(), ids=OPEN_DNAT.keys())
def test_an_open_dnat_add_is_refused_even_when_the_ticket_asks(repo, t_sources, r_sources):
    """Security register 50.21: STD-COLL-04 blocks however the open source is written, and nothing is written."""
    add_ip_group(repo, "ipg-partner-anyone", ["0.0.0.0/1", "128.0.0.0/1"])
    t, e = dnat_from(t_sources, r_sources)
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match=r"source is open to everyone: .*\(STD-COLL-04, RB-02-5 open_dnat_source\)"):
        apply_reply(repo, t, e)
    assert changed(before, repo) == set()


def test_an_ipv6_open_source_is_refused_not_a_crash(repo):
    """::/0 against an IPv4 ticket range is not approved; before 2026-10-22 it raised TypeError."""
    t, e = dnat_from([{"cidr": "0.0.0.0/0"}], ["::/0"])
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match="::/0 is not on the ticket"):
        apply_reply(repo, t, e)
    assert changed(before, repo) == set()


RESTRICTED_DNAT = {  # (ticket sources, reply sources): restricted, so the draft is written
    "the partner's range": ([{"cidr": "198.51.100.80/28"}], ["198.51.100.80/28"]),
    "narrower than the ticket": ([{"cidr": "198.51.100.80/28"}], ["198.51.100.80/29"]),
    "half of every address (a caution, RB-02-6)": ([{"cidr": "0.0.0.0/1"}], ["0.0.0.0/1"]),
    "partner IP group": ([{"ip_group": "ipg-partner-wingtip"}], ["ipg-partner-wingtip"]),
}


@pytest.mark.parametrize("t_sources, r_sources", RESTRICTED_DNAT.values(), ids=RESTRICTED_DNAT.keys())
def test_a_dnat_add_with_a_restricted_source_is_written(repo, t_sources, r_sources):
    add_ip_group(repo, "ipg-partner-wingtip", ["198.51.100.80/28"])
    t, e = dnat_from(t_sources, r_sources)
    before = snapshot(repo)
    apply_reply(repo, t, e)
    assert changed(before, repo) == set(STAGE_XFER)


def test_an_existing_open_dnat_rule_can_still_be_removed(repo):
    """Deleting an open rule closes the hole, so STD-COLL-04 never blocks a removal."""
    apply_reply(repo, *dnat_from([{"cidr": "0.0.0.0/1"}], ["0.0.0.0/1"]))
    for f in STAGE_XFER:  # make the rule just written open, as if it had been added outside the workflow
        path = repo / f
        assert path.read_text().count('"0.0.0.0/1"') == 1
        path.write_text(path.read_text().replace('"0.0.0.0/1"', '"0.0.0.0/0"'))
    before = snapshot(repo)
    apply_reply(repo, *dnat_from([{"cidr": "0.0.0.0/0"}], ["0.0.0.0/0"], removal=True))
    assert changed(before, repo) == set(STAGE_XFER)
    for f in STAGE_XFER:
        text = (repo / f).read_text()
        assert "sftp-wingtip-to-xferSftp" not in text and '"0.0.0.0/0"' not in text


def test_an_open_source_in_a_network_rule_is_left_to_the_tier1_caution(repo):
    """STD-COLL-04 is about DNAT only; 0.0.0.0/0 elsewhere is a STD-COLL-02 caution the engineer sees."""
    t = flow_ticket("TCP", ["443"])
    t["sources"] = [{"cidr": "0.0.0.0/0"}]
    r = flow_reply("TCP", ["443"])
    r["rules"][0]["sources"] = ["0.0.0.0/0"]
    before = snapshot(repo)
    apply_reply(repo, t, r)
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}
