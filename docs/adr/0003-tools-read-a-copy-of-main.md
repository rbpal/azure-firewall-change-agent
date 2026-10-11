# ADR 0003: The tools read a copy of main, not GitHub

- **Status:** Accepted
- **Date:** 2026-10-11

## The problem

The agent's tools answer from files in `main`: the network data in `data/network/` and the firewall rules in `infra/envs/`. The tools run in an Azure Function app. The app has no copy of the repo.

So the tools need a way to read `main`. The project rule is no secrets: managed identity and federated credentials only.

## What we decided

A GitHub Actions job copies those files into a private blob container on every push to `main`. The tools read the container.

1. **The job signs in with no secret.** It asks GitHub for a signed token that names the repo and branch. Azure accepts it only for `repo:rbpal/azure-firewall-change-agent:ref:refs/heads/main`, through a federated credential on the identity `uami-fwagentic-sync-dev`.
2. **The job can write to one container only.** Its role, Storage Blob Data Contributor, is scoped to `network-snapshot`.
3. **A copy is never read half-written.** The job uploads files under `snapshots/<commit>/`, then points `current.json` at that commit. A tool reads `current.json` once per call and reads every file from that commit.
4. **Every answer names its commit.** The approval step compares it with the latest `main` and re-checks if `main` has moved.

The Function app reads the container with its own managed identity. Step `infra/06-sync` builds this.

## Why

1. **No secret anywhere.** Nothing to leak, store or rotate.
2. **No rate limit.** Blob reads have no limit this project can reach. One duplicate check reads about 8 files.
3. **Free.** The container sits in the existing step 05 storage account and holds a few KB per copy.

## What we did not choose

1. **A read-only GitHub App with its key in Key Vault.** The tool reads the key, signs a JWT that lasts at most 10 minutes, swaps it for an installation token that lasts one hour, and calls the GitHub API. It reads `main` live, with 5,000 requests an hour. It costs one private key to guard and rotate, and Key Vault has no free tier. This is the right choice when a tool must read `main` live.
2. **Anonymous reads of the public repo.** GitHub allows 60 requests an hour per IP address, which is about 7 duplicate checks an hour. It also stops working if the repo goes private.
3. **A personal access token.** A secret tied to one person's account, usually with more reach than needed.

## What this costs us

1. **The copy is about a minute behind `main`.** The commit on every answer, checked at approval, covers this.
2. **If the sync job fails, the tools answer from the last good copy.** The commit check catches this too.
3. **One more workflow to maintain.**

## What would change our mind

A tool that must read `main` live, with no lag at all. Then option 1, the GitHub App, replaces the copy.
