# ADR 0006: Draft from main, with the snapshot supplied per request

- **Status:** Proposed
- **Date:** 2026-11-03

## The problem

Each agent version carried its snapshot commit in a fixed header. Every merge that changed the network data needed a new agent version. Engineers had to type commits and pick versions, and the ticket path published versions.

The org handles about 50 firewall tickets a month. That figure is an estimate, not a measurement. Most tickets end in a merge that changes a rule file, so the old design would have needed up to about 50 agent versions a month, fewer when merges are batched.

## What we decided

1. **GitHub `main` is the source of truth.** Every draft starts from the latest `origin/main`, on its own branch.
2. **The snapshot travels with each request.** The version's header is `X-Fwagent-Snapshot: {{snapshot}}`, a required structured input. A live probe on 2026-11-03 confirmed it works with the managed-identity connection: one version read two different snapshots, a request without the value was refused with HTTP 400, and a malformed value was refused by the tool server.
3. **Only the sync job publishes.** It marks each `main` commit ready after checking every file's bytes and reading the agent version back.
4. **A check right before each call** compares the ticket branch, the ready record and Azure's files with `main`, by commit and by bytes.
5. **An evaluation gate.** Drafting uses only definitions listed in `agents/evaluated-definitions.json` on `main`. An entry is added by a reviewed pull request after the evaluation passes. The register is not part of the definition, so adding an entry does not change its hash.

## What we did not choose

1. **One agent version per snapshot.** It needs no unproven feature, but it creates a version for every data merge and puts publishing on every merge.
2. **The local checkout's commit.** The checkout may be behind `main` or edited.
3. **Leases on snapshots.** Engineers would need write access to the container, and crashed runs would leave leases behind. A 30-minute run limit against a 24-hour grace period gives the same guarantee.
4. **A canary model call on every deploy.** It would prove the header reaches the tools once per merge, at about one model call each time. The probe proved the mechanism, and every real draft checks that each tool answer names the pinned commit, so the sync job reads the version back instead.

## What this costs us

1. The sync identity can publish agent versions. This needs a security-register row.
2. Each draft attempt downloads every snapshot file once, 74 small files today, to check them.
3. A new definition cannot draft until its evaluation passes and its register entry is merged.
4. A change to the header mechanism is caught by the first real draft, not by the deploy.
