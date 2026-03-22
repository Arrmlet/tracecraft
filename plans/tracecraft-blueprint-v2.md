# TRACECRAFT — Multi-Agent Construction Blueprint v2.0

> **Objective**: Build `tracecraft` — an open-source coordination layer for multi-agent AI systems. Shared memory, experiment tracking, and session replay.

> **Primary goal**: AI researcher recognition via tool papers and benchmarks.

**Version**: 2.0 (coordination layer architecture)
**Created**: 2026-03-22
**Status**: READY FOR EXECUTION
**Source repo**: github.com/gnosis-research/gnosis-track (pivot source)
**Target repo**: github.com/tracecraft (to be created)
**Timeline**: 20 weeks at side-project pace (~15h/week)
**Predecessor**: claude-peers-mcp validated the market (377 stars in 1 day). Tracecraft is the production-grade superset.
**Distribution model**: CLI-first (like dataverse-cli `dv` — 300 users/day). NOT an MCP server.

---

## MARKET VALIDATION (from real data)

**Karpathy** (Mar 8, 2026): *"The next step for autoresearch is that it has to be asynchronously massively collaborative for agents"* — 7,547 likes, 1.1M views, 4,543 bookmarks. He needs collaborative agent infra with failover/persistence.

**Louis Arge** (Mar 21, 2026): claude-peers-mcp — 377 stars in 24h, 3,174 likes, 403K views. Simplest possible agent coordination went viral. But it's ephemeral messaging only.

**dataverse-cli** (our own): 300 users/day, 30K requests served. Proves CLI distribution works.

---

## WHAT MAKES THIS DIFFERENT FROM v1

v1 was observability: agents write traces → humans read dashboards.
v2 is coordination: agents read AND write shared state → agents coordinate through tracecraft.

```
v1 (observability):   Agent → traces → Human watches
v2 (coordination):    Agent A → writes shared memory → Agent B reads it → Agent C builds on it
                      + Agent D claims a step → Agent E waits at barrier → all proceed
                      + Human can watch/replay everything
```

**Competitive positioning**: claude-peers-mcp does ephemeral messaging. Tracecraft does persistent shared memory + coordination primitives + experiment tracking + session replay.

---

## CLI-FIRST ARCHITECTURE

Tracecraft is a **CLI tool**, not an MCP server. This is what made `dv` successful and what developers actually install.

### Why CLI, not MCP:
- `dv` got 300 users/day as a CLI. MCP servers have higher friction (need claude config).
- Karpathy's autoresearch is a CLI script. That's what researchers use.
- A CLI works with ANY agent framework, not just Claude Code.
- CLI can be called from scripts, CI/CD, notebooks, cron jobs.
- MCP can be added LATER as an optional integration on top of the CLI.

### Target CLI UX:

```bash
# Install
pip install tracecraft

# Start server (local, one command)
tracecraft serve                          # Starts server + PostgreSQL + SeaweedFS via Docker

# Agent coordination
tracecraft memory set phase1.status "complete"
tracecraft memory get phase1.status
tracecraft memory watch "phase1.*"        # Stream changes

tracecraft send agent-b "Step S1.A complete, artifacts ready"
tracecraft broadcast "Phase 1 done, starting Phase 2"
tracecraft inbox                          # Check messages
tracecraft inbox --watch                  # Stream incoming

tracecraft claim S1.A                     # Claim a step
tracecraft complete S1.A --note "Built SDK core, watch out for race in queue.py"
tracecraft wait-for S0.1 S0.2 S0.3       # Barrier — block until all done

# Experiment tracking
tracecraft run start "prompt-comparison-v2"
tracecraft run log-metric quality_score 0.92
tracecraft run log-artifact report.pdf ./report.pdf
tracecraft run end --status completed

# Inspection
tracecraft agents                         # Who's online?
tracecraft agents --step S1.B             # Who's working on S1.B?
tracecraft runs                           # List all runs
tracecraft runs inspect <run-id>          # Step timeline
tracecraft replay <run-id>                # Replay a run

# Status
tracecraft status                         # Server connection + active agents
```

### How agents use it:
Agents (Claude Code, Codex, scripts) shell out to `tracecraft` CLI commands. No SDK import needed for basic coordination. Python SDK available for deeper integration.

```python
# Option A: Shell out (zero dependencies, any language)
import subprocess
subprocess.run(["tracecraft", "memory", "set", "s1a.status", "complete"])
result = subprocess.run(["tracecraft", "memory", "get", "s1b.status"], capture_output=True)

# Option B: Python SDK (richer, async)
import tracecraft
tracecraft.init(project="my-research")
with tracecraft.run("experiment-1") as run:
    run.shared_memory.set("s1a.status", "complete")
    # ...
```

