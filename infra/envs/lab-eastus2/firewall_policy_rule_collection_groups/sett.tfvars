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
          source_ip_groups      = ["ipg-sett-lab"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009001"
        }
        "002-sftp-sett-to-xferSftp" = {
          name                  = "sftp-sett-to-xferSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-lab"]
          destination_addresses = ["10.106.20.0/24"]
          destination_ports     = ["22"]
          ticket                = "RITM0009002"
        }
        "003-amqps-sett-to-northwindMq" = {
          name                  = "amqps-sett-to-northwindMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009003"
        }
        "004-smtp-sett-to-fabrikamSmtp" = {
          name                  = "smtp-sett-to-fabrikamSmtp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-lab"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009004"
        }
        "005-sftp-sett-to-lamnaSftp" = {
          name                  = "sftp-sett-to-lamnaSftp"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-lab"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["22"]
          ticket                = "RITM0009005"
        }
        "006-amqps-sett-to-lamnaMq" = {
          name                  = "amqps-sett-to-lamnaMq"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-lab"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009006"
        }
        "007-https-sett-to-wingtipFs" = {
          name                  = "https-sett-to-wingtipFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009007"
        }
        "008-smtp-sett-to-wingtipSmtp" = {
          name                  = "smtp-sett-to-wingtipSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009008"
        }
        "009-https-sett-to-fabrikamFs" = {
          name                  = "https-sett-to-fabrikamFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-sett-lab"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009009"
        }
        "010-sftp-sett-to-prosewareSftp" = {
          name                  = "sftp-sett-to-prosewareSftp"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["22"]
          ticket                = "RITM0009010"
        }
        "011-smtp-sett-to-lamnaSmtp" = {
          name                  = "smtp-sett-to-lamnaSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009011"
        }
        "012-amqps-sett-to-prosewareMq" = {
          name                  = "amqps-sett-to-prosewareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009012"
        }
        "013-https-sett-to-lamnaFs" = {
          name                  = "https-sett-to-lamnaFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009013"
        }
        "014-sftp-sett-to-fabrikamSftp" = {
          name                  = "sftp-sett-to-fabrikamSftp"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["203.0.113.32/28"]
          destination_ports     = ["22"]
          ticket                = "RITM0009014"
        }
        "015-amqps-sett-to-woodgroveMq" = {
          name                  = "amqps-sett-to-woodgroveMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["203.0.113.48/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009015"
        }
        "016-smtp-sett-to-tailspinSmtp" = {
          name                  = "smtp-sett-to-tailspinSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009016"
        }
        "017-amqps-sett-to-tailspinMq" = {
          name                  = "amqps-sett-to-tailspinMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009017"
        }
        "018-https-sett-to-litwareFs" = {
          name                  = "https-sett-to-litwareFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.106.14.0/24"]
          destination_addresses = ["203.0.113.64/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009018"
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
          source_ip_groups  = ["ipg-sett-lab"]
          destination_fqdns = ["api.northwind.example"]
          ticket            = "RITM0009024"
        }
        "002-https-sett-to-woodgroveApi" = {
          name              = "https-sett-to-woodgroveApi"
          protocols         = ["Https:443"]
          source_ip_groups  = ["ipg-sett-lab"]
          destination_fqdns = ["api.woodgrove.example"]
          ticket            = "RITM0009025"
        }
      }
    }
  }
}
