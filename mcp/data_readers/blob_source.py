"""BlobSource: reads the copy of main that the sync job writes to Blob storage.

Example: current.json says {"commit": "2cdc49a..."}, so read("data/network/routing.yaml")
returns snapshots/2cdc49a.../data/network/routing.yaml from the network-snapshot container.

The deployed tools have no repo checkout, so they read this copy instead (ADR 0003).
It reads current.json once, on the first read of a call, and takes every file from that
commit. A push in the middle of a call can never mix two versions of main.

A caller can pin one commit for a whole ticket with the X-Fwagent-Snapshot header. Then
current.json is never read, and every call of that ticket reads the same snapshot, even if
main moves between calls. Only a full commit SHA is accepted, and only a snapshot the sync
job uploaded can be read; the sync job keeps the newest two.

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
SNAPSHOT_HEADER = "x-fwagent-snapshot"


class BlobSource:
    """Reads repo files from one commit of the snapshot container."""

    def __init__(self, container, commit: str | None = None):
        """Keep the container client and any pinned commit; nothing is read until the first read."""
        if commit is not None and not (isinstance(commit, str) and _COMMIT.fullmatch(commit)):
            raise NetworkDataError("a pinned snapshot must be a full commit SHA")
        self._container = container
        self._commit = commit

    @property
    def commit(self) -> str:
        """The commit this call reads from, taken from current.json on first use."""
        if self._commit is None:
            try:
                pointer = json.loads(self._download(POINTER))
            except ValueError as exc:
                raise NetworkDataError(f"{POINTER} is not valid JSON") from exc
            commit = pointer.get("commit") if isinstance(pointer, dict) else None
            if not isinstance(commit, str) or not _COMMIT.fullmatch(commit):
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


def snapshot_source(commit: str | None = None) -> BlobSource:
    """Return a fresh BlobSource for one tool call, pinned to commit if given; it does no network work until read."""
    return BlobSource(snapshot_container(), commit)


def pinned_commit(context: dict) -> str | None:
    """The commit the caller pinned in the X-Fwagent-Snapshot header, or None when there is no header."""
    def get(mapping, key):
        """Case-insensitive lookup, as the extension may change header casing."""
        return next((v for k, v in mapping.items() if isinstance(k, str) and k.lower() == key), None) \
            if isinstance(mapping, dict) else None
    headers = get(get(get(context, "transport"), "properties"), "headers")
    value = get(headers, SNAPSHOT_HEADER)
    return None if value is None else str(value).strip().lower()