### MCP as optional addon (Phase 3+):
```bash
# For Claude Code users who want channel push:
claude mcp add tracecraft -- tracecraft mcp-serve
```
This wraps the CLI as an MCP server. Not the primary interface.

---

## HOW TO USE THIS BLUEPRINT

This document is designed for **parallel multi-agent execution**. Each step is self-contained — a fresh Claude Code agent in an isolated worktree can execute any step cold.

### For agents reading this:
1. Read ONLY the step assigned to you
2. Check `depends_on` — verify those steps are complete (check git log or ask via tracecraft)
3. Follow `files_to_create` and `files_to_modify` exactly
4. Run `verification` commands before marking complete
5. Do NOT modify files outside your step's scope
6. Commit with: `tracecraft: [step-id] description`
7. Write a handoff note for the next agent

### Parallel execution rules:
- Steps sharing a `parallel_group` can run simultaneously in separate worktrees
- `depends_on` steps MUST be merged before starting
- REVIEW GATES between phases — all steps must pass

---

## DEPENDENCY GRAPH

```
PHASE 0: FOUNDATION
  S0.1 ─── Repo setup + rename ──────────────────→ FIRST (sequential)
  ┌─────────────────────────────────────────────────┐
  │ After S0.1 merges, these run in parallel:       │
  │ S0.2 ─── Data model (PostgreSQL + 16 tables)    │
  │ S0.3 ─── Docker (Postgres + SeaweedFS + Redis)  │ parallel_group: P0
  │ S0.4 ─── CI/CD pipeline (GitHub Actions)        │
  │ S0.5 ─── Redis + Pub/Sub infrastructure         │
  └─────────────────────────────────────────────────┘
                    │
              [REVIEW GATE 0]
                    │
PHASE 1: CORE SERVICES (9 parallel streams)
  ┌─────────────────────────────────────────────────┐
  │ S1.A ─── SDK core (init, run, agent, step)      │
  │ S1.B ─── Server ingest + query API              │
  │ S1.C ─── Storage layer (artifacts)              │
  │ S1.D ─── CLI tool                               │ parallel_group: P1
  │ S1.E ─── Shared Memory service         [NEW]    │
  │ S1.F ─── Agent Mailbox service         [NEW]    │
  │ S1.G ─── Coordination Primitives       [NEW]    │
  │ S1.H ─── Agent Registry service        [NEW]    │
  │ S1.I ─── Handoff / Context Sharing     [NEW]    │
  └─────────────────────────────────────────────────┘
                    │
              [REVIEW GATE 1]
                    │
PHASE 1.5: SDK COORDINATION CLIENTS [NEW PHASE]
  ┌─────────────────────────────────────────────────┐
  │ S1.5.A ── SDK shared memory client              │
  │ S1.5.B ── SDK mailbox client                    │ parallel_group: P1.5
  │ S1.5.C ── SDK coordination client               │ (all depend on S1.A + S1.E-I)
  │ S1.5.D ── SDK registry + handoff clients        │
  │ S1.5.E ── CLI tool (tracecraft command)           │
  └─────────────────────────────────────────────────┘
                    │
              [REVIEW GATE 1.5] ← TWO Claude Codes coordinate via tracecraft
                    │
PHASE 2: INTEGRATIONS + LIVE
  ┌─────────────────────────────────────────────────┐
  │ S2.A ─── CrewAI integration                     │
  │ S2.B ─── Claude Agent SDK integration           │ parallel_group: P2
  │ S2.C ─── LangGraph integration                  │
  │ S2.D ─── WebSocket live streaming (8 channels)  │
  └─────────────────────────────────────────────────┘
                    │
              [REVIEW GATE 2]
                    │
PHASE 3: DASHBOARD + REPLAY
  ┌─────────────────────────────────────────────────┐
  │ S3.A ─── Dashboard + coordination views         │
  │ S3.B ─── Session replay + coordination replay   │ parallel_group: P3
  │ S3.C ─── Cost tracking + metrics                │
  └─────────────────────────────────────────────────┘
                    │
              [REVIEW GATE 3]
                    │
PHASE 4: RESEARCH + LAUNCH
  S4.A ─── Benchmark (MAExBench) ─────────────────→ parallel with S4.C
  S4.B ─── arXiv paper ───────────────────────────→ sequential after S4.A
  S4.C ─── Launch prep (README, PyPI, content) ───→ parallel with S4.A
                    │
PHASE 5: PAYMENTS + SCALE
  S5.A ─── Crypto payments (TAO/USDC)
  S5.B ─── Cloud deployment
```

