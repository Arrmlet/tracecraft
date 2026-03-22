# Tracecraft

Coordination layer for multi-agent AI systems. Shared memory, experiment tracking, and session replay.

## Quick Reference

- CLI: `tracecraft`
- Language: Python 3.10+
- Server: FastAPI + PostgreSQL + SeaweedFS + Redis
- Tests: `pytest`
- Install: `pip install tracecraft`

## Architecture

```
sdk/tracecraft/          Python SDK + CLI
  cli/                   CLI commands (click-based)
  integrations/          Framework adapters (CrewAI, Claude SDK, LangGraph)
  transport/             Batching, retry, offline SQLite buffer
server/tracecraft_server/ FastAPI server
  api/v1/                REST endpoints (runs, experiments, memory, mailbox, coordination)
  core/                  Config, security (JWT), database (SQLAlchemy + Alembic)
  storage/               SeaweedFS client, artifact management
  services/              Shared memory, mailbox, coordination, registry, handoff, replay
  models/                SQLAlchemy models (16 tables)
  ws/                    WebSocket handlers (live streaming, memory watch, mailbox, registry)
```

## Data Model (16 tables)

Core: User, Project, Experiment, Run, AgentInstance, Step, ToolCall, MemorySnapshot, Artifact, Metric, Event
Coordination: SharedMemoryEntry, AgentMailboxMessage, CoordinationPrimitive, AgentRegistration, HandoffNote, ArtifactDependency

## Key Design Decisions

- **CLI-first**: Primary interface is the `tracecraft` CLI command. Python SDK is secondary. MCP is optional addon.
- **PostgreSQL for metadata**: All coordination state + experiment data. JSONB for semi-structured fields.
- **SeaweedFS for blobs**: Artifacts, memory snapshots, replay files. S3-compatible.
- **Redis for pub/sub**: Real-time notifications for shared memory changes, message delivery, coordination events.
- **CAS for shared memory**: Optimistic concurrency via version numbers, not database locks.
- **Mandatory TTL on locks**: Agents crash. Every lock/barrier must expire to prevent deadlocks.

## Building

```bash
pip install -e "sdk/[dev]"           # SDK + CLI
pip install -e "server/[dev]"        # Server
docker compose -f docker-compose.dev.yml up -d  # Infrastructure
```

## Plans

Read `plans/tracecraft-blueprint-v2.md` for the full construction blueprint. Each step is self-contained for parallel multi-agent execution.
