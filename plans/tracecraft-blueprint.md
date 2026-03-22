# TRACECRAFT — Multi-Agent Construction Blueprint

> **Objective**: Pivot gnosis-track into `tracecraft` — an open-source multi-agent experiment tracker, storage platform, and research instrument. Primary goal: AI researcher recognition via tool papers and benchmarks.

**Version**: 1.1 (post-adversarial review)
**Created**: 2026-03-21
**Status**: READY FOR EXECUTION
**Repo**: github.com/gnosis-research/gnosis-track (to be renamed/forked to tracecraft)
**Timeline**: 18 weeks at side-project pace (~15h/week)

---

## HOW TO USE THIS BLUEPRINT

This document is designed for **parallel multi-agent execution**. Each step is self-contained — a fresh Claude Code agent in an isolated worktree can execute any step without reading prior steps, as long as dependencies are met.

### For agents reading this:
1. Read ONLY the step assigned to you
2. Check the `depends_on` field — verify those steps are complete
3. Follow the `files_to_create` and `files_to_modify` lists exactly
4. Run the `verification` commands before marking complete
5. Do NOT modify files outside your step's scope
6. Commit with message format: `tracecraft: [step-id] description`

### Parallel execution rules:
- Steps with `parallel_group: X` can run simultaneously in separate worktrees
- Steps with `depends_on: [step-id]` MUST wait for that step to merge
- After each phase, there is a REVIEW GATE — all steps in the phase must pass before next phase starts

---

## DEPENDENCY GRAPH

```
PHASE 0: FOUNDATION (SEQUENTIAL)
  S0.1 ─── Repo setup + rename ──────────────────→
  S0.2 ─── Data model + PostgreSQL schema ────────→ (depends on S0.1)
  S0.3 ─── Docker dev environment ────────────────→ (depends on S0.1)
  S0.4 ─── CI/CD pipeline (GitHub Actions) ───────→ (depends on S0.1)
  Note: S0.2 and S0.3 can run in parallel AFTER S0.1 merges
                    │
              [REVIEW GATE 0]
                    │
PHASE 1: CORE (4 streams in parallel)
  S1.A ─── SDK core package ──────────────────────┐
  S1.B ─── Server ingest API ─────────────────────┤ parallel_group: P1
  S1.C ─── Storage layer (artifact mgmt) ─────────┤ (all depend on Phase 0)
  S1.D ─── CLI tool ──────────────────────────────┘
                    │
              [REVIEW GATE 1]
                    │
PHASE 2: INTEGRATIONS + LIVE
  S2.A ─── CrewAI integration ────────────────────┐
  S2.B ─── Claude Agent SDK integration ──────────┤ parallel_group: P2
  S2.C ─── LangGraph integration ─────────────────┤ (all depend on S1.A)
  S2.D ─── WebSocket live streaming ──────────────┘ (depends on S1.B)
                    │
              [REVIEW GATE 2]
                    │
PHASE 3: DASHBOARD + REPLAY
  S3.A ─── Dashboard scaffold + run explorer ─────┐
  S3.B ─── Session replay engine + player ─────────┤ parallel_group: P3
  S3.C ─── Cost tracking + metrics ───────────────┘
                    │
              [REVIEW GATE 3]
                    │
PHASE 4: RESEARCH + LAUNCH
  S4.A ─── Benchmark design + data collection ────┐
  S4.B ─── arXiv paper draft ─────────────────────┤ parallel_group: P4
  S4.C ─── Launch prep (README, PyPI, content) ───┘
                    │
              [REVIEW GATE 4]
                    │
PHASE 5: PAYMENTS + SCALE
  S5.A ─── Crypto payments (TAO/USDC) ───────────┐
  S5.B ─── Cloud deployment ──────────────────────┘ parallel_group: P5
```

---

## INVARIANTS (verify after EVERY step)

```bash
# 1. All existing tests pass
cd tracecraft && python -m pytest tests/ -x -q

# 2. Server starts without errors
cd tracecraft/server && python -c "from tracecraft_server.main import app; print('OK')"

# 3. SDK imports cleanly
python -c "import tracecraft; print(tracecraft.__version__)"

# 4. Docker compose builds (after S0.3)
docker compose -f docker-compose.dev.yml config --quiet

# 5. No secrets in code
grep -rE "(gt_|tc-|api_key\s*=\s*['\"])" --include="*.py" tracecraft/ | grep -v test | grep -v example
# Should return nothing (no hardcoded tokens or keys)
```

---

## PHASE 0: FOUNDATION

### Step S0.1 — Repository Setup and Rename

**parallel_group**: P0
**depends_on**: none
**estimated_effort**: 4 hours
**model_tier**: default

#### Context Brief
gnosis-track is an existing Python package at github.com/gnosis-research/gnosis-track. It has a SeaweedFS storage client, FastAPI UI, JWT auth, and a CLI. We are pivoting it into `tracecraft` — a multi-agent experiment tracker. This step restructures the repo.

#### Current repo structure (gnosis-track):
```
gnosis_track/
  __init__.py          → exports SeaweedClient, BucketManager, ValidatorLogger
  core/
    config_manager.py  → YAML config with env var overrides
    seaweed_client.py  → S3-compatible SeaweedFS client (boto3)
    bucket_manager.py  → S3 bucket CRUD operations
    auth_manager.py    → JWT auth with role-based access
    token_manager.py   → API token generation (gt_xxxxx format)
  logging/
    validator_logger.py → Bittensor validator-specific logger
    log_streamer.py     → WebSocket streaming infrastructure
    log_formatter.py    → Log formatting utilities
  ui/
    server.py           → FastAPI server with Jinja2 templates
    static/app.js       → Frontend JS
    templates/           → index.html, login.html, error.html
  cli/
    main.py             → Click-based CLI entry point
    install.py          → SeaweedFS installation commands
    manage.py           → Management commands
    logs.py             → Log-related commands
```

