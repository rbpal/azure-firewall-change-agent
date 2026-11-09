# Synthetic network data. All names and addresses are fictional.
rprt = {
  name                = "rprt"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  nat_rule_collections = {
    allow-rprt-dnat-rules = {
      name     = "allow-rprt-dnat-rules"
      priority = 1000
      action   = "Dnat"
      rules = {
        "001-tcp-humongousInsurance-to-rprtReportingApi" = {
          name                = "tcp-humongousInsurance-to-rprtReportingApi"
          protocols           = ["TCP"]
          source_addresses    = ["203.0.113.160/28"]
          destination_address = "192.0.2.14"
          destination_ports   = ["9443"]
          translated_address  = "10.104.15.20"
          translated_port     = "9443"
        }
      }
    }
  }

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
        }
        "002-https-rprt-to-fabrikamFs" = {
          name                  = "https-rprt-to-fabrikamFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["443"]
        }
        "003-smtp-rprt-to-woodgroveSmtp" = {
          name                  = "smtp-rprt-to-woodgroveSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["587"]
        }
        "004-amqps-rprt-to-lamnaMq" = {
          name                  = "amqps-rprt-to-lamnaMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
        }
        "005-sql-rprt-to-ledgSql" = {
          name                  = "sql-rprt-to-ledgSql"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-rprt-dev"]
          destination_addresses = ["10.104.16.0/24"]
          destination_ports     = ["1433"]
        }
        "006-https-rprt-to-prosewareFs" = {
          name                  = "https-rprt-to-prosewareFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["443"]
        }
        "007-sftp-rprt-to-xferSftp" = {
          name                  = "sftp-rprt-to-xferSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-rprt-dev"]
          destination_ip_groups = ["ipg-xfer-dev"]
          destination_ports     = ["22"]
        }
        "008-https-rprt-to-settApi" = {
          name                  = "https-rprt-to-settApi"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["10.104.14.0/24"]
          destination_ports     = ["443"]
        }
        "009-tcp-rprt-to-wingtipToys" = {
          name                  = "tcp-rprt-to-wingtipToys"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["203.0.113.96/28"]
          destination_ports     = ["443"]
        }
        "010-tcp-rprt-to-adatumCorp" = {
          name                  = "tcp-rprt-to-adatumCorp"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.15.0/24"]
          destination_addresses = ["198.51.100.176/28"]
          destination_ports     = ["8443"]
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
        }
        "002-https-rprt-to-bellowsCollegeApi" = {
          name              = "https-rprt-to-bellowsCollegeApi"
          protocols         = ["Https:443"]
          source_addresses  = ["10.104.15.0/24"]
          destination_fqdns = ["api.bellowscollege.example"]
        }
      }
    }
  }
}
