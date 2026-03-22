# tracecraft

**Coordination layer for multi-agent AI systems.** Shared memory, experiment tracking, and session replay.

```bash
pip install tracecraft
```

---

When you run 10 AI agents in parallel, they need to coordinate. They need to share results, claim tasks, wait for each other, and pass context forward. Today, that infrastructure doesn't exist. Tracecraft is it.

```bash
# Agent A finishes a step and shares the result
tracecraft memory set s1a.status "complete"
tracecraft complete S1.A --note "SDK core built. Watch out for race in queue.py"

# Agent B reads it and starts its work
tracecraft wait-for S1.A
tracecraft memory get s1a.status
tracecraft claim S1.B
```

Works with Claude Code, Codex, CrewAI, LangGraph, Hermes Agent, autoresearch, or any process that can call a CLI.

---

## Why

Andrej Karpathy ran [700 experiments in 2 days](https://x.com/karpathy/status/2030371219518931079) with autoresearch. Then his labs [got wiped out in an outage](https://x.com/karpathy/status/2031792523187040643). No persistence, no replay, no failover.

He said the next step is ["asynchronously massively collaborative agents"](https://x.com/karpathy/status/2030705271627284816) — 7,500 people agreed.

[claude-peers](https://github.com/louislva/claude-peers-mcp) proved 400K people want agent coordination. But it's ephemeral messaging only — no shared memory, no persistence, no experiment tracking.

Tracecraft is the production infrastructure for both use cases.

---

## What it does

| Capability | Command | What happens |
|-----------|---------|-------------|
| **Shared memory** | `tracecraft memory set key value` | Agents read/write persistent key-value state |
| **Messaging** | `tracecraft send agent-b "done"` | Direct or broadcast messages between agents |
| **Task claiming** | `tracecraft claim S1.A` | Atomic step claiming so agents don't collide |
| **Barriers** | `tracecraft wait-for S1.A S1.B` | Block until dependencies complete |
| **Handoffs** | `tracecraft complete S1.A --note "..."` | Structured context for the next agent |
| **Experiment tracking** | `tracecraft run start "exp-v2"` | Track runs, metrics, artifacts, cost |
| **Session replay** | `tracecraft replay <run-id>` | Step-by-step replay of any past run |
| **Agent registry** | `tracecraft agents` | See who's online and what they're working on |

---

## Quick start

### 1. Install

```bash
pip install tracecraft
```

### 2. Start the server

```bash
tracecraft serve
```

This starts PostgreSQL + SeaweedFS + the tracecraft server locally via Docker.

### 3. Use from any agent

```bash
# From a Claude Code session, a Python script, a bash script — anything
tracecraft memory set research.findings '{"papers": 47, "relevant": 12}'
tracecraft send agent-writer "Research phase complete, 12 relevant papers found"
tracecraft run log-metric quality_score 0.92
```

### 4. Or use the Python SDK

```python
import tracecraft

tracecraft.init(project="my-research")

with tracecraft.run("prompt-comparison-v2") as run:
    with run.agent(name="researcher", model="claude-sonnet-4-20250514") as agent:
        with agent.step("search", kind="tool_call") as step:
            step.log_input({"query": "multi-agent coordination"})
            step.log_output(results)

        agent.shared_memory.set("findings", {"papers": 47})
        agent.send("writer", "Research complete")

    run.log_metrics({"quality_score": 0.92, "cost": 0.034})
```

---

## Integrations

Tracecraft works with any agent framework. One-line integrations for the major ones:

```python
# CrewAI
from tracecraft.integrations.crewai import TracecraftCallback
crew = Crew(agents=[...], callbacks=[TracecraftCallback()])

# Claude Agent SDK
from tracecraft.integrations.claude_sdk import tracecraft_hooks
agent = Agent(model="claude-sonnet-4-20250514", hooks=tracecraft_hooks())

# LangGraph
from tracecraft.integrations.langgraph import TracecraftTracer
result = app.invoke(input, config={"callbacks": [TracecraftTracer()]})

# Hermes Agent — coming soon
# AutoGen — coming soon
```

---

## Architecture

```
Agents (Claude Code, Codex, CrewAI, scripts, anything)
    |
    |  tracecraft CLI  or  Python SDK
    |
    v
Tracecraft Server (FastAPI)
    |
    +--- PostgreSQL (metadata, coordination state, experiment tracking)
    +--- SeaweedFS (artifacts, memory snapshots, replay files)
    +--- Redis (pub/sub, real-time notifications, locks)
```

Everything self-hosted. No cloud dependency. One `docker compose up` to start.

---

## CLI reference

```bash
# Server
tracecraft serve                          # Start local server
tracecraft status                         # Check connection

# Shared memory
tracecraft memory set <key> <value>       # Write (JSON or string)
tracecraft memory get <key>               # Read
tracecraft memory list [--prefix X]       # List keys
tracecraft memory watch <pattern>         # Stream changes in real-time

# Messaging
tracecraft send <agent-id> <message>      # Direct message
tracecraft broadcast <message>            # Message all agents
tracecraft inbox                          # Check messages
tracecraft inbox --watch                  # Stream incoming messages

# Coordination
tracecraft claim <step-id>                # Claim a task (atomic)
tracecraft complete <step-id> [--note X]  # Mark done + handoff note
tracecraft wait-for <step-ids...>         # Block until all complete

# Experiment tracking
tracecraft run start <name>               # Start a tracked run
tracecraft run log-metric <name> <value>  # Log a metric
tracecraft run log-artifact <name> <path> # Upload an artifact
tracecraft run end [--status X]           # End the run

# Inspection
tracecraft agents                         # Who's online?
tracecraft runs                           # List all runs
tracecraft runs inspect <id>              # Step-by-step timeline
tracecraft replay <id>                    # Replay a past run
```

---

## Use cases

### Parallel Claude Code sessions
Run 4 Claude Code agents in git worktrees, each building a different module. They claim steps, share artifacts, wait at barriers, and hand off context — all through tracecraft.

### Karpathy-style autoresearch
Run hundreds of experiments overnight. Every run is tracked with metrics, artifacts, and cost. Replay any run to understand what the agent tried. Compare runs to find what worked.

### CrewAI/LangGraph production monitoring
Track every agent decision, tool call, and handoff in production multi-agent workflows. Debug failures with session replay. Attribute costs to specific agents.

### Benchmarking multi-agent systems
Compare different agent configurations (3 agents vs 5 agents, GPT vs Claude, different prompts) with controlled experiment tracking and standardized metrics.

---

## How it compares

| | tracecraft | Langfuse | LangSmith | claude-peers | AgentOps |
|---|---|---|---|---|---|
| Open source | MIT | MIT (ClickHouse) | No | MIT | Partial |
| Shared memory | Yes | No | No | No | No |
| Agent coordination | Yes | No | No | Messaging only | No |
| Experiment tracking | Yes | Tracing only | Tracing only | No | Monitoring |
| Session replay | Yes | Trace waterfall | Trace waterfall | No | No |
| Artifact storage | Yes (SeaweedFS) | No | No | No | No |
| CLI-first | Yes | No | No | No | No |
| Self-hosted | Yes | Yes | Enterprise only | Localhost | No |
| Works with any framework | Yes | Yes | LangChain-centric | Claude Code only | Yes |

---

## Project structure

```
tracecraft/
  sdk/
    tracecraft/              Python SDK + CLI
      cli/                   CLI commands (click)
      integrations/          CrewAI, Claude SDK, LangGraph adapters
      transport/             Batching, retry, offline buffer
  server/
    tracecraft_server/       FastAPI server
      api/v1/                REST endpoints
      core/                  Config, auth, database
      storage/               SeaweedFS + artifact management
      services/              Shared memory, mailbox, coordination, registry
      models/                SQLAlchemy models
      ws/                    WebSocket handlers
  dashboard/                 Web UI (Phase 3)
  examples/                  Integration examples
  benchmarks/                MAExBench benchmark suite
  plans/                     Construction blueprints for contributors
  docs/                      Documentation
```

---

## Roadmap

- [x] Architecture design and blueprints
- [ ] Core SDK (init, run, agent, step)
- [ ] Server (PostgreSQL + SeaweedFS + Redis)
- [ ] Shared memory + messaging + coordination primitives
- [ ] CLI tool
- [ ] CrewAI integration
- [ ] Claude Agent SDK integration
- [ ] LangGraph integration
- [ ] Dashboard with session replay
- [ ] MAExBench (multi-agent experiment benchmark)
- [ ] arXiv paper

---

## Contributing

Tracecraft is built for parallel development. The `plans/` directory contains detailed construction blueprints where each step is self-contained — a fresh contributor (human or AI) can pick up any step and execute it independently.

```bash
git clone https://github.com/Arrmlet/tracecraft
cd tracecraft
cat plans/tracecraft-blueprint-v2.md    # Read the blueprint
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup instructions.

---

## Research

Tracecraft is also a research instrument. We're working toward:

- **arXiv preprint**: "Tracecraft: Shared Memory and Coordination Primitives for Multi-Agent LLM Systems"
- **MAExBench**: A standardized benchmark for evaluating multi-agent coordination, cost efficiency, and reliability
- **NeurIPS/ICLR submission**: Empirical findings from real-world multi-agent experiment data

If you're a researcher interested in multi-agent systems, we'd love to collaborate. Open an issue or reach out.

---

## License

MIT