#### Target repo structure:
```
tracecraft/
  README.md
  LICENSE                      # MIT
  pyproject.toml
  CONTRIBUTING.md
  CLAUDE.md                    # Agent context for Claude Code
  docker-compose.dev.yml
  plans/
    tracecraft-blueprint.md    # This file
  sdk/
    tracecraft/
      __init__.py              # tracecraft.init(), start_run()
      py.typed                 # PEP 561 marker
  server/
    tracecraft_server/
      __init__.py
      main.py                  # FastAPI app
      core/
        config.py              # Extended from gnosis config_manager
        security.py            # From gnosis auth_manager + token_manager
        database.py            # SQLAlchemy + Alembic setup
      storage/
        seaweed.py             # From gnosis seaweed_client
        buckets.py             # From gnosis bucket_manager
        artifacts.py           # NEW: artifact management
      api/
        v1/
          __init__.py
          runs.py
          experiments.py
          agents.py
          steps.py
          artifacts.py
          auth.py
      models/                  # SQLAlchemy models
        __init__.py
      ws/
        live.py                # From gnosis log_streamer
        replay.py              # NEW
    alembic/
      versions/
    tests/
  dashboard/                   # Phase 3 — placeholder
  examples/
  tests/
```

#### Tasks
- [ ] Fork/clone gnosis-track to new `tracecraft` directory
- [ ] Rename package: `gnosis_track` → split into `sdk/tracecraft/` and `server/tracecraft_server/`
- [ ] Move `core/seaweed_client.py` → `server/tracecraft_server/storage/seaweed.py`
- [ ] Move `core/bucket_manager.py` → `server/tracecraft_server/storage/buckets.py`
- [ ] Move `core/config_manager.py` → `server/tracecraft_server/core/config.py`
- [ ] Move `core/auth_manager.py` + `core/token_manager.py` → `server/tracecraft_server/core/security.py`
- [ ] Move `ui/server.py` → `server/tracecraft_server/main.py`
- [ ] Move `logging/log_streamer.py` → `server/tracecraft_server/ws/live.py`
- [ ] Create new `pyproject.toml` for SDK (name=tracecraft)
- [ ] Create new `pyproject.toml` for server (name=tracecraft-server)
- [ ] Create root `pyproject.toml` as workspace
- [ ] Write `CLAUDE.md` with full project context for future agents
- [ ] Write placeholder `README.md` with tagline: "Open-source experiment tracking for AI agents"
- [ ] Add MIT `LICENSE`
- [ ] Copy this blueprint to `plans/tracecraft-blueprint.md`
- [ ] Initialize git, create initial commit

#### Files to create
- `tracecraft/README.md`
- `tracecraft/LICENSE`
- `tracecraft/CLAUDE.md`
- `tracecraft/pyproject.toml` (workspace)
- `tracecraft/sdk/tracecraft/__init__.py`
- `tracecraft/sdk/pyproject.toml`
- `tracecraft/server/tracecraft_server/__init__.py`
- `tracecraft/server/pyproject.toml`
- `tracecraft/server/tracecraft_server/main.py`
- `tracecraft/server/tracecraft_server/core/config.py`
- `tracecraft/server/tracecraft_server/core/security.py`
- `tracecraft/server/tracecraft_server/storage/seaweed.py`
- `tracecraft/server/tracecraft_server/storage/buckets.py`

#### Verification
```bash
# Package imports work
cd tracecraft && pip install -e sdk/ && python -c "import tracecraft; print('SDK OK')"
cd tracecraft && pip install -e server/ && python -c "from tracecraft_server.main import app; print('Server OK')"
# Storage client preserved
python -c "from tracecraft_server.storage.seaweed import SeaweedClient; print('Storage OK')"
# Auth preserved
python -c "from tracecraft_server.core.security import AuthManager; print('Auth OK')"
```

#### Exit criteria
- All existing gnosis-track functionality preserved (nothing deleted, only moved)
- Both packages install and import cleanly
- CLAUDE.md contains full project context
- Git initialized with clean first commit

---

### Step S0.2 — Data Model and PostgreSQL Schema

**parallel_group**: P0b (can parallel with S0.3 AFTER S0.1 merges)
**depends_on**: [S0.1]
**estimated_effort**: 8 hours
**model_tier**: strongest
**database_for_testing**: SQLite for unit tests (use JSONB → JSON compat). PostgreSQL for integration tests (via docker from S0.3).

#### Context Brief
Design and implement the PostgreSQL schema for tracecraft. This is the most critical design decision in the project — it determines what research questions we can answer. The data model must support: organizations/projects, experiments with multiple runs, runs with multiple agents, agents with nested steps (OTel spans), tool calls, memory snapshots, artifacts, and metrics.

**IMPORTANT**: The gnosis-track repo structure will already exist from S0.1. Clone from: `https://github.com/gnosis-research/gnosis-track` (public repo). After S0.1, the directory structure at `server/tracecraft_server/` will exist.

#### Data Model Specification

