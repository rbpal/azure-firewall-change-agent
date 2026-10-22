# Values for the snapshot container. Each name is declared in variables.tf.
# Cost: no charge for the container. It holds a few KB per copy of main on the
# existing Standard LRS account, a fraction of a cent a month.

container_name = "network-snapshot"

# Read-only access for you to every container in the account, including ones
# created later (decided 2026-10-22). No charge.
blob_reader_for_terraform_user = true
