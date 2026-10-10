# Existing resources this step reads but does not create.

# The subscription this run is signed in to, from ARM_SUBSCRIPTION_ID.
# The budget needs its full ID, /subscriptions/<id>.
data "azurerm_subscription" "current" {}
