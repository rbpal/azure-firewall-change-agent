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
          source_addresses      = ["10.102.20.0/24"]
          destination_addresses = ["203.0.113.80/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009049"
        }
        "002-https-xfer-to-wingtipFs" = {
          name                  = "https-xfer-to-wingtipFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.102.20.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009050"
        }
        "003-https-xfer-to-settApi" = {
          name                  = "https-xfer-to-settApi"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-stage"]
          destination_addresses = ["10.102.14.0/24"]
          destination_ports     = ["443"]
          ticket                = "RITM0009051"
        }
        "004-https-xfer-to-lamnaFs" = {
          name                  = "https-xfer-to-lamnaFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.102.20.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009052"
        }
        "005-sftp-xfer-to-woodgroveSftp" = {
          name                  = "sftp-xfer-to-woodgroveSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-stage"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["22"]
          ticket                = "RITM0009053"
        }
        "006-amqps-xfer-to-litwareMq" = {
          name                  = "amqps-xfer-to-litwareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.102.20.0/24"]
          destination_addresses = ["203.0.113.64/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009054"
        }
        "007-https-xfer-to-northwindFs" = {
          name                  = "https-xfer-to-northwindFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-stage"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009061"
        }
      }
    }
  }
}
