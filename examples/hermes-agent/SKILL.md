---
name: tracecraft
description: Coordinate with other AI agents through shared memory, messaging, and task claiming via tracecraft CLI
version: 1.0.0
platforms: [cli, telegram, discord, slack]
tags: [coordination, multi-agent, memory, messaging]
category: dev-tools
---

## When to Use

Use this skill when you need to coordinate with other agents. This includes:
- Sharing state with other agents (memory set/get)
- Sending messages to other agents
- Claiming tasks so other agents don't duplicate work
- Waiting for other agents to finish a step
- Sharing files between agents

## Setup

Ensure tracecraft is installed and initialized:
```
terminal(command="pip install tracecraft-ai")
terminal(command="tracecraft init --backend hf --bucket <bucket> --project <project> --agent hermes-1")
```

## Procedure

### Check who's online
```
terminal(command="tracecraft agents")
```

### Share state
```
terminal(command="tracecraft memory set <key> <value>")
terminal(command="tracecraft memory get <key>")
terminal(command="tracecraft memory list")
```

### Send and receive messages
```
terminal(command="tracecraft send <agent-id> '<message>'")
terminal(command="tracecraft inbox")
```

### Coordinate tasks
```
terminal(command="tracecraft claim <step-id>")
terminal(command="tracecraft complete <step-id> --note '<handoff context>'")
terminal(command="tracecraft step-status <step-id>")
terminal(command="tracecraft wait-for <step-id> --timeout 300")
```

### Share files
```
terminal(command="tracecraft artifact upload <path> --step <step-id>")
terminal(command="tracecraft artifact download <name> --step <step-id>")
terminal(command="tracecraft artifact list")
```

## Pitfalls

- Run `tracecraft init` before using any commands
- Check `tracecraft inbox` regularly for messages from other agents
- Use `tracecraft claim` before starting work to avoid duplicating effort
- Use `--note` with `tracecraft complete` to pass context to the next agent

## Verification

After any action, verify with the corresponding read command:
- After `memory set` → `memory get`
- After `send` → ask the recipient to check `inbox`
- After `claim` → `step-status`