---

## INVARIANTS (verify after EVERY step)

```bash
# 1. All tests pass
cd tracecraft && python -m pytest tests/ sdk/tests/ server/tests/ -x -q

# 2. Server starts
python -c "from tracecraft_server.main import app; print('Server OK')"

# 3. SDK imports
python -c "import tracecraft; print(tracecraft.__version__)"

# 4. Docker compose builds
docker compose -f docker-compose.dev.yml config --quiet

# 5. No secrets in code
grep -rE "(tc-|api_key\s*=\s*['\"])" --include="*.py" tracecraft/ | grep -v test | grep -v example
```

---

## NEW DATA MODEL (v2 — 16 tables)

### Original entities (10 — from v1):
```
User, Project, Experiment, Run, AgentInstance, Step, ToolCall,
MemorySnapshot, Artifact, Metric, Event
```

### New coordination entities (6):
```
SharedMemoryEntry
  id: UUID (pk)
  namespace: str (indexed)          # scoping: "project/exp/run" or "global"
  key: str (indexed)                # dot-path, e.g. "s1a.status"
  value: JSONB
  version: int (default 1)         # optimistic locking (CAS)
  owner_agent_id: UUID (fk → AgentInstance, nullable)
  ttl_seconds: int (nullable)      # auto-expire
  created_at, updated_at: datetime
  UNIQUE(namespace, key)

AgentMailboxMessage
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  sender_agent_id: UUID (fk, nullable)    # null = system
  recipient_agent_id: UUID (fk, nullable) # null = broadcast
  channel: str (indexed)                   # topic routing
  message_type: enum(result, request, notification, handoff, barrier_signal)
  payload: JSONB
  in_reply_to: UUID (fk, nullable)
  status: enum(pending, delivered, acknowledged, expired)
  expires_at: datetime (nullable)
  created_at, acknowledged_at: datetime

CoordinationPrimitive
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  primitive_type: enum(lock, barrier, semaphore, claim)
  resource_key: str (indexed)
  owner_agent_id: UUID (fk, nullable)
  state: JSONB                     # barrier: {required:4, arrived:["a1","a2"]}
  acquired_at, expires_at, released_at: datetime (nullable)
  created_at: datetime

AgentRegistration
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  agent_instance_id: UUID (fk → AgentInstance, unique)
  worktree_path: str (nullable)
  assigned_step: str (nullable)    # e.g., "S1.A"
  status: enum(starting, active, idle, waiting, completed, failed, unreachable)
  capabilities: JSONB (nullable)
  last_heartbeat: datetime
  started_at, finished_at: datetime

HandoffNote
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  from_agent_id: UUID (fk)
  to_agent_id: UUID (fk, nullable)  # null = anyone
  from_step: str
  to_step: str (nullable)
  summary: text
  findings: JSONB
  warnings: JSONB (nullable)
  artifacts_produced: JSONB (nullable)
  context_patch: JSONB (nullable)    # CLAUDE.md updates
  created_at: datetime

ArtifactDependency
  id: UUID (pk)
  artifact_id: UUID (fk → Artifact)
  producer_step_id: UUID (fk → Step)
  consumer_step_id: UUID (fk, nullable)
  consumer_agent_id: UUID (fk, nullable)
  created_at: datetime
```

---

## NEW API ENDPOINTS (v2 — 22 new coordination endpoints)

### Shared Memory (6 endpoints)
```
GET    /api/v1/memory/{namespace}/{key}
PUT    /api/v1/memory/{namespace}/{key}    # CAS via If-Match header
DELETE /api/v1/memory/{namespace}/{key}
GET    /api/v1/memory/{namespace}           # List keys (?prefix=)
WS     /ws/memory/{namespace}               # Subscribe to changes
```

### Agent Mailbox (5 endpoints)
```
POST   /api/v1/mailbox/send
POST   /api/v1/mailbox/broadcast
GET    /api/v1/mailbox/{agent_id}          # Poll (?channel=, ?since=)
POST   /api/v1/mailbox/{message_id}/ack
WS     /ws/mailbox/{agent_id}              # Real-time delivery
```

### Coordination (10 endpoints)
```
POST   /api/v1/coordination/lock/acquire
POST   /api/v1/coordination/lock/release
POST   /api/v1/coordination/lock/extend
POST   /api/v1/coordination/barrier/create
POST   /api/v1/coordination/barrier/arrive
GET    /api/v1/coordination/barrier/{id}
POST   /api/v1/coordination/semaphore/acquire
POST   /api/v1/coordination/semaphore/release
POST   /api/v1/coordination/claim           # Step claiming
GET    /api/v1/coordination/{run_id}        # List active primitives
```

