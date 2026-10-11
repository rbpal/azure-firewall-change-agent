# Values for the federated credential. Each name is declared in variables.tf.
# Cost: free.

fic_name   = "fic-fwagentic-sync-main"
fic_issuer = "https://token.actions.githubusercontent.com"

# Only this repo's main branch may sign in. Other branches, pull requests and
# forks carry a different subject and are refused. GitHub writes the owner and
# repo with their fixed numeric IDs (rbpal@12468232, repo @1409038920), so a
# repo deleted and recreated under the same name does not match either.
fic_subject   = "repo:rbpal@12468232/azure-firewall-change-agent@1409038920:ref:refs/heads/main"
fic_audiences = ["api://AzureADTokenExchange"]
