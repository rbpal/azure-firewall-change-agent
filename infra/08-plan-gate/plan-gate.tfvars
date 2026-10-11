# Values every resource in this step shares, and the names of resources built
# by earlier steps. Each name is declared in variables.tf.

resource_group_name = "rg-fwagentic-dev"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "08-plan-gate"
}

# Built by the step 01 bootstrap, read in data.tf.
state_resource_group_name  = "rg-terraform-state"
state_storage_account_name = "stfwagentstaterbpal"
state_container_name       = "tfstate"

# The env-site roots keep their state as envs-<env>-<region>.tfstate.
state_blob_prefix = "envs-"
