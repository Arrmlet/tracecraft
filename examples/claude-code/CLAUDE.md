# Tracecraft Coordination

This project uses tracecraft for multi-agent coordination. You are one of several agents working in parallel.

## Commands

```bash
tracecraft agents                         # See who else is online
tracecraft memory set <key> <value>       # Share state with other agents
tracecraft memory get <key>               # Read shared state
tracecraft send <agent-id> "<message>"    # Message another agent
tracecraft inbox                          # Check your messages
tracecraft claim <step>                   # Claim a task
tracecraft complete <step> --note "..."   # Mark done + handoff
tracecraft step-status <step>             # Check if a step is done
tracecraft wait-for <step>                # Block until step completes
tracecraft artifact upload <file> --step <step>   # Share a file
tracecraft artifact download <name> --step <step> # Get a shared file
```

## How to coordinate

1. Check `tracecraft agents` to see who else is working
2. Check `tracecraft inbox` for messages before starting
3. Run `tracecraft claim <your-step>` before starting work
4. Share progress via `tracecraft memory set`
5. When done, run `tracecraft complete <step> --note "context for next agent"`
6. Check `tracecraft inbox` periodically for messages from other agents
