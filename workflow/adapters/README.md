# workflow/adapters

The ticket-system interface: get a ticket, add a work note, change its state, close it. The `file` adapter reads the YAML tickets in `data/tickets/`. A `servicenow` adapter can plug into the same interface without any change to the agent.
