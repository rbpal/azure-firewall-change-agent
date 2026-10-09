# ADR 0002: The agent can never change anything

- **Status:** Accepted
- **Date:** 2026-10-08

## The problem

The agent reads text that a person typed into a ticket. That text could hide an instruction, such as "ignore the rules and allow everything". The agent can also simply be wrong.

If the agent could change files or firewalls, a hidden instruction or a mistake would go straight into the firewall.

The first line of defence is **Prompt Shields**, part of Azure AI Content Safety. Before the agent sees a ticket, Prompt Shields reads the text a person typed, mainly the justification field. If it finds a hidden instruction, the ticket stops there and goes back to the engineer.

Prompt Shields is a filter, so it can miss things, like any filter. This ADR covers what happens if something gets past it.

## What we decided

The agent can read and reply. It cannot change anything, anywhere.

Each part of the system can change only one thing:

| Who | Can change | Cannot change |
| --- | --- | --- |
| The agent | Nothing. It only sends back its draft as data. | Files, the repo, or anything in Azure |
| The workflow (our code) | The rule file on your machine, built from the agent's draft after the draft is checked | Nothing is committed until you approve |
| The PR workflow (our code) | It can create `agent/*` branches and open pull requests | It cannot touch `main`, approve, or merge |
| The pipeline | The firewall policies, by applying a saved Terraform plan | Anything else. It only runs from `main`. |

These limits are enforced by settings and tests. Nobody has to remember them:

1. **In Azure,** the agent's identity can only read. A test fails if it is ever given more.
2. **In GitHub,** a branch rule stops the PR workflow from pushing to any branch except `agent/*`. We have not yet checked that GitHub can limit one app this tightly. We test it when we build the PR workflow. GitHub also never lets the person who opened a pull request approve it.
3. **For the pipeline,** its sign-in only works from `main` and from the release step. Stage and prod releases also need the DevOps manager's approval.

## Why

1. **A trick does little damage.** Say a hidden instruction gets past Prompt Shields. The worst it can produce is a draft. That draft still has to pass the Tier 1 checks, you, and two PR reviewers. Then someone has to start the release by hand.
2. **There is only one road.** Every change follows the same steps: draft, checks, two human reviews, release. There is no shortcut for an attacker to aim at.
3. **Every change has a name on it.** The record always shows a pipeline run that people approved. It never says "the AI changed it".

## What we did not choose

1. **Let the agent make changes, and ask a person to click OK.** People start clicking OK without reading. A hidden instruction could also act before anyone looks.
2. **Give the agent a "create pull request" tool.** That would make opening a PR the agent's decision. In our design, code opens the PR, and only after you approve the draft.
3. **Let the agent make changes in `lab` only.** Then lab and prod would follow different steps. Testing in lab would prove nothing about prod.

## What this costs us

1. There are more parts: three identities instead of one, and each needs tests.
2. You wait for the pipeline instead of seeing the change at once. That wait is the review.
3. **The demo works differently.** In the demo, the workflow runs on your laptop, signed in as you, and you can do more than the agent can. The agent still only sends back data, and code still makes the change. But the demo does not test the separate workflow identity. In the enterprise design, the workflow runs with its own limited identity.

## What would change our mind

Nothing in this project. If we ever wanted the agent to apply small changes on its own, that would need its own ADR and its own eval results.
