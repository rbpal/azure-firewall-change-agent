# Values for the plan identity. Each name is declared in variables.tf.
# Cost: user-assigned managed identities and role assignments are free,
# conditions included.

uami_name = "uami-fwagentic-tf-plan-dev"

# Read only. Reader cannot change a resource or read secrets such as keys.
uami_resource_group_role = "Reader"

# Read only, and only the envs-* state files (see the condition in main.tf).
uami_state_role = "Storage Blob Data Reader"
