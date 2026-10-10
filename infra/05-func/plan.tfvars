# Values for the hosting plan. Each name is declared in variables.tf.

plan_name    = "asp-fwagentic-dev"
plan_os_type = "Linux"

# Cost: FC1 is Flex Consumption. 250,000 executions and 100,000 GB-s a month
# are free; there is no charge while nothing runs.
plan_sku_name = "FC1"
