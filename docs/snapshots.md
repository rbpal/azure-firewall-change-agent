# Network snapshots

The agent's tools never read GitHub. On every push to `main`, the `sync-network` workflow copies `data/network` and `infra/envs` into Blob storage (ADR 0003), checks the copy, and marks the commit ready for drafting (ADR 0006).

Storage account `stfwagentfuncdev`, container `network-snapshot`:

```
snapshots/<sha>/data/network/...    one folder per main commit, written once
snapshots/<sha>/infra/envs/...
ready/<sha>.json                    the ready record: file hashes, agent version, checks
current.json                        {"commit": "<sha>"} for tools called without a pinned commit
```

A snapshot of `main` holds 74 files today.

## What the sync job does

1. Uploads each file of the pushed commit once. A file that already exists must hold the same bytes.
2. Downloads every file and compares its SHA-256 with Git. A missing, extra or changed file stops the job.
3. Reuses the agent version whose definition matches the commit's instructions, or publishes a new one.
4. Reads that version back and checks its hash, its `{{snapshot}}` header and its required input. It makes no model call.
5. Writes `ready/<sha>.json` once. Any earlier failure leaves no record, so drafting waits or stops.

Every push gets a record, including commits that change only docs or tests. The job never touches a firewall policy.

## Ready for drafting is not applied in Azure

A ready record says the commit's configuration files are copied and checked, and which agent version matches its instructions. It says nothing about any firewall. Firewall changes reach Azure only through the release pipeline.

## How a draft uses a snapshot

1. `fwagent accept` fetches `origin/main` and waits up to 10 minutes for its ready record. While it waits, it checks the record and the file list.
2. It creates branch `agent/<ticket>-<commit>` at that commit, in its own worktree.
3. Right before the agent call, it downloads every snapshot file once. The branch, the ready record and Azure's files must match `main`, by commit and by each file's bytes. A mismatch sends nothing to the agent.
4. Each request supplies the commit as the `snapshot` structured input, so every tool call reads that snapshot. A reply is refused if any tool answer names another commit.
5. If `main` changes relevant files during the call, the draft is made again from the new `main`, up to 3 times.

The agent version must also be listed in `agents/evaluated-definitions.json` on `main`. Until its evaluation has passed and a reviewed pull request has added it, drafting stops.

## What is kept

A snapshot is deleted only when another commit replaced it more than 24 hours ago. A draft attempt may run 30 minutes at most, so no run loses its snapshot. Ready records are kept for the audit.

## Compare two snapshots

Reading needs `az login` and Storage Blob Data Reader on the container or the storage account; shared keys are off.

```
az storage blob list --auth-mode login --account-name stfwagentfuncdev \
  --container-name network-snapshot --prefix ready/ --num-results "*" --query "[].name" --output tsv
git diff --stat <older-sha> <newer-sha> -- data/network infra/envs
```

Each folder holds exactly its commit's files, so `git diff` between two commits shows what differs between their snapshots.

## Roll back the pointer

A manual run of `sync-network` with `rollback_to` moves `current.json` to a commit that is still ready. It uploads and deletes nothing. Drafting always follows `main`, never `current.json`.
