# Values for the observability workbook. Each name is declared in variables.tf.
# Cost (checked 2026-11-19): Microsoft's Azure Monitor cost page bills data
# ingestion and retention, not the features that read it, and lists no
# workbook charge. Interactive queries on Analytics tables are not charged
# by data scanned. No official page states "workbooks are free" in so many
# words, so confirm on the Azure Monitor pricing page before the first apply.

# Changing this text changes the GUID, which replaces the workbook.
workbook_name_seed = "azure-firewall-change-agent/dev/workbook/fwagent-observability"

workbook_display_name = "Firewall agent observability (dev)"
workbook_description  = "Agent runs, tokens, tools and ticket timelines from law-fwagentic-dev."
