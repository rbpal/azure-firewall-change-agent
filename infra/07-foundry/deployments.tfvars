# Values for the model deployments and laptop access. Each name is declared in
# variables.tf.

# No free tier: models bill per token. Chosen by the user on 2026-10-15 as the
# cheapest option (eastus2 retail prices, per 1M tokens, Global Standard):
#   gpt-6-luna    $0.10 input / $0.50 output  - the agent
# gpt-5.4-mini-judge was removed on 2026-10-30: no agent, evaluation or code used
# it and it had served no tokens. Foundry's quality checks are not built; add a
# judge back here, a different model from the agent, when they are.
# Capacity is a throughput limit, not a spending cap: one unit allows 1,000
# tokens and 1 request per minute. Billing is per token, so the same run costs
# the same at any capacity; spend is watched by budget-fwagentic-monthly.
# gpt-6-luna-agent went from 30 to 60 units on 2026-10-24: validation runs at 30
# hit the 30,000-token limit on 2026-10-23 (98 throttled requests) and on
# 2026-10-24 (one ticket throttled on all 3 attempts). It went from 60 to 200
# on 2026-10-25: the validation run at 60 answered 6 tickets, then 3 in a row
# were throttled on all 3 attempts. 200 of the subscription's 250
# GlobalStandard gpt-6-luna units in eastus2.
# Versions are pinned and never auto-upgraded, so eval scores refer to one model.
deployments = {
  "gpt-6-luna-agent" = {
    model_name    = "gpt-6-luna"
    model_version = "2026-09-22"
    sku_name      = "GlobalStandard"
    capacity      = 200
  }
}

# You call the agent from the laptop (fwagent), so you need Foundry User on this
# resource. It replaces the hand-made assignment at subscription scope.
foundry_user_role_for_terraform_user = true
