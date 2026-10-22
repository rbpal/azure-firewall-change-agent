# Network snapshots

The agent's tools never read GitHub. On every push to `main`, the `sync-network` workflow copies `data/network` and `infra/envs` into Blob storage (ADR 0003). Each copy is a folder named after its commit. A small file, `current.json`, names the folder the tools read.

Storage account `stfwagentfuncdev`, container `network-snapshot`:

```
current.json                       {"commit": "<40-character SHA>"}
snapshots/<sha>/data/network/...
snapshots/<sha>/infra/envs/...
```

## What is kept

Two snapshots: the one `current.json` names, and the one before it. Older folders are deleted at the end of each sync from a push. The sync never deletes the folder `current.json` names, and a rollback deletes nothing.

Before `current.json` moves, the sync checks that the folder holds exactly the commit's tracked files (`git ls-tree` of that commit). A missing or extra file stops the sync, and the pointer stays where it was.

## How a run uses a snapshot

1. The eval runner reads `current.json` and checks the folder against that commit's file list, the same check the sync makes.
2. It refuses to start when this checkout's `data/network` or `infra/envs` differ from that commit, whether the difference is committed, uncommitted or an untracked file. The labels and the tools must rest on one revision. `evals/README.md` describes `--data-diff-ok`, which names a differing file the run may ignore.
3. It pins that commit for the whole run. Every tool call sends it in the `X-Fwagent-Snapshot` header, and a reply is refused if any tool answer names another commit.

An invalid snapshot, or one that is not the required commit (`FWAGENT_SNAPSHOT_COMMIT`, when set), stops the run. The previous snapshot is never used instead.

## No push during a controlled run

Nothing records which runs are active. A push during a run would sync a new commit and could delete the folder the run has pinned. Finish the run before pushing.

## Compare two snapshots

Reading needs `az login` and Storage Blob Data Reader on the container or the storage account; shared keys are off.

```
az storage blob download --auth-mode login --account-name stfwagentfuncdev \
  --container-name network-snapshot --name current.json --file /dev/stdout --no-progress --output none
az storage blob list --auth-mode login --account-name stfwagentfuncdev \
  --container-name network-snapshot --prefix snapshots/ --num-results "*" \
  --query "[].name" --output tsv | cut -d/ -f2 | sort -u
git diff --stat <older-sha> <newer-sha> -- data/network infra/envs
```

The folders hold exactly each commit's files, so `git diff` between the two commits shows what differs between the two snapshots.

## Roll back the pointer

Rollback moves `current.json` to a kept snapshot. It uploads nothing and deletes nothing.

1. In GitHub, run the `sync-network` workflow on `main` with `rollback_to` set to the full 40-character SHA of a kept snapshot.
2. The workflow refuses anything that is not a full SHA of a commit on `main`. It checks the folder against that commit's file list before moving the pointer.
3. Check `current.json` names the commit (first command above).
4. Before another run, check out that commit's data, so the checkout and the snapshot match:

```
git worktree add ../fwagent-at-<short-sha> <sha>
```

Run the eval from that worktree. The worktree holds that commit's code and eval labels too, not only its data. The next push to `main` syncs that push's commit and moves the pointer forward again.
