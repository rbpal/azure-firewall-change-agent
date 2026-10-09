# Synthetic estate. All names and addresses are fictional.
rprt = {
  name                = "rprt"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  network_rule_collections = {
    allow-rprt-network-rules = {
      name     = "allow-rprt-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-sftp-rprt-to-fabrikamSftp" = {
          name                  = "sftp-rprt-to-fabrikamSftp"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["22"]
          ticket                = "RITM0009026"
        }
        "002-https-rprt-to-fabrikamFs" = {
          name                  = "https-rprt-to-fabrikamFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009027"
        }
        "003-smtp-rprt-to-woodgroveSmtp" = {
          name                  = "smtp-rprt-to-woodgroveSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009028"
        }
        "004-amqps-rprt-to-lamnaMq" = {
          name                  = "amqps-rprt-to-lamnaMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009029"
        }
        "005-sql-rprt-to-ledgSql" = {
          name                  = "sql-rprt-to-ledgSql"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-rprt-dev"]
          destination_addresses = ["10.104.16.0/24"]
          destination_ports     = ["1433"]
          ticket                = "RITM0009030"
        }
        "006-https-rprt-to-prosewareFs" = {
          name                  = "https-rprt-to-prosewareFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009031"
        }
      }
    }
  }

  application_rule_collections = {
    allow-rprt-app-rules = {
      name     = "allow-rprt-app-rules"
      priority = 3000
      action   = "Allow"
      rules = {
        "001-https-rprt-to-litwareApi" = {
          name              = "https-rprt-to-litwareApi"
          protocols         = ["Https:443"]
          source_ip_groups  = ["ipg-rprt-dev"]
          destination_fqdns = ["api.litware.example"]
          ticket            = "RITM0009032"
        }
      }
    }
  }
}
