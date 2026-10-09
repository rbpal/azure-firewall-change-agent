# Synthetic estate. All names and addresses are fictional.
sett = {
  name                = "sett"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  network_rule_collections = {
    allow-sett-network-rules = {
      name     = "allow-sett-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-smtp-sett-to-prosewareSmtp" = {
          name                  = "smtp-sett-to-prosewareSmtp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["587"]
        }
        "002-sftp-sett-to-xferSftp" = {
          name                  = "sftp-sett-to-xferSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["10.101.20.0/24"]
          destination_ports     = ["22"]
        }
        "003-amqps-sett-to-northwindMq" = {
          name                  = "amqps-sett-to-northwindMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["5671"]
        }
        "004-smtp-sett-to-fabrikamSmtp" = {
          name                  = "smtp-sett-to-fabrikamSmtp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["587"]
        }
        "005-sftp-sett-to-lamnaSftp" = {
          name                  = "sftp-sett-to-lamnaSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["22"]
        }
        "006-amqps-sett-to-lamnaMq" = {
          name                  = "amqps-sett-to-lamnaMq"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
        }
        "007-https-sett-to-wingtipFs" = {
          name                  = "https-sett-to-wingtipFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["443"]
        }
        "008-smtp-sett-to-wingtipSmtp" = {
          name                  = "smtp-sett-to-wingtipSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["587"]
        }
        "009-https-sett-to-fabrikamFs" = {
          name                  = "https-sett-to-fabrikamFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["443"]
        }
        "010-sftp-sett-to-prosewareSftp" = {
          name                  = "sftp-sett-to-prosewareSftp"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["22"]
        }
        "011-smtp-sett-to-lamnaSmtp" = {
          name                  = "smtp-sett-to-lamnaSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["587"]
        }
        "012-amqps-sett-to-prosewareMq" = {
          name                  = "amqps-sett-to-prosewareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["5671"]
        }
        "013-https-sett-to-lamnaFs" = {
          name                  = "https-sett-to-lamnaFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["443"]
        }
        "014-sftp-sett-to-fabrikamSftp" = {
          name                  = "sftp-sett-to-fabrikamSftp"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["22"]
        }
        "015-amqps-sett-to-woodgroveMq" = {
          name                  = "amqps-sett-to-woodgroveMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["5671"]
        }
        "016-smtp-sett-to-tailspinSmtp" = {
          name                  = "smtp-sett-to-tailspinSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports     = ["587"]
        }
        "017-amqps-sett-to-tailspinMq" = {
          name                  = "amqps-sett-to-tailspinMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports     = ["5671"]
        }
        "018-https-sett-to-litwareFs" = {
          name                  = "https-sett-to-litwareFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["203.0.113.64/28"]
          destination_ports     = ["443"]
        }
        "019-sftp-sett-to-adventureworksSftp" = {
          name                  = "sftp-sett-to-adventureworksSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["198.51.100.64/28"]
          destination_ports     = ["22"]
        }
        "020-https-sett-to-prosewareFs" = {
          name                  = "https-sett-to-prosewareFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["443"]
        }
        "021-sftp-sett-to-woodgroveSftp" = {
          name                  = "sftp-sett-to-woodgroveSftp"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["22"]
        }
        "022-sftp-sett-to-northwindSftp" = {
          name                  = "sftp-sett-to-northwindSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-prod-dr"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["22"]
        }
        "023-amqps-sett-to-fourthcoffeeMq" = {
          name                  = "amqps-sett-to-fourthcoffeeMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.101.14.0/24"]
          destination_addresses = ["203.0.113.80/28"]
          destination_ports     = ["5671"]
        }
      }
    }
  }

  application_rule_collections = {
    allow-sett-app-rules = {
      name     = "allow-sett-app-rules"
      priority = 3000
      action   = "Allow"
      rules = {
        "001-https-sett-to-northwindApi" = {
          name              = "https-sett-to-northwindApi"
          protocols         = ["Https:443"]
          source_ip_groups  = ["ipg-sett-prod-dr"]
          destination_fqdns = ["api.northwind.example"]
        }
        "002-https-sett-to-woodgroveApi" = {
          name              = "https-sett-to-woodgroveApi"
          protocols         = ["Https:443"]
          source_ip_groups  = ["ipg-sett-prod-dr"]
          destination_fqdns = ["api.woodgrove.example"]
        }
      }
    }
  }
}