```
User
  id: UUID (pk)
  username: str (unique, indexed)
  email: str (nullable)
  wallet_address: str (nullable)     # For crypto payments (Phase 5)
  api_token_hash: str                # Hashed tc-xxx token
  role: enum(admin, member, viewer)
  created_at: datetime

Project
  id: UUID (pk)
  name: str (indexed)
  slug: str (unique, indexed)        # URL-safe identifier
  owner_id: UUID (fk → User)
  description: str (nullable)
  settings: JSONB                    # Project-level config
  created_at: datetime
  updated_at: datetime

Experiment
  id: UUID (pk)
  project_id: UUID (fk → Project, indexed)
  name: str
  description: str (nullable)
  hypothesis: str (nullable)        # Research hypothesis
  parameters: JSONB                  # Default params for runs
  tags: JSONB (array)
  created_at: datetime
  updated_at: datetime

Run
  id: UUID (pk)
  experiment_id: UUID (fk → Experiment)
  name: str (nullable)
  status: enum(pending, running, completed, failed, cancelled)
  params: JSONB                      # Override experiment params
  config_snapshot: JSONB             # Frozen config at run start
  git_sha: str (nullable)           # For reproducibility
  total_tokens_in: int (default 0)
  total_tokens_out: int (default 0)
  total_cost_usd: decimal (default 0)
  error: text (nullable)
  started_at: datetime
  finished_at: datetime (nullable)
  created_at: datetime

AgentInstance
  id: UUID (pk)
  run_id: UUID (fk → Run)
  name: str                          # e.g., "researcher"
  role: str (nullable)               # e.g., "Research specialist"
  model: str (nullable)              # e.g., "claude-sonnet-4-20250514"
  framework: str (nullable)          # e.g., "crewai", "langgraph", "claude-sdk"
  config: JSONB                      # Agent-specific config
  system_prompt: text (nullable)
  tools: JSONB (array, nullable)     # List of available tools
  status: enum(idle, active, waiting, completed, errored)
  token_usage: JSONB                 # {input: N, output: N, total: N}
  ordinal: int (default 0)          # Order in agent team
  created_at: datetime

Step
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  agent_id: UUID (fk → AgentInstance, nullable, indexed)
  parent_step_id: UUID (fk → Step, nullable)  # For nested spans
  trace_id: str (indexed)           # OTel trace ID
  span_id: str (unique)             # OTel span ID
  parent_span_id: str (nullable)    # OTel parent span ID
  kind: enum(llm_call, tool_call, retrieval, delegation, reasoning, user_input, system)
  name: str
  input: JSONB (nullable)
  output: JSONB (nullable)
  model: str (nullable)
  tokens_in: int (nullable)
  tokens_out: int (nullable)
  cost_usd: decimal (nullable)
  latency_ms: int (nullable)
  status: enum(ok, error)
  error: text (nullable)
  metadata: JSONB (nullable)
  started_at: datetime
  finished_at: datetime (nullable)

ToolCall
  id: UUID (pk)
  step_id: UUID (fk → Step)
  tool_name: str (indexed)
  input: JSONB
  output: JSONB (nullable)
  output_artifact_id: UUID (fk → Artifact, nullable)
  duration_ms: int (nullable)
  status: enum(ok, error)
  error: text (nullable)
  created_at: datetime

MemorySnapshot
  id: UUID (pk)
  agent_id: UUID (fk → AgentInstance)
  step_id: UUID (fk → Step, nullable)  # Snapshot taken at this step
  snapshot_type: enum(working_memory, long_term_memory, scratchpad, context_window)
  content: JSONB (nullable)          # Small snapshots inline
  artifact_id: UUID (fk → Artifact, nullable)  # Large snapshots as artifact
  created_at: datetime

Artifact
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  step_id: UUID (fk → Step, nullable)
  agent_id: UUID (fk → AgentInstance, nullable)
  name: str
  content_type: str                  # MIME type
  size_bytes: int
  storage_key: str                   # SeaweedFS object key
  checksum_sha256: str (nullable)
  metadata: JSONB (nullable)
  created_at: datetime

Metric
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  step_id: UUID (fk → Step, nullable)
  agent_id: UUID (fk → AgentInstance, nullable)
  name: str (indexed)
  value: float
  unit: str (nullable)
  timestamp: datetime

Event
  id: UUID (pk)
  run_id: UUID (fk → Run, indexed)
  agent_id: UUID (fk → AgentInstance, nullable)
  event_type: enum(agent_spawned, agent_completed, message_sent, message_received, handoff, error, checkpoint, user_interrupt)
  payload: JSONB (nullable)
  timestamp: datetime
```

#### Tasks
- [ ] Create `server/tracecraft_server/models/__init__.py` with all SQLAlchemy models
- [ ] Create `server/tracecraft_server/models/experiment.py`
- [ ] Create `server/tracecraft_server/models/run.py`
- [ ] Create `server/tracecraft_server/models/agent.py`
- [ ] Create `server/tracecraft_server/models/step.py`
- [ ] Create `server/tracecraft_server/models/tool_call.py`
- [ ] Create `server/tracecraft_server/models/memory_snapshot.py`
- [ ] Create `server/tracecraft_server/models/artifact.py`
- [ ] Create `server/tracecraft_server/models/metric.py`
- [ ] Create `server/tracecraft_server/models/event.py`
- [ ] Create `server/tracecraft_server/core/database.py` with engine, session, Base
- [ ] Set up Alembic: `server/alembic.ini` + `server/alembic/env.py`
- [ ] Create initial migration
- [ ] Add indexes on: `step.run_id`, `step.trace_id`, `step.agent_id`, `metric.run_id+name`, `artifact.run_id`, `event.run_id+timestamp`
- [ ] Write model unit tests

#### Files to create
- `server/tracecraft_server/models/*.py` (10 files)
- `server/tracecraft_server/core/database.py`
- `server/alembic.ini`
- `server/alembic/env.py`
- `server/alembic/versions/001_initial_schema.py`
- `server/tests/test_models.py`

#### Verification
```bash
# Models import cleanly
python -c "from tracecraft_server.models import *; print('Models OK')"
# Alembic migration runs against SQLite (for testing)
cd server && alembic upgrade head && echo "Migration OK"
# Tests pass
cd server && pytest tests/test_models.py -v
```

#### Exit criteria
- All 10 entity models defined with proper relationships
- Alembic migration creates all tables
- Indexes defined on high-query columns
- Models tested with SQLite (PostgreSQL tested in docker step)

---

### Step S0.3 — Docker Development Environment

**parallel_group**: P0
**depends_on**: none
**estimated_effort**: 3 hours
**model_tier**: default

#### Context Brief
Create a docker-compose.dev.yml that starts the full local development stack: PostgreSQL, SeaweedFS, and the tracecraft server. This enables any developer (or Claude Code agent) to get a working environment with one command.

#### Tasks
- [ ] Create `docker-compose.dev.yml` with services:
  - `postgres`: PostgreSQL 16, port 5432, volume for persistence
  - `seaweedfs-master`: SeaweedFS master, port 9333
  - `seaweedfs-volume`: SeaweedFS volume server, port 8080
  - `seaweedfs-filer`: SeaweedFS filer, port 8888
  - `seaweedfs-s3`: SeaweedFS S3 gateway, port 8333
  - `server`: tracecraft FastAPI server, port 8000, depends on postgres + seaweedfs
- [ ] Create `server/Dockerfile` (Python 3.12, uvicorn)
- [ ] Create `.env.example` with all config vars
- [ ] Create `scripts/dev-setup.sh` that runs migrations and seeds test data
- [ ] Add health check endpoints to FastAPI server

#### Files to create
- `docker-compose.dev.yml`
- `server/Dockerfile`
- `.env.example`
- `scripts/dev-setup.sh`

#### Verification
```bash
docker compose -f docker-compose.dev.yml up -d
sleep 10
curl -s http://localhost:8000/health | grep ok
curl -s http://localhost:8333 | grep -i seaweed  # S3 gateway alive
docker compose -f docker-compose.dev.yml down
```

#### Exit criteria
- `docker compose up` starts all services
- Server connects to PostgreSQL and runs migrations
- SeaweedFS S3 gateway accessible
- Health endpoint returns 200

---

## REVIEW GATE 0

