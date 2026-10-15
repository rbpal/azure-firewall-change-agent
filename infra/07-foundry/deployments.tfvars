# Values for the model deployments and laptop access. Each name is declared in
# variables.tf.

# No free tier: models bill per token. Chosen by the user on 2026-10-15 as the
# cheapest option (eastus2 retail prices, per 1M tokens, Global Standard):
#   gpt-6-luna    $0.10 input / $0.50 output  - the agent
#   gpt-5.4-mini  $0.75 input / $4.50 output  - the judge for Foundry's quality checks
# The judge is a different model from the agent, so it does not grade itself.
# Capacity caps spend: one unit is 1,000 tokens and 1 request per minute.
# Versions are pinned and never auto-upgraded, so eval scores refer to one model.
deployments = {
  "gpt-6-luna-agent" = {
    model_name    = "gpt-6-luna"
    model_version = "2026-09-22"
    sku_name      = "GlobalStandard"
    capacity      = 30
  }
  "gpt-5.4-mini-judge" = {
    model_name    = "gpt-5.4-mini"
    model_version = "2026-03-17"
    sku_name      = "GlobalStandard"
    capacity      = 10
  }
}

# You call the agent from the laptop (fwagent), so you need Foundry User on this
# resource. It replaces the hand-made assignment at subscription scope.
foundry_user_role_for_terraform_user = true
