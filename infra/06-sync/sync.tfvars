# Values every resource in this step shares, and the names of resources built
# by earlier steps. Each name is declared in variables.tf.

resource_group_name = "rg-fwagentic-dev"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "06-sync"
}

# Built by step 05-func, read in data.tf.
storage_account_name = "stfwagentfuncdev"