**Reviewer**: Strongest model agent
**Checklist**:
- [ ] All Phase 0 steps merged to main
- [ ] `docker compose up` works end-to-end
- [ ] Data model covers all entities from architecture doc
- [ ] No gnosis-track specific references remain (except in git history)
- [ ] CLAUDE.md accurately describes the project
- [ ] All invariants pass

---

## PHASE 1: CORE

### Step S1.A — SDK Core Package

**parallel_group**: P1
**depends_on**: [S0.1, S0.2]
**estimated_effort**: 30 hours (split into S1.A.1 core + S1.A.2 transport if parallelizing)
**model_tier**: strongest

#### Context Brief
Build the Python SDK that developers use to instrument their multi-agent applications. The SDK must support a 3-line setup and use background batching to avoid blocking user code. It communicates with the tracecraft server via HTTP/2.

#### Target API:
```python
import tracecraft

# Initialize
tracecraft.init(
    api_key="tc-xxx",              # or TRACECRAFT_API_KEY env var
    project="my-research",
    server_url="http://localhost:8000",  # default
)

# Start a run
with tracecraft.run("prompt-comparison-v2", experiment="exp-1") as run:
    run.log_params({"model": "claude-sonnet-4-20250514", "temperature": 0.7})

    # Track an agent
    with run.agent(name="researcher", model="claude-sonnet-4-20250514") as agent:

        # Track a step (maps to OTel span)
        with agent.step("search", kind="tool_call") as step:
            result = search_tool(query)
            step.log_input({"query": query})
            step.log_output(result)

        with agent.step("synthesize", kind="llm_call") as step:
            response = llm.complete(prompt)
            step.log_tokens(input=1200, output=450)

        agent.snapshot_memory({"working": agent_memory})

    run.log_artifact("report.pdf", open("report.pdf", "rb"))
    run.log_metrics({"quality_score": 0.92, "total_cost": 0.034})
```

#### Tasks
- [ ] Create `sdk/tracecraft/__init__.py` — top-level `init()`, `run()` functions
- [ ] Create `sdk/tracecraft/client.py` — `TracecraftClient` HTTP client (httpx async)
- [ ] Create `sdk/tracecraft/config.py` — Configuration resolution (api_key, server_url, env vars)
- [ ] Create `sdk/tracecraft/run.py` — `Run` context manager
- [ ] Create `sdk/tracecraft/agent.py` — `AgentContext` context manager
- [ ] Create `sdk/tracecraft/step.py` — `StepContext` context manager (generates span_id, trace_id)
- [ ] Create `sdk/tracecraft/artifact.py` — `ArtifactManager` (upload to SeaweedFS via presigned URL)
- [ ] Create `sdk/tracecraft/metric.py` — `MetricCollector`
- [ ] Create `sdk/tracecraft/memory.py` — `MemorySnapshotManager`
- [ ] Create `sdk/tracecraft/transport/` — batching + background flush
  - `queue.py` — bounded event queue (10K max)
  - `batcher.py` — flush every 100ms or 50 events
  - `retry.py` — exponential backoff with jitter
  - `local_buffer.py` — SQLite WAL fallback for offline mode
- [ ] Create `sdk/tracecraft/tracing/` — OTel bridge
  - `span_factory.py` — generate trace_id, span_id (W3C format)
  - `context.py` — contextvars-based trace propagation
- [ ] Create `sdk/pyproject.toml` — package metadata, dependencies (httpx, pydantic)
- [ ] Write tests for all context managers
- [ ] Write tests for batching/transport layer

#### Files to create
- `sdk/tracecraft/__init__.py`
- `sdk/tracecraft/client.py`
- `sdk/tracecraft/config.py`
- `sdk/tracecraft/run.py`
- `sdk/tracecraft/agent.py`
- `sdk/tracecraft/step.py`
- `sdk/tracecraft/artifact.py`
- `sdk/tracecraft/metric.py`
- `sdk/tracecraft/memory.py`
- `sdk/tracecraft/transport/__init__.py`
- `sdk/tracecraft/transport/queue.py`
- `sdk/tracecraft/transport/batcher.py`
- `sdk/tracecraft/transport/retry.py`
- `sdk/tracecraft/transport/local_buffer.py`
- `sdk/tracecraft/tracing/__init__.py`
- `sdk/tracecraft/tracing/span_factory.py`
- `sdk/tracecraft/tracing/context.py`
- `sdk/tracecraft/integrations/__init__.py`
- `sdk/tests/test_run.py`
- `sdk/tests/test_agent.py`
- `sdk/tests/test_step.py`
- `sdk/tests/test_transport.py`

#### Verification
```bash
cd sdk && pip install -e ".[dev]" && pytest tests/ -v
python -c "
import tracecraft
tracecraft.init(api_key='tc-test', project='test', server_url='http://localhost:8000')
with tracecraft.run('test-run') as run:
    with run.agent(name='test-agent') as agent:
        with agent.step('test-step', kind='llm_call') as step:
            step.log_tokens(input=100, output=50)
    run.log_metrics({'test': 1.0})
print('SDK smoke test OK')
"
```

#### Exit criteria
- 3-line setup works
- Context managers produce correct nested trace structure
- Background batching flushes without blocking
- Offline mode falls back to SQLite
- >80% test coverage on core modules

---

### Step S1.B — Server Ingest API

**parallel_group**: P1
**depends_on**: [S0.1, S0.2, S0.3]
**estimated_effort**: 10 hours
**model_tier**: default

#### Context Brief
Build the FastAPI server endpoints that receive data from the SDK. The server must handle batched event ingestion, CRUD for experiments/runs, and serve query APIs for the dashboard.

#### API Endpoints:

```
POST   /api/v1/ingest                  # Batched event ingestion (steps, metrics, events)
POST   /api/v1/runs                    # Create a new run
GET    /api/v1/runs                    # List runs (filterable by experiment, status, date)
GET    /api/v1/runs/{id}              # Get run detail
PATCH  /api/v1/runs/{id}              # Update run (status, metrics, finished_at)
GET    /api/v1/runs/{id}/steps        # List steps for a run (paginated, tree structure)
GET    /api/v1/runs/{id}/agents       # List agents in a run
GET    /api/v1/runs/{id}/artifacts    # List artifacts for a run
GET    /api/v1/runs/{id}/metrics      # Get metrics for a run
POST   /api/v1/experiments            # Create experiment
GET    /api/v1/experiments            # List experiments
GET    /api/v1/experiments/{id}       # Get experiment with run summary
POST   /api/v1/artifacts/presign      # Get presigned upload URL for SeaweedFS
POST   /api/v1/auth/token             # Generate API token
GET    /health                         # Health check
```

