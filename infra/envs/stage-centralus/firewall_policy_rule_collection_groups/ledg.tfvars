# Synthetic estate. All names and addresses are fictional.
ledg = {
  name                = "ledg"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  network_rule_collections = {
    allow-ledg-network-rules = {
      name     = "allow-ledg-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-https-ledg-to-litwareFs" = {
          name                  = "https-ledg-to-litwareFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.16.0/24"]
          destination_addresses = ["203.0.113.64/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009033"
        }
        "002-smtp-ledg-to-tailspinSmtp" = {
          name                  = "smtp-ledg-to-tailspinSmtp"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.16.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports     = ["587"]
          ticket                = "RITM0009034"
        }
        "003-https-ledg-to-fourthcoffeeFs" = {
          name                  = "https-ledg-to-fourthcoffeeFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-ledg-stage-dr"]
          destination_addresses = ["203.0.113.80/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009035"
        }
        "004-amqps-ledg-to-lamnaMq" = {
          name                  = "amqps-ledg-to-lamnaMq"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-ledg-stage-dr"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009036"
        }
        "005-amqps-ledg-to-prosewareMq" = {
          name                  = "amqps-ledg-to-prosewareMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.16.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009037"
        }
        "006-amqps-ledg-to-wingtipMq" = {
          name                  = "amqps-ledg-to-wingtipMq"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-ledg-stage-dr"]
          destination_addresses = ["198.51.100.80/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009038"
        }
        "007-https-ledg-to-adventureworksFs" = {
          name                  = "https-ledg-to-adventureworksFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-ledg-stage-dr"]
          destination_addresses = ["198.51.100.64/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009039"
        }
        "008-amqps-ledg-to-northwindMq" = {
          name                  = "amqps-ledg-to-northwindMq"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-ledg-stage-dr"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["5671"]
          ticket                = "RITM0009040"
        }
        "009-https-ledg-to-lamnaFs" = {
          name                  = "https-ledg-to-lamnaFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-ledg-stage-dr"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["443"]
          ticket                = "RITM0009041"
        }
      }
    }
  }
}
