"""BlobSource: reads the copy of main that the sync job writes to Blob storage.

Example: current.json says {"commit": "2cdc49a..."}, so read("data/network/routing.yaml")
returns snapshots/2cdc49a.../data/network/routing.yaml from the network-snapshot container.

The deployed tools have no repo checkout, so they read this copy instead (ADR 0003).
It reads current.json once, on the first read of a call, and takes every file from that
commit. A push in the middle of a call can never mix two versions of main.

Safety rule: read-only. It signs in with the Function app's managed identity; no keys.
"""

import json
import os
import re
from functools import lru_cache

from azure.core.exceptions import ResourceNotFoundError

from data_readers.read_addressplan_routing import NetworkDataError

SNAPSHOT_CONTAINER = "network-snapshot"
POINTER = "current.json"
_COMMIT = re.compile(r"^[0-9a-f]{40}$")


class BlobSource:
    """Reads repo files from one commit of the snapshot container."""

    def __init__(self, container):
        """Keep the container client; nothing is read until the first read or commit."""
        self._container = container
        self._commit = None

    @property
    def commit(self) -> str:
        """The commit this call reads from, taken from current.json on first use."""
        if self._commit is None:
            try:
                pointer = json.loads(self._download(POINTER))
            except ValueError as exc:
                raise NetworkDataError(f"{POINTER} is not valid JSON") from exc
            commit = pointer.get("commit") if isinstance(pointer, dict) else None
            if not isinstance(commit, str) or not _COMMIT.match(commit):
                raise NetworkDataError(f"{POINTER} does not hold a full commit SHA")
            self._commit = commit
        return self._commit

    def read(self, path: str) -> str:
        """Return one repo file, as text, from this call's commit."""
        if not isinstance(path, str) or path.startswith("/") or ".." in path.split("/") or not path:
            raise NetworkDataError(f"refused path {path!r}")
        return self._download(f"snapshots/{self.commit}/{path}").decode("utf-8")

    def _download(self, name: str) -> bytes:
        """Download one blob; a missing blob is a data error, not a crash."""
        try:
            return self._container.download_blob(name).readall()
        except ResourceNotFoundError as exc:
            raise NetworkDataError(f"{name} is not in the snapshot container") from exc


@lru_cache(maxsize=1)
def snapshot_container():
    """Build the container client once per app instance, signed in as the app's managed identity."""
    from azure.identity import ManagedIdentityCredential
    from azure.storage.blob import ContainerClient

    account = os.environ["AzureWebJobsStorage__accountName"]
    return ContainerClient(f"https://{account}.blob.core.windows.net", SNAPSHOT_CONTAINER,
                           credential=ManagedIdentityCredential())


def snapshot_source() -> BlobSource:
    """Return a fresh BlobSource for one tool call; it does no network work until read."""
    return BlobSource(snapshot_container())