### Agent Registry (5 endpoints)
```
POST   /api/v1/registry/register
POST   /api/v1/registry/heartbeat
POST   /api/v1/registry/deregister
GET    /api/v1/registry/{run_id}
WS     /ws/registry/{run_id}               # Presence changes
```

### Handoff (4 endpoints)
```
POST   /api/v1/handoffs
GET    /api/v1/handoffs/{run_id}
GET    /api/v1/handoffs/{run_id}/step/{step_id}
GET    /api/v1/handoffs/{run_id}/context/{step_id}  # Aggregated context
```

---

## NEW SDK API (v2 — coordination methods)

```python
import tracecraft

# Initialize with coordination support
tracecraft.init(
    api_key="tc-xxx",
    project="tracecraft-build",
    agent_name="s1a-builder",
    assigned_step="S1.A",
    worktree_path="/path/to/worktree",
)

with tracecraft.run("build-phase-1") as run:

    # === SHARED MEMORY ===
    mem = run.shared_memory(namespace="phase1")
    mem.set("s1a.status", "in_progress")
    status = mem.get("s1b.status")              # Read another agent's state
    mem.watch("s1b.*", callback=on_change)      # Real-time notifications

    # === MESSAGING ===
    with run.agent(name="builder-s1a") as agent:
        inbox = agent.mailbox()
        inbox.send(to="builder-s1b", channel="step.complete", payload={...})
        inbox.broadcast(channel="phase1.status", payload={"s1a": "done"})
        messages = inbox.poll(channel="step.*")
        inbox.subscribe(channel="phase1.*", callback=on_message)

    # === COORDINATION ===
    coord = run.coordination()
    async with coord.lock("file:models.py", ttl=300):
        # Safely edit shared file
        pass
    claimed = coord.claim("step:S1.A")         # Atomic step claiming
    barrier = coord.barrier("phase1_done", parties=4)
    await barrier.arrive_and_wait(timeout=600)  # Wait for all Phase 1 agents

    # === ARTIFACT SHARING ===
    run.share_artifact("schema.sql", data, tags=["s0.2-output"])
    data = run.fetch_artifact(artifact_id)      # Download from another agent
    url = run.get_artifact_url("schema.sql")    # Presigned URL

    # === HANDOFF ===
    agent.write_handoff(
        from_step="S1.A", to_step="S1.5.A",
        summary="SDK core complete with shared memory client stubs",
        findings={"key_decisions": ["CAS-based memory", "background batching"]},
        warnings=["transport/queue.py has known race condition"],
    )

    # === EXPERIMENT TRACKING (same as v1) ===
    with run.agent(name="researcher") as agent:
        with agent.step("search", kind="tool_call") as step:
            step.log_input({"query": query})
            step.log_output(result)
        run.log_metrics({"quality_score": 0.92})
```

---

## NEW STEP: S1.5.E — CLI Tool (`tracecraft` command)

**parallel_group**: P1.5
**depends_on**: [S1.A, S1.E, S1.F, S1.G, S1.H]
**estimated_effort**: 12 hours
**model_tier**: strongest

### Context Brief
Build the `tracecraft` CLI — the primary interface for agent coordination. Like `dv` for data queries, `tracecraft` is for agent coordination. Any agent (Claude Code, Codex, scripts) shells out to it. No SDK import needed.

### CLI commands:
```
tracecraft serve                          # Start local server (Docker)
tracecraft status                         # Connection + active agents

# Shared memory
tracecraft memory set <key> <value>       # Write
tracecraft memory get <key>               # Read
tracecraft memory list [--prefix X]       # List keys
tracecraft memory watch <pattern>         # Stream changes

# Messaging
tracecraft send <agent-id> <message>      # Direct message
tracecraft broadcast <message>            # To all agents
tracecraft inbox                          # Check messages
tracecraft inbox --watch                  # Stream incoming

# Coordination
tracecraft claim <step-id>                # Claim a step
tracecraft complete <step-id> [--note X]  # Mark done + handoff
tracecraft wait-for <step-ids...>         # Barrier

# Experiment tracking
tracecraft run start <name>               # Start a run
tracecraft run log-metric <name> <value>  # Log metric
tracecraft run log-artifact <name> <path> # Upload artifact
tracecraft run end [--status X]           # End run

# Inspection
tracecraft agents                         # List active agents
tracecraft runs                           # List runs
tracecraft runs inspect <id>              # Step timeline
tracecraft replay <id>                    # Replay a run
```