#### Tasks
- [ ] Create `server/tracecraft_server/api/v1/runs.py` — Run CRUD + query endpoints
- [ ] Create `server/tracecraft_server/api/v1/experiments.py` — Experiment CRUD
- [ ] Create `server/tracecraft_server/api/v1/steps.py` — Step queries (paginated, tree)
- [ ] Create `server/tracecraft_server/api/v1/agents.py` — Agent queries
- [ ] Create `server/tracecraft_server/api/v1/artifacts.py` — Artifact metadata + presigned URLs
- [ ] Create `server/tracecraft_server/api/v1/ingest.py` — Batched event ingestion endpoint
- [ ] Create `server/tracecraft_server/api/v1/auth.py` — Token generation + validation
- [ ] Create `server/tracecraft_server/api/deps.py` — Dependency injection (db session, auth)
- [ ] Update `server/tracecraft_server/main.py` — Mount all routers
- [ ] Create `server/tracecraft_server/schemas/` — Pydantic request/response models
- [ ] Write API tests (httpx TestClient)

#### Files to create
- `server/tracecraft_server/api/v1/*.py` (7 files)
- `server/tracecraft_server/api/deps.py`
- `server/tracecraft_server/schemas/*.py`
- `server/tests/test_api_runs.py`
- `server/tests/test_api_ingest.py`

#### Verification
```bash
cd server && pytest tests/ -v
# Start server and test manually
uvicorn tracecraft_server.main:app --host 0.0.0.0 --port 8000 &
sleep 2
curl -s http://localhost:8000/health | grep ok
curl -s -X POST http://localhost:8000/api/v1/experiments \
  -H "Content-Type: application/json" \
  -d '{"name": "test", "project": "test"}' | grep id
kill %1
```

#### Exit criteria
- All endpoints return correct status codes
- Ingest endpoint handles batched events (50+ events per request)
- Pagination works on step/run list endpoints
- Auth middleware validates tc-xxx tokens
- API tests cover happy path + error cases

---

### Step S1.C — Storage Layer (Artifact Management)

**parallel_group**: P1
**depends_on**: [S0.1, S0.2, S0.3]
**estimated_effort**: 6 hours
**model_tier**: default

#### Context Brief
Extend the existing SeaweedFS storage client (from gnosis-track) with artifact management: presigned upload/download URLs, content-type detection, size tracking, and a deterministic key convention.

#### Storage key convention:
```
/{project}/{experiment_id}/{run_id}/artifacts/{step_id}/{artifact_name}
/{project}/{experiment_id}/{run_id}/memory/{agent_id}/{step_id}.snapshot.json
/{project}/{experiment_id}/{run_id}/replay/{run_id}.replay.jsonl
```

#### Tasks
- [ ] Create `server/tracecraft_server/storage/artifacts.py`:
  - `generate_storage_key(project, experiment_id, run_id, step_id, name)` → deterministic key
  - `create_presigned_upload(key, content_type, expires)` → presigned POST URL
  - `create_presigned_download(key, expires)` → presigned GET URL
  - `store_artifact(key, data, content_type)` → direct upload
  - `get_artifact(key)` → direct download
  - `delete_artifact(key)` → delete
  - `list_artifacts(prefix)` → list objects with prefix
- [ ] Extend `server/tracecraft_server/storage/seaweed.py`:
  - Add presigned URL support (SeaweedFS S3 gateway supports this)
  - Add content-type auto-detection
- [ ] Create `server/tracecraft_server/storage/lifecycle.py`:
  - `apply_lifecycle_policy(project, max_age_days)` — move/delete old artifacts
- [ ] Write storage integration tests (against local SeaweedFS in docker)

#### Files to create
- `server/tracecraft_server/storage/artifacts.py`
- `server/tracecraft_server/storage/lifecycle.py`
- `server/tests/test_storage.py`

#### Files to modify
- `server/tracecraft_server/storage/seaweed.py` — add presigned URL methods

#### Verification
```bash
# Requires docker compose running
docker compose -f docker-compose.dev.yml up -d
cd server && pytest tests/test_storage.py -v
# Manual: upload and download round-trip
python -c "
from tracecraft_server.storage.artifacts import ArtifactManager
am = ArtifactManager()
am.store_artifact('test/artifact.txt', b'hello world', 'text/plain')
data = am.get_artifact('test/artifact.txt')
assert data == b'hello world'
print('Storage round-trip OK')
"
```

#### Exit criteria
- Upload/download round-trip works against SeaweedFS
- Presigned URLs work for browser-based upload/download
- Key convention enforced
- Content-type detection works for common types

---

### Step S1.D — CLI Tool

**parallel_group**: P1
**depends_on**: [S0.1, S1.A] (CLI uses SDK client; server endpoints from S1.B needed for verification but not build)
**estimated_effort**: 4 hours
**model_tier**: default

#### Context Brief
Extend the existing Click-based CLI from gnosis-track into a tracecraft CLI. Commands for managing experiments, inspecting runs, and configuring the client.

#### Commands:
```
tracecraft init                    # Interactive setup (api key, server URL)
tracecraft status                  # Check connection + API key
tracecraft experiments list        # List experiments
tracecraft runs list [--experiment ID]  # List runs
tracecraft runs inspect <run_id>   # Show run detail (agents, steps, cost)
tracecraft runs compare <id1> <id2>  # Compare two runs (future)
tracecraft artifacts list <run_id> # List artifacts
tracecraft artifacts download <artifact_id> <path>  # Download artifact
```

#### Tasks
- [ ] Create `sdk/tracecraft/cli/__init__.py` — Click group
- [ ] Create `sdk/tracecraft/cli/auth.py` — init, status commands
- [ ] Create `sdk/tracecraft/cli/experiments.py` — experiment commands
- [ ] Create `sdk/tracecraft/cli/runs.py` — run list, inspect commands
- [ ] Create `sdk/tracecraft/cli/artifacts.py` — artifact list, download
- [ ] Update `sdk/pyproject.toml` — add `[project.scripts] tracecraft = "tracecraft.cli:main"`
- [ ] Write CLI tests (click.testing.CliRunner)

