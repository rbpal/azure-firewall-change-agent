# Values for the function app, plus the values every resource in this step
# shares and the names of resources built by earlier steps.
# Each name is declared in variables.tf.

resource_group_name = "rg-fwagentic-dev"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "05-func"
}

# Built by earlier steps, read in data.tf.
vnet_name   = "vnet-fwagentic-dev"
subnet_name = "snet-func-dev"
appi_name   = "appi-fwagentic-dev"

func_name            = "func-fwagentic-dev"
func_runtime_name    = "python"
func_runtime_version = "3.11"

# Cost: Flex Consumption bills memory-seconds after a free monthly grant of
# 100,000 GB-s. 512 MB is the smallest size, so the grant covers about
# 200,000 seconds of run time a month. No always-ready instances, so an idle
# app costs nothing.
func_instance_memory_in_mb = 512

# Caps scale-out so a runaway cannot multiply the bill.
func_maximum_instance_count = 40
