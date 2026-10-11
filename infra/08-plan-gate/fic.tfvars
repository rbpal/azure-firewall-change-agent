# Values for the federated credential. Each name is declared in variables.tf.
# Cost: free.

fic_name   = "fic-fwagentic-tf-plan-pr"
fic_issuer = "https://token.actions.githubusercontent.com"

# Only pull requests in this repo may sign in. GitHub gives pull requests from
# forks no token, so outsiders cannot use it. The owner and repo carry their
# fixed numeric IDs, as in step 06.
fic_subject   = "repo:rbpal@12468232/azure-firewall-change-agent@1409038920:pull_request"
fic_audiences = ["api://AzureADTokenExchange"]
