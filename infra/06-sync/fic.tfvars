# Values for the federated credential. Each name is declared in variables.tf.
# Cost: free.

fic_name   = "fic-fwagentic-sync-main"
fic_issuer = "https://token.actions.githubusercontent.com"

# Only this repo's main branch may sign in. Other branches, pull requests and
# forks carry a different subject and are refused.
fic_subject   = "repo:rbpal/azure-firewall-change-agent:ref:refs/heads/main"
fic_audiences = ["api://AzureADTokenExchange"]
