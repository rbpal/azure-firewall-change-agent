# Synthetic estate. All names and addresses are fictional.
port = {
  name                = "port"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  network_rule_collections = {
    allow-port-network-rules = {
      name     = "allow-port-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-amqps-port-to-lamnaMq" = {
          name                  = "amqps-port-to-lamnaMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
        }
        "002-https-port-to-settApi" = {
          name                  = "https-port-to-settApi"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_addresses = ["10.104.14.0/24"]
          destination_ports     = ["443"]
        }
        "003-https-port-to-fourthcoffeeFs" = {
          name                  = "https-port-to-fourthcoffeeFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_addresses = ["203.0.113.80/28"]
          destination_ports     = ["443"]
        }
        "004-https-port-to-tailspinFs" = {
          name                  = "https-port-to-tailspinFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports     = ["443"]
        }
      }
    }
  }

  application_rule_collections = {
    allow-port-app-rules = {
      name     = "allow-port-app-rules"
      priority = 3000
      action   = "Allow"
      rules = {
        "001-https-port-to-fabrikamApi" = {
          name              = "https-port-to-fabrikamApi"
          protocols         = ["Https:443"]
          source_ip_groups  = ["ipg-port-dev"]
          destination_fqdns = ["api.fabrikam.example"]
        }
        "002-https-port-to-tailspinApi" = {
          name              = "https-port-to-tailspinApi"
          protocols         = ["Https:443"]
          source_ip_groups  = ["ipg-port-dev"]
          destination_fqdns = ["api.tailspin.example"]
        }
      }
    }
  }
}
