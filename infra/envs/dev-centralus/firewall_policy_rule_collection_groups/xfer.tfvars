# Synthetic network data. All names and addresses are fictional.
xfer = {
  name                = "xfer"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  nat_rule_collections = {
    allow-xfer-dnat-rules = {
      name     = "allow-xfer-dnat-rules"
      priority = 1000
      action   = "Dnat"
      rules = {
        "001-sftp-woodgrove-to-xferSftp" = {
          name                = "sftp-woodgrove-to-xferSftp"
          protocols           = ["TCP"]
          source_addresses    = ["203.0.113.48/28"]
          destination_address = "192.0.2.15"
          destination_ports   = ["2221"]
          translated_address  = "10.105.20.14"
          translated_port     = "22"
        }
        "002-ssh-fourthCoffee-to-xferSftp" = {
          name                = "ssh-fourthCoffee-to-xferSftp"
          protocols           = ["TCP"]
          source_addresses    = ["203.0.113.80/28"]
          destination_address = "192.0.2.15"
          destination_ports   = ["22"]
          translated_address  = "10.105.20.14"
          translated_port     = "22"
        }
        "003-ftps-alpineSkiHouse-to-xferFtps" = {
          name                = "ftps-alpineSkiHouse-to-xferFtps"
          protocols           = ["TCP"]
          source_addresses    = ["198.51.100.96/28"]
          destination_address = "192.0.2.15"
          destination_ports   = ["990"]
          translated_address  = "10.105.20.15"
          translated_port     = "990"
        }
      }
    }
  }

  network_rule_collections = {
    allow-xfer-network-rules = {
      name     = "allow-xfer-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-https-xfer-to-fourthcoffeeFs" = {
          name                  = "https-xfer-to-fourthcoffeeFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["203.0.113.80/28"]
          destination_ports     = ["443"]
        }
        "002-https-xfer-to-wingtipFs" = {
          name                  = "https-xfer-to-wingtipFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["443"]
        }
        "003-https-xfer-to-settApi" = {
          name                  = "https-xfer-to-settApi"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-dev-dr"]
          destination_addresses = ["10.105.14.0/24"]
          destination_ports     = ["443"]
        }
        "004-https-xfer-to-lamnaFs" = {
          name                  = "https-xfer-to-lamnaFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["443"]
        }
        "005-sftp-xfer-to-woodgroveSftp" = {
          name                  = "sftp-xfer-to-woodgroveSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-dev-dr"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["22"]
        }
        "006-amqps-xfer-to-litwareMq" = {
          name                  = "amqps-xfer-to-litwareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["203.0.113.64/28"]
          destination_ports     = ["5671"]
        }
        "007-https-xfer-to-northwindFs" = {
          name                  = "https-xfer-to-northwindFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-xfer-dev-dr"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["443"]
        }
        "008-amqps-xfer-to-prosewareMq" = {
          name                  = "amqps-xfer-to-prosewareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["5671"]
        }
        "009-ssh-xfer-to-treyResearch" = {
          name                  = "ssh-xfer-to-treyResearch"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["198.51.100.144/28"]
          destination_ports     = ["22"]
        }
      }
    }
  }

  application_rule_collections = {
    allow-xfer-app-rules = {
      name     = "allow-xfer-app-rules"
      priority = 3000
      action   = "Allow"
      rules = {
        "001-https-xfer-to-graphicDesignInstituteApi" = {
          name              = "https-xfer-to-graphicDesignInstituteApi"
          protocols         = ["Https:443"]
          source_addresses  = ["10.105.20.0/24"]
          destination_fqdns = ["api.graphicdesigninstitute.example"]
        }
      }
    }
  }
}
