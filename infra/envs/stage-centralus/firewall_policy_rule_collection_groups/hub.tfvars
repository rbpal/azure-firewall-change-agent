# Synthetic estate. All names and addresses are fictional.
hub = {
  name                = "hub"
  firewall_policy_key = "firewall_policy"
  priority            = 200

  network_rule_collections = {
    allow-hub-network-rules = {
      name     = "allow-hub-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "001-dns-spokes-to-hubDns" = {
          name                  = "dns-spokes-to-hubDns"
          protocols             = ["TCP", "UDP"]
          source_addresses      = ["10.103.16.0/24", "10.103.17.0/24", "10.103.15.0/24", "10.103.14.0/24", "10.103.20.0/24"]
          destination_addresses = ["10.103.1.4/32", "10.103.1.5/32"]
          destination_ports     = ["53"]
          ticket                = "RITM0009057"
        }
        "002-ntp-spokes-to-hubNtp" = {
          name                  = "ntp-spokes-to-hubNtp"
          protocols             = ["UDP"]
          source_addresses      = ["10.103.16.0/24", "10.103.17.0/24", "10.103.15.0/24", "10.103.14.0/24", "10.103.20.0/24"]
          destination_addresses = ["10.103.1.6/32"]
          destination_ports     = ["123"]
          ticket                = "RITM0009058"
        }
        "003-ldaps-spokes-to-hubDc" = {
          name                  = "ldaps-spokes-to-hubDc"
          protocols             = ["TCP"]
          source_addresses      = ["10.103.16.0/24", "10.103.17.0/24", "10.103.15.0/24", "10.103.14.0/24", "10.103.20.0/24"]
          destination_addresses = ["10.103.1.7/32"]
          destination_ports     = ["636"]
          ticket                = "RITM0009059"
        }
        "004-syslog-spokes-to-hubSyslog" = {
          name                  = "syslog-spokes-to-hubSyslog"
          protocols             = ["UDP"]
          source_addresses      = ["10.103.16.0/24", "10.103.17.0/24", "10.103.15.0/24", "10.103.14.0/24", "10.103.20.0/24"]
          destination_addresses = ["10.103.1.8/32"]
          destination_ports     = ["514"]
          ticket                = "RITM0009060"
        }
      }
    }
  }
}
