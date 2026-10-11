# One firewall policy, its IP groups and its rule collection groups.
#
# The code here never changes for a rule request. The rules are data: one
# tfvars file per spoke in infra/envs/<env-site>/. Rules refer to IP groups by
# name; this module swaps each name for the group's resource ID. An unknown
# group name fails the plan, so a typing mistake never drops a source.

resource "azurerm_firewall_policy" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  tags                = var.tags
}

resource "azurerm_ip_group" "this" {
  for_each = var.ip_groups

  name                = each.value.name
  resource_group_name = var.resource_group_name
  location            = var.location
  cidrs               = each.value.cidrs
  tags                = var.tags
}

locals {
  ip_group_ids = { for k, g in azurerm_ip_group.this : g.name => g.id }
}

resource "azurerm_firewall_policy_rule_collection_group" "this" {
  for_each = var.rule_collection_groups

  name               = each.value.name
  firewall_policy_id = azurerm_firewall_policy.this.id
  priority           = each.value.priority

  dynamic "nat_rule_collection" {
    for_each = lookup(each.value, "nat_rule_collections", {})
    content {
      name     = nat_rule_collection.value.name
      priority = nat_rule_collection.value.priority
      action   = nat_rule_collection.value.action

      dynamic "rule" {
        for_each = nat_rule_collection.value.rules
        content {
          name                = rule.value.name
          protocols           = rule.value.protocols
          source_addresses    = lookup(rule.value, "source_addresses", null)
          source_ip_groups    = length(lookup(rule.value, "source_ip_groups", [])) > 0 ? [for n in rule.value.source_ip_groups : local.ip_group_ids[n]] : null
          destination_address = rule.value.destination_address
          destination_ports   = rule.value.destination_ports
          translated_address  = rule.value.translated_address
          translated_port     = rule.value.translated_port
        }
      }
    }
  }

  dynamic "network_rule_collection" {
    for_each = lookup(each.value, "network_rule_collections", {})
    content {
      name     = network_rule_collection.value.name
      priority = network_rule_collection.value.priority
      action   = network_rule_collection.value.action

      dynamic "rule" {
        for_each = network_rule_collection.value.rules
        content {
          name                  = rule.value.name
          protocols             = rule.value.protocols
          source_addresses      = lookup(rule.value, "source_addresses", null)
          source_ip_groups      = length(lookup(rule.value, "source_ip_groups", [])) > 0 ? [for n in rule.value.source_ip_groups : local.ip_group_ids[n]] : null
          destination_addresses = lookup(rule.value, "destination_addresses", null)
          destination_ip_groups = length(lookup(rule.value, "destination_ip_groups", [])) > 0 ? [for n in rule.value.destination_ip_groups : local.ip_group_ids[n]] : null
          destination_ports     = rule.value.destination_ports
        }
      }
    }
  }

  dynamic "application_rule_collection" {
    for_each = lookup(each.value, "application_rule_collections", {})
    content {
      name     = application_rule_collection.value.name
      priority = application_rule_collection.value.priority
      action   = application_rule_collection.value.action

      dynamic "rule" {
        for_each = application_rule_collection.value.rules
        content {
          name              = rule.value.name
          source_addresses  = lookup(rule.value, "source_addresses", null)
          source_ip_groups  = length(lookup(rule.value, "source_ip_groups", [])) > 0 ? [for n in rule.value.source_ip_groups : local.ip_group_ids[n]] : null
          destination_fqdns = rule.value.destination_fqdns

          # "Https:443" in the data becomes type Https, port 443.
          dynamic "protocols" {
            for_each = rule.value.protocols
            content {
              type = split(":", protocols.value)[0]
              port = tonumber(split(":", protocols.value)[1])
            }
          }
        }
      }
    }
  }
}