#### Files to create
- `sdk/tracecraft/cli/__init__.py`
- `sdk/tracecraft/cli/auth.py`
- `sdk/tracecraft/cli/experiments.py`
- `sdk/tracecraft/cli/runs.py`
- `sdk/tracecraft/cli/artifacts.py`
- `sdk/tests/test_cli.py`

#### Verification
```bash
cd sdk && pip install -e . && tracecraft --help
tracecraft status  # Should show connection info
```

#### Exit criteria
- `tracecraft --help` shows all commands
- `tracecraft status` tests server connection
- `tracecraft runs list` displays formatted output

---

## REVIEW GATE 1

**Reviewer**: Strongest model agent
**Checklist**:
- [ ] SDK 3-line setup produces traces in server database
- [ ] Full round-trip: SDK → Server Ingest → PostgreSQL → Query API → correct data returned
- [ ] Artifacts uploaded via SDK appear in SeaweedFS and are downloadable
- [ ] CLI can inspect runs created by SDK
- [ ] All tests pass across all 4 streams
- [ ] No hardcoded URLs, tokens, or secrets
- [ ] All invariants pass

---

## PHASE 2: INTEGRATIONS + LIVE

### Step S2.A — CrewAI Integration

**parallel_group**: P2
**depends_on**: [S1.A]
**estimated_effort**: 6 hours
**model_tier**: default

#### Context Brief
Build a CrewAI callback that auto-instruments CrewAI workflows. One line to add, captures everything automatically.

#### Target API:
```python
from tracecraft.integrations.crewai import TracecraftCrewCallback

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    callbacks=[TracecraftCrewCallback()]  # <-- one line
)
crew.kickoff()
# Everything tracked automatically
```

#### Auto-captures:
- Crew execution → Run
- Each CrewAI Agent → AgentInstance
- Each Task → parent Step
- Each LLM call within task → child Step (with tokens)
- Tool calls → Step + ToolCall
- Agent delegation → Event (handoff)
- Task outputs → Artifact

#### Tasks
- [ ] Create `sdk/tracecraft/integrations/__init__.py`
- [ ] Create `sdk/tracecraft/integrations/crewai.py` — `TracecraftCrewCallback`
- [ ] Create `examples/crewai_example.py` — working example with 2 agents
- [ ] Write integration test (mock CrewAI or use real CrewAI with simple task)

#### Files to create
- `sdk/tracecraft/integrations/crewai.py`
- `examples/crewai_example.py`
- `sdk/tests/test_integration_crewai.py`

#### Verification
```bash
cd sdk && pip install crewai && pytest tests/test_integration_crewai.py -v
python examples/crewai_example.py  # Should produce traces visible in server
```

---

### Step S2.B — Claude Agent SDK Integration

**parallel_group**: P2
**depends_on**: [S1.A]
**estimated_effort**: 6 hours
**model_tier**: default

#### Context Brief
Build hooks for the Claude Agent SDK. The SDK has a lifecycle hooks API that we can use for deep instrumentation including MCP tool calls.

#### Target API:
```python
from tracecraft.integrations.claude_sdk import tracecraft_hooks

agent = Agent(
    model="claude-sonnet-4-20250514",
    tools=[...],
    hooks=tracecraft_hooks()
)
```

#### Tasks
- [ ] Create `sdk/tracecraft/integrations/claude_sdk.py` — `tracecraft_hooks()` factory
- [ ] Create `examples/claude_sdk_example.py`
- [ ] Write integration test

#### Files to create
- `sdk/tracecraft/integrations/claude_sdk.py`
- `examples/claude_sdk_example.py`
- `sdk/tests/test_integration_claude.py`

---

### Step S2.C — LangGraph Integration

**parallel_group**: P2
**depends_on**: [S1.A]
**estimated_effort**: 6 hours
**model_tier**: default

#### Target API:
```python
from tracecraft.integrations.langgraph import TracecraftTracer
app = graph.compile()
result = app.invoke(input, config={"callbacks": [TracecraftTracer()]})
```

#### Files to create
- `sdk/tracecraft/integrations/langgraph.py`
- `examples/langgraph_example.py`
- `sdk/tests/test_integration_langgraph.py`

---

### Step S2.D — WebSocket Live Streaming

**parallel_group**: P2
**depends_on**: [S1.B]
**estimated_effort**: 6 hours
**model_tier**: default

