"""data_readers/blob_source.py, the reader of the copy of main in Blob storage.
A fake container stands in for Azure and records every download, so each test
can fail if BlobSource reads the wrong blob, mixes commits, or reads too early."""

import json
from pathlib import Path

import pytest
from azure.core.exceptions import ResourceNotFoundError

from data_readers import blob_source
from data_readers.blob_source import BlobSource
from data_readers.read_addressplan_routing import ADDRESS_PLAN, ROUTING, LocalSource, NetworkDataError
from tools.duplicate_rule_check import duplicate_rule_check
from tools.locate_address_for_env_site import locate_address_for_env_site

REPO = Path(__file__).resolve().parents[2]
SHA_A = "a" * 40
SHA_B = "b" * 40


class FakeContainer:
    """Blobs in a dict; download_blob mimics the SDK, including ResourceNotFoundError."""

    def __init__(self, blobs: dict):
        self.blobs = dict(blobs)
        self.downloads = []

    def download_blob(self, name):
        """Return an object whose readall() gives the blob's bytes."""
        self.downloads.append(name)
        if name not in self.blobs:
            raise ResourceNotFoundError(f"{name} not found")
        data = self.blobs[name]
        return type("Downloader", (), {"readall": lambda self: data})()


def pointer(commit) -> bytes:
    """Build current.json as the sync job writes it."""
    return json.dumps({"commit": commit}).encode()


def snapshot_of_repo(commit: str) -> dict:
    """Copy the repo's data files into blobs under snapshots/<commit>/, as the sync job does."""
    blobs = {"current.json": pointer(commit)}
    for folder in ("data/network", "infra/envs"):
        for p in (REPO / folder).rglob("*"):
            if p.is_file():
                blobs[f"snapshots/{commit}/{p.relative_to(REPO).as_posix()}"] = p.read_bytes()
    return blobs


def test_read_takes_the_file_from_the_pointed_commit():
    c = FakeContainer({"current.json": pointer(SHA_A), f"snapshots/{SHA_A}/{ROUTING}": b"hubs: []\n"})
    s = BlobSource(c)
    assert s.read(ROUTING) == "hubs: []\n"
    assert s.commit == SHA_A
    assert c.downloads == ["current.json", f"snapshots/{SHA_A}/{ROUTING}"]


def test_nothing_is_read_until_first_use():
    """Built before gate 2 in function_app.py, so construction must not touch storage."""
    c = FakeContainer({"current.json": pointer(SHA_A)})
    BlobSource(c)
    assert c.downloads == []


def test_pointer_is_read_once_per_call_even_if_main_moves():
    c = FakeContainer({"current.json": pointer(SHA_A),
                       f"snapshots/{SHA_A}/{ROUTING}": b"old", f"snapshots/{SHA_B}/{ROUTING}": b"new"})
    s = BlobSource(c)
    assert s.read(ROUTING) == "old"
    c.blobs["current.json"] = pointer(SHA_B)  # a push lands mid-call
    assert s.read(ROUTING) == "old"
    assert s.commit == SHA_A
    assert c.downloads.count("current.json") == 1


def test_a_new_source_sees_the_new_commit():
    c = FakeContainer({"current.json": pointer(SHA_B)})
    assert BlobSource(c).commit == SHA_B


@pytest.mark.parametrize("body", [b"not json", b"[]", b"{}", json.dumps({"commit": "abc123"}).encode(),
                                  json.dumps({"commit": "A" * 40}).encode(), json.dumps({"commit": 7}).encode()])
def test_bad_pointer_is_a_data_error(body):
    with pytest.raises(NetworkDataError):
        BlobSource(FakeContainer({"current.json": body})).commit


def test_missing_pointer_is_a_data_error():
    with pytest.raises(NetworkDataError, match="current.json is not in the snapshot"):
        BlobSource(FakeContainer({})).commit


def test_missing_file_is_a_data_error():
    with pytest.raises(NetworkDataError, match="is not in the snapshot"):
        BlobSource(FakeContainer({"current.json": pointer(SHA_A)})).read(ROUTING)


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../current.json", "data/../../x", None])
def test_paths_outside_the_snapshot_are_refused_before_any_download(path):
    c = FakeContainer({"current.json": pointer(SHA_A)})
    with pytest.raises(NetworkDataError, match="refused path"):
        BlobSource(c).read(path)
    assert c.downloads == []


def test_container_client_targets_the_snapshot_container(monkeypatch):
    monkeypatch.setenv("AzureWebJobsStorage__accountName", "stexample")
    blob_source.snapshot_container.cache_clear()
    try:
        client = blob_source.snapshot_container()
        assert client.container_name == "network-snapshot"
        assert client.account_name == "stexample"
        assert type(client.credential).__name__ == "ManagedIdentityCredential"
    finally:
        blob_source.snapshot_container.cache_clear()


# --- the tools give the same answer from blobs as from the repo ----------

def test_locate_address_answers_the_same_from_blobs():
    args = {"address": "10.100.20.14"}
    local = locate_address_for_env_site(None, args, source=LocalSource(REPO))
    blob = locate_address_for_env_site(None, args, source=BlobSource(FakeContainer(snapshot_of_repo(SHA_A))))
    assert blob["source"] == {"files": [ADDRESS_PLAN, ROUTING], "commit": SHA_A}
    local.pop("source"), blob.pop("source")
    assert blob == local


def test_duplicate_rule_check_answers_the_same_from_blobs():
    """One spoke's DNS rule, already allowed by the hub's DNS rule, so both must find the match."""
    args = {"env_site": "dev-eastus2", "type": "network",
            "rule": {"protocols": ["UDP"], "source_addresses": ["10.104.14.0/24"],
                     "destination_addresses": ["10.104.1.4/32"], "destination_ports": ["53"]}}
    local = duplicate_rule_check(None, args, source=LocalSource(REPO))
    blob = duplicate_rule_check(None, args, source=BlobSource(FakeContainer(snapshot_of_repo(SHA_A))))
    assert blob["already_allowed"] and blob["matches"][0]["key"] == "001-dns-spokes-to-hubDns"
    assert blob["source"]["commit"] == SHA_A
    local["source"].pop("commit"), blob["source"].pop("commit")
    assert blob == local