### Files to create:
- `sdk/tracecraft/cli/__init__.py` — Click group
- `sdk/tracecraft/cli/memory.py` — memory get/set/list/watch
- `sdk/tracecraft/cli/messages.py` — send/broadcast/inbox
- `sdk/tracecraft/cli/coordination.py` — claim/complete/wait-for
- `sdk/tracecraft/cli/runs.py` — run start/end/log-metric/log-artifact
- `sdk/tracecraft/cli/agents.py` — agents list
- `sdk/tracecraft/cli/serve.py` — start local server
- `sdk/tracecraft/cli/replay.py` — replay command

### Why CLI-first:
- `dv` got 300 users/day as a CLI. Proven distribution.
- Works with ANY agent framework — shell out from anything.
- Karpathy's autoresearch is a CLI script. Researchers use CLIs.
- MCP can be added later as `tracecraft mcp-serve` (optional, Phase 3+).

---

## ARCHITECTURE DECISIONS (v2)

### ADR-001: PostgreSQL source of truth, Redis notification layer
All coordination state persists in PostgreSQL. Redis provides pub/sub for real-time notifications and fast-path caching for hot keys. If Redis restarts, nothing is lost.

### ADR-002: CAS (optimistic concurrency) for shared memory
Version-based compare-and-swap, not database row locks. Agents are async and may hold stale references. CAS lets them detect conflicts and retry.

### ADR-003: Mandatory TTL on all coordination primitives
Agents crash. Claude Code sessions get killed. Every lock/barrier/semaphore MUST have an expiration. Auto-reaping prevents permanent blocks.

### ADR-004: MCP as the Claude Code integration layer
Following claude-peers' proven pattern: MCP server per instance, using claude/channel for instant push. This is the native integration path for Claude Code.

### ADR-005: A2A protocol alignment
The Agent Registry and Mailbox designs align with Google's A2A protocol (Agent Cards → AgentRegistration, Task lifecycle → HandoffNotes). Future A2A compatibility planned.

---

## EFFORT SUMMARY (v2)

| Phase | Steps | Effort | Parallelizable |
|-------|-------|--------|----------------|
| Phase 0 | 5 | 24h | 4 parallel after S0.1 |
| Phase 1 | 9 | 92h | All 9 parallel |
| Phase 1.5 | 5 | 30h | All 5 parallel |
| Phase 2 | 4 | 28h | All 4 parallel |
| Phase 3 | 3 | 66h | All 3 parallel |
| Phase 4 | 3 | 44h | 2 parallel + 1 sequential |
| Phase 5 | 2 | 28h | Both parallel |
| **Total** | **31** | **312h** | **Max parallel: 9 agents** |

At 15h/week side-project: ~21 weeks serial, ~12 weeks with parallel agents.
With 4 Claude Code agents in worktrees: each phase = 1-2 sessions.

---

## PAPER ANGLE UPDATE (v2)

The paper story is now STRONGER:

**v1 paper**: "An experiment tracking framework" (tool paper, EMNLP demos)
**v2 paper**: "A coordination infrastructure for multi-agent systems" (systems paper, OSDI/SOSP-tier)

New paper title options:
1. "Tracecraft: Shared Memory and Coordination Primitives for Multi-Agent LLM Systems"
2. "The Blackboard Revisited: A Modern Coordination Layer for Autonomous AI Agents"

The blackboard architecture reference (from 1986 AI research, now revived for LLM agents — see arXiv 2510.01285) gives the paper historical depth that reviewers love.

---

## KEY RESEARCH FROM COMPETITIVE ANALYSIS

### claude-peers-mcp (377 stars, created Mar 21 2026)
- Ephemeral messaging only, SQLite broker, no persistence
- **Tracecraft superset**: Everything claude-peers does + shared memory + artifacts + coordination + replay

### Protocols landscape:
- **MCP** = agent-to-tool (97M monthly SDK downloads)
- **A2A** (Google/Linux Foundation) = agent-to-agent task delegation
- **Tracecraft** fills the gap: agent-to-agent COORDINATION (shared state, not just messages)

### Academic backing:
- "LLM-Based Multi-Agent Blackboard System" (arXiv 2510.01285) — 13-57% improvement over baselines
- "Multi-Agent Memory from Computer Architecture Perspective" (arXiv 2603.10062) — cache hierarchy for agents
- "Collaborative Memory with Dynamic Access Control" (arXiv 2505.18279) — private/shared memory tiers

---

*This blueprint is a living document. Update step status as work progresses. For the full v1 step details (S0.1-S0.3, S1.A-D, S2.A-D, S3.A-C, S4.A-C, S5.A-B), see plans/tracecraft-blueprint.md (v1.1). This v2 document adds the coordination layer on top.*