#### Context Brief
Extend the existing WebSocket infrastructure (from gnosis-track's log_streamer) to stream live run events to connected dashboard clients.

#### WebSocket endpoints:
```
WS /ws/runs/{run_id}/live     # Live step/event stream for a specific run
WS /ws/runs/live               # Live stream of all active runs
```

#### Tasks
- [ ] Refactor `server/tracecraft_server/ws/live.py` from gnosis log_streamer
- [ ] Create fan-out manager: when ingest receives events, publish to subscribed WS clients
- [ ] Add connection management (heartbeat, reconnect, max connections)
- [ ] Write WS integration test

#### Files to create/modify
- `server/tracecraft_server/ws/live.py` (rewrite from gnosis)
- `server/tracecraft_server/ws/manager.py` (connection manager)
- `server/tests/test_ws_live.py`

---

## REVIEW GATE 2

**Checklist**:
- [ ] All 3 framework integrations produce correct trace data
- [ ] WebSocket live streaming works end-to-end
- [ ] Example scripts for each integration run successfully
- [ ] Integration tests pass
- [ ] All invariants pass

---

## PHASE 3: DASHBOARD + REPLAY

### Step S3.A — Dashboard Scaffold + Run Explorer

**parallel_group**: P3
**depends_on**: [S1.B, S2.D]
**estimated_effort**: 12 hours
**model_tier**: default

#### Context Brief
Build the web dashboard. Use Jinja2 + HTMX + Alpine.js (keeps the team in Python, extends existing gnosis-track UI infrastructure). Alternatively, use Next.js if frontend expertise is available.

#### Views:
1. **Experiment List** — table with name, run count, latest status, avg cost
2. **Run List** — filterable table with status, duration, cost, agent count
3. **Run Detail** — step timeline (waterfall), agent cards, metrics, artifacts
4. **Step Inspector** — click a step to see full input/output/tokens

#### Tasks
- [ ] Create dashboard route group in FastAPI
- [ ] Create experiment list page
- [ ] Create run list page with filters
- [ ] Create run detail page with step tree
- [ ] Create step inspector (expandable panel)
- [ ] Add HTMX for dynamic updates
- [ ] Style with Tailwind CSS (via CDN for simplicity)

---

### Step S3.B — Session Replay Engine + Player

**parallel_group**: P3
**depends_on**: [S1.A, S1.B, S1.C]
**estimated_effort**: 40 hours (SPLIT into S3.B.1 engine + S3.B.2 UI if parallelizing)
**model_tier**: strongest

#### Context Brief
This is the killer feature. Build a replay engine that reconstructs any past run step-by-step, showing agent state transitions, memory diffs, and decision points.

#### Recording (SDK side):
The SDK already records Steps with timestamps. Additionally, create a replay JSONL that is a denormalized, time-ordered stream of all events in a run. Store in SeaweedFS at `/{project}/{exp}/{run}/replay/{run_id}.replay.jsonl`.

#### Playback (Server + UI side):
- Server loads JSONL, indexes by timestamp
- Serves via WebSocket with play/pause/seek/speed controls
- UI renders timeline with agent lanes

#### Memory Diff:
- Compare consecutive MemorySnapshots for same agent
- JSON structural diff (not text diff)
- Render additions in green, removals in red

#### Tasks
- [ ] Create `sdk/tracecraft/replay.py` — JSONL recording (append events during run)
- [ ] Create `server/tracecraft_server/ws/replay.py` — replay server (load, index, stream)
- [ ] Create `server/tracecraft_server/services/replay.py` — replay engine (seek, speed control)
- [ ] Create `server/tracecraft_server/services/memory_diff.py` — JSON structural diff
- [ ] Create replay player UI page (timeline, VCR controls, agent lanes, step inspector)
- [ ] Create memory diff viewer (side-by-side with highlights)
- [ ] Write replay tests

---

### Step S3.C — Cost Tracking + Metrics Dashboard

**parallel_group**: P3
**depends_on**: [S1.B]
**estimated_effort**: 6 hours
**model_tier**: default

#### Tasks
- [ ] Create `server/tracecraft_server/services/cost.py`:
  - Load model pricing from `data/pricing.json`
  - Calculate cost per step: `(tokens_in * price_in / 1000) + (tokens_out * price_out / 1000)`
  - Aggregate cost per agent, per run, per experiment
- [ ] Create `data/pricing.json` — model pricing table
- [ ] Create cost dashboard page (per-run, per-agent, trends over time)
- [ ] Create metrics dashboard page (custom metrics, time series)

---

## REVIEW GATE 3

**Checklist**:
- [ ] Dashboard shows experiment/run/step data correctly
- [ ] Session replay plays back a multi-agent run end-to-end
- [ ] Memory diffs render correctly
- [ ] Cost tracking matches expected values
- [ ] All invariants pass

---

## PHASE 4: RESEARCH + LAUNCH

### Step S4.A — Benchmark Design + Data Collection

**parallel_group**: P4
**depends_on**: [S2.A, S2.B, S3.B]
**estimated_effort**: 12 hours (research-heavy)
**model_tier**: strongest

#### Context Brief
Design MAExBench (Multi-Agent Experiment Benchmark) — a standardized benchmark for evaluating multi-agent coordination, cost efficiency, and reliability. This is the highest-citation-potential research artifact.

#### Benchmark dimensions:
1. **Coordination efficiency**: Steps to complete task / minimum possible steps
2. **Communication overhead**: Inter-agent messages / task complexity
3. **Cost efficiency**: Total cost / task quality score
4. **Reliability**: Success rate across N runs of same task
5. **Delegation accuracy**: Did the right agent handle each subtask?

#### Tasks
- [ ] Define 10 benchmark tasks across 3 difficulty tiers
- [ ] Create `benchmarks/` directory with task definitions
- [ ] Create `benchmarks/runner.py` — automated benchmark runner using tracecraft
- [ ] Run benchmarks across CrewAI, LangGraph, Claude Agent SDK
- [ ] Collect results into standardized format
- [ ] Create benchmark results visualization

---

### Step S4.B — arXiv Paper Draft

**parallel_group**: P4-sequential (runs AFTER S4.A, NOT parallel)
**depends_on**: [S4.A]
**estimated_effort**: 20 hours (writing-heavy)
**model_tier**: strongest

#### Context Brief
Write the paper: "Tracecraft: An Open-Source Framework for Experiment Tracking and Session Replay in Multi-Agent LLM Systems"

#### Paper structure:
1. **Abstract** (150 words)
2. **Introduction** — the multi-agent evaluation gap
3. **Related Work** — Langfuse, LangSmith, AgentOps, MLflow (what they miss)
4. **Architecture** — data model, SDK, storage, replay
5. **MAExBench** — benchmark design and methodology
6. **Experiments** — results from benchmark runs
7. **Discussion** — what we learned about multi-agent behavior
8. **Conclusion + Future Work**

#### Tasks
- [ ] Create `paper/` directory
- [ ] Create `paper/tracecraft.tex` (LaTeX, NeurIPS format)
- [ ] Write each section
- [ ] Create figures (architecture diagram, benchmark results, replay screenshot)
- [ ] Write `paper/references.bib`
- [ ] Compile and proofread

#### Files to create
- `paper/tracecraft.tex`
- `paper/references.bib`
- `paper/figures/`

---

### Step S4.C — Launch Preparation

**parallel_group**: P4 (can parallel with S4.A)
**depends_on**: [ALL of Phase 1, Phase 2, Phase 3]
**estimated_effort**: 8 hours
**model_tier**: default

#### Tasks
- [ ] Write final README.md (GIF, 3-line setup, comparison table, architecture diagram)
- [ ] Publish `tracecraft` to PyPI
- [ ] Create GitHub release v0.1.0
- [ ] Write launch blog post: "Why We Built Tracecraft"
- [ ] Prepare HN Show post draft
- [ ] Record 90-second demo video
- [ ] Set up Discord server
- [ ] Create `CONTRIBUTING.md` + issue templates + 10 good-first-issues

---

## REVIEW GATE 4

**Checklist**:
- [ ] Benchmark runs produce meaningful, reproducible results
- [ ] Paper draft is complete and internally consistent
- [ ] PyPI package installs and works
- [ ] README is polished and compelling
- [ ] Demo video is recorded
- [ ] All invariants pass

---

## PHASE 5: PAYMENTS + SCALE (Post-Launch)

### Step S5.A — Crypto Payments

**depends_on**: [Phase 4 complete]
**estimated_effort**: 16 hours

#### Tasks
- [ ] Implement wallet-based auth (Bittensor wallet or EVM wallet → API key)
- [ ] Create prepaid credit system (send TAO/USDC → credits added)
- [ ] Build usage metering (trace count → credit deduction)
- [ ] Create payment status dashboard page
- [ ] Test with TAO testnet

### Step S5.B — Cloud Deployment

**depends_on**: [Phase 4 complete]
**estimated_effort**: 12 hours

#### Tasks
- [ ] Multi-tenant PostgreSQL (row-level security)
- [ ] Managed SeaweedFS or S3-compatible storage
- [ ] Auto-scaling FastAPI workers
- [ ] Deploy to cloud (Fly.io, Railway, or AWS)
- [ ] Set up monitoring (Prometheus + Grafana)

---

## APPENDIX A: CLAUDE.md Template for Tracecraft

```markdown
# Tracecraft

Open-source experiment tracking and session replay for multi-agent AI systems.

## Quick Reference
- SDK: `pip install tracecraft`
- Server: `docker compose -f docker-compose.dev.yml up`
- Tests: `cd sdk && pytest` / `cd server && pytest`
- CLI: `tracecraft --help`

## Architecture
- SDK (sdk/tracecraft/): Python SDK, 3-line setup, framework integrations
- Server (server/): FastAPI, PostgreSQL, SeaweedFS, WebSocket
- Dashboard: Jinja2 + HTMX (server/templates/)

## Data Model
Experiment → Run → AgentInstance → Step → ToolCall/MemorySnapshot
Artifacts stored in SeaweedFS, metadata in PostgreSQL.

## Key Files
- sdk/tracecraft/__init__.py — Public API (init, run)
- server/tracecraft_server/main.py — FastAPI app
- server/tracecraft_server/models/ — SQLAlchemy models
- server/tracecraft_server/api/v1/ — REST endpoints
- server/tracecraft_server/ws/ — WebSocket handlers

## Running
docker compose -f docker-compose.dev.yml up -d
cd sdk && pip install -e ".[dev]" && pytest
cd server && pip install -e ".[dev]" && pytest
```

---

## APPENDIX B: Effort Summary

| Phase | Steps | Total Effort | Parallelizable |
|-------|-------|-------------|----------------|
| Phase 0 | 3 | 13 hours | All 3 parallel |
| Phase 1 | 4 | 32 hours | All 4 parallel |
| Phase 2 | 4 | 24 hours | All 4 parallel |
| Phase 3 | 3 | 32 hours | All 3 parallel |
| Phase 4 | 3 | 40 hours | 2 parallel + 1 sequential |
| Phase 5 | 2 | 28 hours | Both parallel |
| **Total** | **19** | **169 hours** | **Max parallel: 4 agents** |

At 15 hours/week side project pace: ~12 weeks with parallelization, ~18 weeks serial.

With 2-4 Claude Code agents in parallel worktrees: each phase completes in 1-2 sessions.

---

---

## APPENDIX C: POST-REVIEW ERRATA (v1.1)

Adversarial review found 28 issues. Critical fixes applied inline above. Remaining items for agents to note:

### Data Model Fixes (apply in S0.2)
1. **Added User and Project entities** — Project is now a proper FK, not a string
2. **Step.parent_step_id rule**: Use `parent_step_id` (FK) for database queries, `parent_span_id` (string) only for OTel export. When constructing step tree, use `parent_step_id`.
3. **Add `deleted_at: datetime (nullable)` to Experiment, Run** for soft-delete
4. **Add `agent_id: UUID (fk, nullable)` to ToolCall** for direct agent queries
5. **Change `Metric.value` from `float` to `numeric(20,10)`** to match cost precision

### Framework Integration Pinning (apply in S2.A/B/C)
Pin versions in pyproject.toml extras:
```
crewai = ["crewai>=1.10,<2.0"]
langgraph = ["langgraph>=0.3,<1.0"]
claude-sdk = ["claude-agent-sdk>=0.1,<1.0"]
```

### Error Handling Strategy (apply across all steps)
- SDK: Never throw — log warning + buffer locally on server unreachable
- Server: Return 4xx/5xx with structured error JSON `{"error": "message", "code": "ERR_CODE"}`
- Transport: Exponential backoff (100ms, 200ms, 400ms, max 30s) with jitter
- WebSocket: Auto-reconnect with backoff; replay from last received event_id
- Artifacts: Retry upload 3x, then store path for manual retry

### Missing Step: S0.4 — CI/CD Pipeline
**depends_on**: [S0.1]
**effort**: 2 hours
- GitHub Actions workflow: lint (ruff), test (pytest), type check (mypy)
- Run on PR and push to main
- Matrix: Python 3.10, 3.11, 3.12

### Missing Step: S0.5 — Database Backup Script
**depends_on**: [S0.3]
**effort**: 1 hour
- `scripts/backup.sh`: pg_dump to timestamped file
- Document in README

### Rate Limiting (apply in S1.B)
- Ingest endpoint: 100 requests/minute per API key
- Max batch size: 500 events per request
- Max request body: 10MB

### Migration Strategy Between Phases
- Each phase that adds new models MUST create a new Alembic migration
- Migrations MUST be backwards compatible (additive only, no column drops)
- Migration files go in `server/alembic/versions/` with naming: `{phase}_{step}_{description}.py`

### Corrected Effort Summary (v1.1)

| Phase | Steps | Total Effort | Parallelizable |
|-------|-------|-------------|----------------|
| Phase 0 | 5 | 20 hours | S0.2+S0.3+S0.4 parallel after S0.1 |
| Phase 1 | 4 | 44 hours | S1.A-D parallel (S1.A is critical path at 30h) |
| Phase 2 | 4 | 24 hours | All 4 parallel |
| Phase 3 | 3 | 58 hours | All 3 parallel (S3.B is critical path at 40h) |
| Phase 4 | 3 | 40 hours | S4.A+S4.C parallel, then S4.B sequential |
| Phase 5 | 2 | 28 hours | Both parallel |
| **Total** | **21** | **214 hours** | **Critical path: ~20 weeks serial, ~14 weeks parallel** |

At 15h/week side project pace with 2-4 Claude Code agents in parallel worktrees: **~10-14 weeks**.

---

*This blueprint is a living document. Update step status as work progresses.*
