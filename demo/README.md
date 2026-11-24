# Demo scripts

The scripts behind the README walkthrough. Run each from the repo's top folder; `uv run` uses the project's Python and packages.

| Step | Command |
|---|---|
| 1 | `uv run python demo/scripts/step_01_01_make_demo_network_ticket.py` |
| 2 | `uv run python demo/scripts/step_02_create_branch_for_demo_ticket.py` |
| 3 | `uv run python demo/scripts/step_03_verify_and_sync_main_to_azure_storage.py` |
| 4 | `uv run python demo/scripts/step_04_verify_and_submit_to_foundry.py` |
| 5 | `uv run python demo/scripts/step_05_write_draft_rules_to_dev_tfvars.py` |
| 9 | `uv run python demo/scripts/step_09_archive_ticket.py` |

Steps 6–8 (pull request, merge, apply) run by hand with git, gh and Terraform.

| Folder | Holds |
|---|---|
| `01-waiting/` | new tickets (step 1) |
| `02-submit/` | the accepted ticket and the agent's reply (step 4) |
| `03-pr-description/` | the PR description (step 6) |
| `04-archive/` | finished tickets (step 9) |
| `05-pr-abandoned/` | tickets that did not finish |

Git keeps the folders but ignores their contents.

`04-archive/024-2026-11-24-RITM0013525-rprt-to-wikipedia-tcp443/` holds the walkthrough's finished ticket: the ticket, the request sent to the agent, the run record and the PR description. Personal details and file hashes are removed. All names and addresses are synthetic.

Set `ENGINEER` (steps 4, 5) and `ASSIGNEE` (`scripts/demo_ticket.py`) to your GitHub login first.
