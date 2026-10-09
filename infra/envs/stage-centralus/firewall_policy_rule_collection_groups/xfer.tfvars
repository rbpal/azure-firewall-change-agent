# Synthetic estate. All names and addresses are fictional.
xfer = {
  name                = "xfer"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  network_rule_collections = {
    allow-xfer-network-rules = {
      name     = "allow-xfer-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-https-xfer-to-fourthcoffeeFs" = {
          name                  = "https-xfer-to-fourthcoffeeFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.20.0/24"]
          destination_addresses = ["203.0.113.80/28"]
          destination_ports     = ["443"]
        }
        "002-https-xfer-to-wingtipFs" = {
          name                  = "https-xfer-to-wingtipFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.20.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["443"]
        }
        "003-https-xfer-to-settApi" = {
          name                  = "https-xfer-to-settApi"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-stage-dr"]
          destination_addresses = ["10.103.14.0/24"]
          destination_ports     = ["443"]
        }
        "004-https-xfer-to-lamnaFs" = {
          name                  = "https-xfer-to-lamnaFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.20.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["443"]
        }
        "005-sftp-xfer-to-woodgroveSftp" = {
          name                  = "sftp-xfer-to-woodgroveSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-stage-dr"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["22"]
        }
        "006-amqps-xfer-to-litwareMq" = {
          name                  = "amqps-xfer-to-litwareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.20.0/24"]
          destination_addresses = ["203.0.113.64/28"]
          destination_ports     = ["5671"]
        }
        "007-https-xfer-to-northwindFs" = {
          name                  = "https-xfer-to-northwindFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-stage-dr"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["443"]
        }
      }
    }
  }
}
