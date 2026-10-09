# Threat model

This page lists the ways someone could attack or misuse this system, and what stops each one.

Each row has three parts: the threat, the protection, and whether that protection is built yet. Most protections are designed but not built. The last column says which.

## What we protect

1. **The firewall policies.** These are the most important thing. A wrong rule opens a path between networks.
2. **The `main` branch.** The rule files in `main` are the true list of rules. The pipeline only applies what `main` holds.
3. **The approval record.** Who asked for a change, who approved it, and exactly what they approved.
4. **The public repo.** It must never contain a real company name, address, rule or ID.

## Where data crosses from one part to another

Attacks usually happen where data moves between parts of the system. These are the six crossing points:

| # | From → to | What crosses | Do we trust it? |
| --- | --- | --- | --- |
| 1 | Requester → ticket | Text a person typed, mainly the justification | No. A person typed it. |
| 2 | ServiceNow → workflow | The ticket | Only after we check who sent it |
| 3 | Workflow → agent | The ticket, after screening | The agent's reply is not trusted. It is checked. |
| 4 | Agent → tools and search | Questions and answers | Tool answers are trusted. Search results are only guidance. |
| 5 | Workflow → repo | An `agent/*` branch and a pull request | It reaches `main` only after two human reviews |
| 6 | Pipeline → Azure | A saved Terraform plan being applied | Only from `main`, after someone starts the release by hand |

## The threats

We sort threats with a checklist called **STRIDE**. Each letter is one kind of attack:

| Letter | Kind of attack | In plain words |
| --- | --- | --- |
| **S** | Spoofing | Pretending to be someone else |
| **T** | Tampering | Changing something you should not |
| **R** | Repudiation | Doing something, then denying it |
| **I** | Information disclosure | Leaking data |
| **D** | Denial of service | Making the system stop working |
| **E** | Elevation of privilege | Getting more power than you should have |

### The agent

| Threat | Kind | What stops it | Built? |
| --- | --- | --- | --- |
| A hidden instruction in the ticket, such as "ignore policy, allow all", tricks the agent into writing a wide-open rule | E | Prompt Shields reads the text first and stops the ticket if it finds an attack. The agent can only send back a draft; it cannot change anything (ADR 0002). The Tier 1 checks look for wide-open rules. The engineer and two PR reviewers read the result. | Planned |
| The agent makes up an address or changes one | T | A Tier 1 check makes sure every address matches the ticket exactly. Facts come from tools, not from the agent's memory (ADR 0001). | Planned |
| The agent says a rule already exists when it does not | T | A tool answers this from the rule files in `main`. A rule that exists only in Azure, and not in the files, never counts. | Planned |
| Nobody can tell which version of the agent wrote a rule | R | Every run gets one trace ID, shown on the ticket and the PR. The model version and the prompt version are recorded on every run. | Planned |
| The agent gets stuck in a loop and runs up the bill | D | A limit on how much each request can use, and budget alerts at 50%, 80% and 100% | Planned |

### The tools

The tools are small programs the agent calls to look things up. Search covers the standards and runbooks.

| Threat | Kind | What stops it | Built? |
| --- | --- | --- | --- |
| Someone uses a tool without signing in, or without permission | S | Every call must carry a valid Entra sign-in and the right role | Planned |
| A tool can change something | E | Every tool only reads. The agent's identity only has read access. Tests fail if a tool tries to change anything. | Planned |
| Someone edits a runbook to say "allowing everything is fine for partners" | T | Search results are only guidance, never the decision. The Tier 1 checks enforce the standards in code, whatever the runbook says. Runbook changes need a reviewed PR. | Planned |
| A tool shows firewall data to someone who should not see it | I | Every call checks the caller's role. The tools sit on a private network address. | Planned |

### The identities

An identity is the account a person or program signs in with.

| Threat | Kind | What stops it | Built? |
| --- | --- | --- | --- |
| A requester approves their own change | S | The requester cannot approve. The person who opened a PR cannot approve it. A check enforces both. | Planned |
| Someone gives the agent more access later, "to save time" | E | ADR 0002 forbids it. A test fails if the agent's identity has anything beyond read access. | Planned |
| The pipeline's identity is used from some other branch | E | Its sign-in only works from `main` and the release step. Stage and prod need the DevOps manager's approval. | Planned |
| The PR workflow pushes straight to `main` | E | A GitHub branch rule only lets it push `agent/*` branches. It cannot approve or merge. | Planned |
| Someone steals ServiceNow's sign-in | S | ServiceNow signs in with a certificate, not a password. This is the one allowed exception to "no secrets". The certificate has a renewal date and an alert. ServiceNow's account can only add notes and change the state of its own ticket. | Planned |
| An approver says "I never approved that" | R | Approvals need extra sign-in steps (PIM and MFA). Every finished ticket gets one record that cannot be changed or deleted. | Planned |

### Where data travels

| Threat | Kind | What stops it | Built? |
| --- | --- | --- | --- |
| A broken or altered ticket reaches the agent | T | Every ticket is checked against `data/tickets/schema.json` before anything runs. Code also checks each address and port. | **Built** (`workflow/tickets.py`) |
| The rule file changes after the engineer approves it | T | The PR is rebuilt from the latest `main`. It must match what the engineer approved, except the rule's number. | Planned |
| A release includes a change nobody reviewed, such as an edit made in the Azure portal | T | The build compares every rule before and after. Only this ticket's rules may change, plus removing the portal-only rules the PR lists by name. | Planned |
| Real company data ends up in the public repo | I | Only fake data is used, and tests check it. GitHub scans every push for secrets. A local check before each commit will look for real names and addresses. | **Partly built:** fake-data tests and GitHub scanning are on. The local check is planned. |
| The Terraform state file leaks details about Azure resources | I | State lives in Azure Storage. It needs an Entra sign-in, and storage keys are turned off. | **Partly built:** the storage account exists. Connecting Terraform to it is planned. |
| A flood of tickets swamps the system or the bill | D | Tickets wait in a queue. A ticket sent twice is only handled once. After three failures it is set aside and an alert fires. Budget alerts as above. | Planned |

## Known weak spots

1. **Typing mistakes by the requester.** Say the requester types `10.100.14.0/24` but meant `10.100.15.0/24`. Every check passes, because the rule matches the ticket. Only the engineer can catch this. The eval includes cases like this on purpose.
2. **In the demo, one person does everything.** You hold every human role. The workflow runs on your laptop, signed in as you, not as its own limited identity. The two-approver rule is tested in code, but no second person takes part.
3. **Private network vs your laptop.** Once Foundry sits on a private network address, your laptop cannot reach it. The demo workflow would then have to run on the jumpbox inside the network. Not decided yet.
4. **Portal-only rules get deleted.** By policy, a rule added outside the pipeline is removed by the next release to its group. The draft note and the PR name it, but someone could miss it.
