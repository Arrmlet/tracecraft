# Gnosis-Track Pivot: Multi-Agent Experiment Tracker & Storage Platform

## Execution Blueprint

**Document Version:** 1.0
**Date:** 2026-03-21
**Timeline:** 18 weeks (Phases 0-4) + 8 months (Phase 5)

---

## Executive Summary

This blueprint details the transformation of gnosis-track (Python logging system with SeaweedFS storage, FastAPI UI, JWT auth) into an open-source multi-agent experiment tracking and observability platform. The AI agent framework market reached $7.84B in 2025 and is projected to hit $52.62B by 2030 (CAGR 46.3%). Gartner predicts 40% of enterprise applications will feature task-specific AI agents by end of 2026. The observability layer for these agents is fragmented, and there is a clear gap for an open-source, storage-first experiment tracker that treats agent artifacts as first-class citizens.

### Competitive Landscape (March 2026)

| Tool | Positioning | Weakness We Exploit |
|------|-------------|---------------------|
| Langfuse | Open-source LLM observability (MIT) | No native artifact/file storage; tracing-only |
| LangSmith | LangChain-coupled observability | Vendor lock-in to LangChain ecosystem |
| Braintrust | Evaluation-first platform | Closed source; no self-host option |
| AgentOps | Agent-specific monitoring | Limited storage; no replay capability |
| MLflow | General ML experiment tracking | Agent support bolted on; not agent-native |
| Weights & Biases | ML experiment tracking | $50/user/mo; heavy; not agent-native |

**Our wedge:** The only open-source platform that combines OpenTelemetry-native agent tracing with built-in artifact storage (SeaweedFS), session replay, and framework-agnostic SDK. Gnosis-track already has the storage layer and auth -- competitors would need to build this from scratch.

---

## Phase 0: Foundation (Weeks 1-2)

### 0.1 Project Naming

**Recommended name: `tracecraft`**

Rationale:
- Available on PyPI (verified via search)
- No existing GitHub projects with significant traction
- Communicates both tracing and craftsmanship
- Works as a CLI command (`tracecraft`), Python import (`import tracecraft`), and brand
- Short, memorable, no hyphens (important for Python imports)
- Domain likely available (.dev, .io)

**Runner-up alternatives:**
| Name | Pros | Cons |
|------|------|------|
| `runledger` | Financial metaphor (ledger of runs), available on PyPI | Less intuitive |
| `agentledger` | Clear purpose | Long; "agent" prefix is crowded |
| `tracevault` | Storage emphasis | Sounds like a backup tool |

**Action items:**
- [ ] Register `tracecraft` on PyPI (placeholder package)
- [ ] Register `tracecraft.dev` domain
- [ ] Create `tracecraft` GitHub organization
- [ ] Register `@tracecraft` on X/Twitter

### 0.2 Repository Restructure

**Current gnosis-track structure (assumed):**
```
gnosis-track/
  app/              # FastAPI application
  storage/          # SeaweedFS integration
  auth/             # JWT auth
  ...
```

**Target structure:**
```
tracecraft/
  README.md
  LICENSE                    # Apache 2.0 (standard for infra OSS)
  pyproject.toml             # Modern Python packaging
  CONTRIBUTING.md
  docs/
    architecture.md
    quickstart.md
    self-hosting.md
  sdk/
    python/
      tracecraft/
        __init__.py          # 3-line setup exports
        client.py            # Core client
        run.py               # Run/Experiment abstractions
        agent.py             # Agent-specific tracing
        step.py              # Step/Span tracking
        artifacts.py         # File/artifact storage
        otel.py              # OpenTelemetry bridge
        integrations/
          crewai.py
          langgraph.py
          claude_sdk.py
          autogen.py
          openai_agents.py
        exporters/
          json.py
          csv.py
          otlp.py
      tests/
      pyproject.toml
    typescript/              # Phase 3 -- placeholder
  server/
    app/
      main.py               # FastAPI entrypoint
      api/
        v1/
          runs.py
          experiments.py
          agents.py
          artifacts.py
          auth.py
          search.py
      core/
        config.py
        security.py          # JWT auth (from gnosis-track)
        database.py
      models/
        run.py
        experiment.py
        agent.py
        step.py
        artifact.py
        metric.py
      services/
        storage.py           # SeaweedFS integration (from gnosis-track)
        tracing.py
        replay.py
        cost.py
      otel/
        collector.py         # OTLP receiver
        processor.py
    tests/
    Dockerfile
    docker-compose.yml       # Server + SeaweedFS + Postgres
  dashboard/
    src/                     # React/Next.js (Phase 2)
  examples/
    quickstart/
    crewai_example/
    langgraph_example/
    claude_sdk_example/
```

### 0.3 Core Data Model

```
Experiment (top-level grouping)
  |-- name: str
  |-- description: str
  |-- tags: dict
  |-- created_at: datetime
  |
  +-- Run (single execution of an experiment)
       |-- run_id: uuid
       |-- experiment_id: fk
       |-- status: enum(running, completed, failed, cancelled)
       |-- params: dict              # hyperparameters, config
       |-- metrics: dict             # final metrics
       |-- cost: CostRecord          # total token cost
       |-- started_at: datetime
       |-- ended_at: datetime
       |
       +-- Agent (participant in a run)
       |    |-- agent_id: uuid
       |    |-- run_id: fk
       |    |-- name: str
       |    |-- role: str
       |    |-- model: str           # e.g., claude-sonnet-4-20250514
       |    |-- framework: str       # e.g., crewai, langgraph
       |    |-- config: dict
       |
       +-- Step (unit of work -- maps to OTel span)
       |    |-- step_id: uuid
       |    |-- trace_id: str        # OTel trace ID
       |    |-- span_id: str         # OTel span ID
       |    |-- parent_span_id: str
       |    |-- run_id: fk
       |    |-- agent_id: fk (nullable)
       |    |-- step_type: enum(llm_call, tool_call, retrieval,
       |    |                   human_input, decision, handoff)
       |    |-- name: str
       |    |-- input: json
       |    |-- output: json
       |    |-- tokens_in: int
       |    |-- tokens_out: int
       |    |-- cost: decimal
       |    |-- model: str
       |    |-- latency_ms: int
       |    |-- status: enum(ok, error)
       |    |-- error: str (nullable)
       |    |-- metadata: dict
       |    |-- started_at: datetime
       |    |-- ended_at: datetime
       |
       +-- Artifact (stored file/object)
            |-- artifact_id: uuid
            |-- run_id: fk
            |-- step_id: fk (nullable)
            |-- agent_id: fk (nullable)
            |-- name: str
            |-- content_type: str
            |-- size_bytes: int
            |-- storage_key: str     # SeaweedFS key
            |-- metadata: dict
            |-- created_at: datetime
```

**OpenTelemetry alignment:** The Step model maps directly to OTel spans with `gen_ai.*` semantic conventions. Steps carry `trace_id` and `span_id` to enable bidirectional linking between tracecraft's storage and any OTel-compatible backend (Jaeger, Datadog, etc.).

### 0.4 New README and Positioning

**Tagline:** "Open-source experiment tracking for AI agents. Trace every decision. Store every artifact. Replay any session."

**Positioning statement:** tracecraft is the open-source platform for teams building with AI agents. Unlike LLM observability tools that only capture traces, tracecraft combines OpenTelemetry-native tracing with built-in artifact storage, giving you a complete record of what your agents did, why they did it, and everything they produced.

**README structure:**
1. One-liner + badge row
2. 30-second GIF showing dashboard with agent trace replay
3. "Get started in 3 lines" code block
4. Feature comparison table vs. Langfuse, LangSmith, MLflow
5. Framework integrations (icons/badges)
6. Architecture diagram
7. Self-hosting quickstart (docker-compose)
8. Contributing guide link
9. License (Apache 2.0)

### Phase 0 Deliverables

| Deliverable | Owner | Est. Effort |
|-------------|-------|-------------|
| Name registration (PyPI, domain, GitHub org, X) | 1 person | 2 hours |
| Repository restructure + migration from gnosis-track | 1 person | 3 days |
| Data model design + SQLAlchemy/Alembic models | 1 person | 3 days |
| README + CONTRIBUTING.md + LICENSE | 1 person | 1 day |
| CI/CD setup (GitHub Actions: lint, test, build) | 1 person | 1 day |
| docker-compose for local dev (FastAPI + Postgres + SeaweedFS) | 1 person | 2 days |

**Success Metrics:**
- Repository publicly visible with clean structure
- `docker-compose up` starts a working server (no SDK yet)
- Data model reviewed and finalized
- PyPI name reserved

**Dependencies:** None (greenfield from gnosis-track codebase)

**Risk Factors:**
- Name collision discovered late (mitigate: register everything in week 1 day 1)
- Data model needs revision after Phase 1 SDK work begins (mitigate: keep migrations lightweight, expect 1-2 schema changes)

---

## Phase 1: Core SDK (Weeks 3-6)

### 1.1 Python SDK with 3-Line Setup

**Target developer experience:**

```python
import tracecraft

# Option A: Hosted / self-hosted server
tracecraft.init(api_key="tc-xxx", project="my-agent")

# Option B: Local file-based (zero infra)
tracecraft.init(backend="local", path="./traces")
```

Then, anywhere in agent code:

```python
with tracecraft.run("research-task") as run:
    run.log_params({"model": "claude-sonnet-4-20250514", "temperature": 0.7})

    with run.step("search", step_type="tool_call") as step:
        result = search_tool(query)
        step.log_input({"query": query})
        step.log_output(result)

    with run.step("synthesize", step_type="llm_call") as step:
        response = llm.complete(prompt)
        step.log_tokens(input=1200, output=450, model="claude-sonnet-4-20250514")

    run.log_artifact("report.pdf", open("report.pdf", "rb"))
    run.log_metrics({"quality_score": 0.92, "total_cost": 0.034})
```

**SDK architecture:**
- Async-first with sync wrappers (same pattern as Langfuse)
- Background queue for trace/artifact uploads (non-blocking)
- Batched uploads (configurable flush interval, default 5s)
- Graceful shutdown with `atexit` hook
- Thread-safe context management via `contextvars`
- Offline mode: queue to local SQLite, sync when server available

### 1.2 OpenTelemetry Compatibility

Two modes of operation:

**Mode 1 -- Native SDK (recommended):**
tracecraft SDK generates OTel-compatible span data internally but ships it directly to the tracecraft server via its own efficient protocol (protobuf over HTTP/2). The server stores spans in Postgres and artifacts in SeaweedFS.

**Mode 2 -- OTel Collector bridge:**
tracecraft server exposes an OTLP receiver endpoint. Any OTel-instrumented application can send spans to tracecraft. The server enriches spans with tracecraft-specific attributes (artifact links, cost tracking) via a processing pipeline.

**OTel semantic convention alignment:**
```
gen_ai.system         -> step.model provider
gen_ai.request.model  -> step.model
gen_ai.usage.input_tokens  -> step.tokens_in
gen_ai.usage.output_tokens -> step.tokens_out
gen_ai.agent.name     -> agent.name
gen_ai.task.name      -> step.name (when step_type=task)
```

### 1.3 Artifact Storage

Leverage gnosis-track's existing SeaweedFS integration:

```python
# Store any file
run.log_artifact("output.csv", dataframe.to_csv())
run.log_artifact("screenshot.png", open("screen.png", "rb"))

# Store structured data
run.log_artifact("chain_of_thought.json", cot_data, content_type="application/json")

# Retrieve later
artifact = tracecraft.get_artifact(run_id="xxx", name="output.csv")
```

**Artifact types with special handling:**
- JSON: Rendered inline in dashboard, diffable between runs
- Images: Thumbnail generation, gallery view
- CSV/Parquet: Column stats, preview rows in dashboard
- Text/Markdown: Rendered with syntax highlighting
- Audio: Waveform display, playback (for voice agents)

### 1.4 First Framework Integration: CrewAI

**Why CrewAI first:**
1. **Largest community** -- 44,600+ GitHub stars, most active multi-agent community
2. **Native MCP + A2A support** (v1.10.1) -- aligns with our protocol strategy
3. **Clear instrumentation points** -- CrewAI has well-defined Agent, Task, Crew abstractions that map cleanly to our data model
4. **No dominant tracker** -- CrewAI users currently scatter across Langfuse, AgentOps, and custom logging; no winner-take-all yet
5. **Rapid prototyping audience** -- CrewAI users value quick setup, matching our 3-line philosophy

**Integration approach:**

```python
from tracecraft.integrations.crewai import TracecraftCallback

crew = Crew(
    agents=[researcher, writer],
    tasks=[research_task, write_task],
    callbacks=[TracecraftCallback()]  # single line addition
)
```

The callback auto-captures:
- Crew execution as a Run
- Each Agent as an Agent entity with role/model/config
- Each Task as a parent Step
- Each LLM call within a task as a child Step (with token counts)
- Tool calls as Steps with input/output
- Agent delegation/handoff events
- Final task outputs as Artifacts

### Phase 1 Deliverables

| Deliverable | Est. Effort | Priority |
|-------------|-------------|----------|
| `tracecraft` Python SDK core (init, run, step, agent) | 5 days | P0 |
| Background upload queue + batching | 3 days | P0 |
| Artifact upload/download via SeaweedFS | 3 days | P0 |
| Server API v1 endpoints (CRUD for all entities) | 4 days | P0 |
| OTel span export (native mode) | 2 days | P0 |
| OTLP receiver endpoint on server | 3 days | P1 |
| CrewAI integration + callback | 3 days | P0 |
| Local/offline backend (SQLite) | 2 days | P1 |
| End-to-end integration tests | 3 days | P0 |
| Quickstart example (CrewAI + tracecraft) | 1 day | P0 |
| SDK documentation (docstrings + docs/) | 2 days | P1 |

**Total estimated effort:** ~31 person-days (achievable by 2 engineers in 4 weeks)

**Success Metrics:**
- SDK published to PyPI as `tracecraft` (alpha)
- `pip install tracecraft` + 3 lines of code produces traces visible in API
- CrewAI example runs end-to-end with all steps captured
- Artifact upload/download round-trip works
- <5ms overhead per step (non-blocking)
- OTLP receiver accepts spans from any OTel-instrumented app

**Dependencies:**
- Phase 0 complete (data model, server skeleton)
- SeaweedFS client library from gnosis-track working with new schema

**Risk Factors:**
- CrewAI callback API may change between versions (mitigate: pin to v1.10.x, test against nightly)
- Batching/async complexity (mitigate: model after Langfuse's proven approach -- they open-sourced their batching logic)
- SeaweedFS performance for many small artifacts (mitigate: batch small artifacts, compress before upload)

---

## Phase 2: Dashboard & Replay (Weeks 7-10)

### 2.1 Real-Time Agent Monitoring Dashboard

**Technology choice:** Next.js 15 + React 19 + Tailwind CSS + shadcn/ui

Rationale: This is the standard stack for OSS developer tools in 2026 (used by Langfuse, Cal.com, Infisical). Enables SSR for fast initial load, great DX, and large contributor pool.

**Dashboard views:**

1. **Experiment List** -- Table of experiments with run counts, latest status, avg cost
2. **Run Detail** -- Timeline view of all steps in a run, with:
   - Waterfall chart (like Chrome DevTools network tab) showing step timing
   - Nested span tree (parent/child steps)
   - Click-to-expand for input/output of any step
   - Token usage breakdown per step
   - Cost accumulation graph
3. **Agent View** -- Per-agent breakdown across runs:
   - Which agents participate in which tasks
   - Agent performance metrics (avg latency, error rate, cost)
   - Model comparison (same agent, different models)
4. **Artifact Browser** -- File manager interface:
   - Grid/list view of all artifacts for a run
   - Inline preview (JSON, images, text, CSV)
   - Diff view between artifacts from different runs
5. **Live View** -- Real-time streaming of active runs:
   - WebSocket connection to server
   - Steps appear as they complete
   - Live cost counter
   - Alert on errors

### 2.2 Session Replay System

**The killer feature that no competitor offers with artifact storage.**

Session replay reconstructs the full execution of an agent run as a navigable timeline:

```
[00:00.000] Run started: "research-and-write"
[00:00.012] Agent "researcher" activated
[00:00.150] Step: LLM call (claude-sonnet-4-20250514) -- "Plan research approach"
             Input: {system_prompt: "...", user_message: "..."}
             Output: "I'll search for 3 topics..."
             Tokens: 450 in / 230 out | Cost: $0.002 | Latency: 1.2s
[00:01.400] Step: Tool call (web_search) -- query: "AI agent frameworks 2026"
             Output: [5 results...]
[00:02.100] Step: LLM call -- "Synthesize findings"
             ...
[00:04.500] Artifact saved: "research_notes.md" (2.3KB)
[00:04.520] Agent handoff: researcher -> writer
[00:04.600] Agent "writer" activated
             ...
[00:08.200] Artifact saved: "final_report.pdf" (45KB)
[00:08.250] Run completed. Total cost: $0.034
```

**Implementation:**
- Server stores Steps with precise timestamps and ordering
- Dashboard fetches the full step sequence and renders a VCR-style player
- Play/pause/seek controls with speed adjustment (1x, 2x, 5x, 10x)
- Click any step to inspect full input/output
- Click any artifact to preview/download
- Shareable replay links (for team debugging)

### 2.3 Cost Tracking

**Per-step cost calculation:**
- SDK sends model name + token counts per step
- Server maintains a pricing table (updated weekly via GitHub-hosted JSON):
  ```json
  {
    "claude-sonnet-4-20250514": {"input_per_1k": 0.003, "output_per_1k": 0.015},
    "gpt-4o": {"input_per_1k": 0.0025, "output_per_1k": 0.01},
    ...
  }
  ```
- Dashboard shows:
  - Cost per step, per agent, per run, per experiment
  - Cost trends over time (are runs getting cheaper or more expensive?)
  - Cost comparison: same experiment, different models
  - Budget alerts: notify when a run exceeds threshold

### 2.4 Metrics and Analytics

**Built-in metrics:**
- Run success rate (% completed vs. failed)
- Average run duration
- Token efficiency (output quality / tokens consumed)
- Agent utilization (time active vs. waiting)
- Tool call frequency and success rate
- Error categorization (model errors, tool errors, timeout, etc.)

**Custom metrics:**
```python
run.log_metrics({
    "answer_relevance": 0.92,    # from eval
    "hallucination_score": 0.03,  # from eval
    "user_satisfaction": 4.5,     # from feedback
})
```

**Analytics dashboard:**
- Time-series charts for all metrics
- Experiment comparison (A/B between configurations)
- Regression detection (metric drops between runs)

### Phase 2 Deliverables

| Deliverable | Est. Effort | Priority |
|-------------|-------------|----------|
| Dashboard scaffold (Next.js + auth + layout) | 3 days | P0 |
| Experiment list + run list views | 3 days | P0 |
| Run detail view with span tree + waterfall | 5 days | P0 |
| Session replay player (timeline + VCR controls) | 5 days | P0 |
| Artifact browser with inline preview | 3 days | P0 |
| Live view (WebSocket streaming) | 3 days | P1 |
| Cost tracking (server-side calculation + dashboard) | 3 days | P0 |
| Metrics dashboard (time-series charts) | 3 days | P1 |
| Agent performance view | 2 days | P1 |
| Docker image for dashboard | 1 day | P0 |

**Total estimated effort:** ~31 person-days (2 engineers, 4 weeks, with frontend focus)

**Success Metrics:**
- Dashboard accessible at `localhost:3000` via docker-compose
- Run detail page loads <2s for runs with 500+ steps
- Session replay plays back a CrewAI multi-agent run end-to-end
- Cost tracking accurate to within 1% of actual API bills
- Live view updates within 500ms of step completion

**Dependencies:**
- Phase 1 SDK and server API complete
- At least 1 framework integration producing real trace data

**Risk Factors:**
- Frontend complexity (mitigate: use shadcn/ui components, avoid custom charting -- use Recharts)
- WebSocket scalability for live view (mitigate: use server-sent events as fallback, simpler to scale)
- Model pricing data maintenance (mitigate: community-contributed JSON file in repo, CI validates format)

---

## Phase 3: Integrations (Weeks 11-14)

### Integration Priority Order

Based on March 2026 market data:

| Framework | GitHub Stars | Monthly Downloads | Why Integrate |
|-----------|-------------|-------------------|---------------|
| CrewAI | 44,600 | High | Done in Phase 1. Largest multi-agent community |
| LangGraph | ~35k | 34.5M/mo | Highest enterprise adoption; stateful workflows |
| Claude Agent SDK | ~15k | Growing fast | MCP-native; Anthropic ecosystem; underserved by existing tools |
| OpenAI Agents SDK | ~20k | Very high | Simplest framework; massive OpenAI user base |
| Microsoft Agent Framework (AutoGen) | ~38k | Moderate | Enterprise; merged AutoGen+Semantic Kernel |

### 3.1 LangGraph Integration

```python
from tracecraft.integrations.langgraph import TracecraftTracer

# As a LangChain callback
app = create_graph(...)
result = app.invoke(input, config={"callbacks": [TracecraftTracer()]})
```

**What we capture:**
- Graph structure (nodes, edges, conditional branching)
- State snapshots at each node (LangGraph's key differentiator is state management)
- Checkpoint data for human-in-the-loop workflows
- Subgraph invocations as nested spans
- Channel messages between nodes

**Dashboard enhancement:** Graph visualization showing execution path through the LangGraph, with nodes color-coded by status (completed/failed/skipped).

**Effort:** 5 days

### 3.2 Claude Agent SDK Integration

```python
from tracecraft.integrations.claude_sdk import tracecraft_hooks

agent = Agent(
    model="claude-sonnet-4-20250514",
    tools=[...],
    hooks=tracecraft_hooks()  # Lifecycle hooks
)
```

**What we capture:**
- Agent lifecycle events (init, turn start/end, tool use)
- MCP server connections and tool discovery
- MCP tool calls with full input/output
- Model reasoning steps
- Token usage per turn
- Handoffs between agents (multi-agent patterns)

**Unique value:** Claude Agent SDK's hook system provides deep instrumentation points. We capture MCP tool metadata (server name, tool schema) that no other tracker stores, enabling MCP-specific analytics.

**Effort:** 4 days

### 3.3 OpenAI Agents SDK Integration

```python
from tracecraft.integrations.openai_agents import TracecraftTraceProvider

# Replace default tracing
from agents import set_trace_provider
set_trace_provider(TracecraftTraceProvider())
```

OpenAI Agents SDK has a built-in tracing interface with `set_trace_provider`. We implement their `TraceProvider` protocol to capture all spans natively.

**Effort:** 3 days

### 3.4 Microsoft Agent Framework (AutoGen) Integration

```python
from tracecraft.integrations.autogen import TracecraftRuntime

runtime = TracecraftRuntime()  # wraps SingleThreadedAgentRuntime
await runtime.register(MyAgent)
```

**What we capture:**
- Agent registration and message routing
- Inter-agent messages
- Tool executions
- Group chat orchestration

**Effort:** 4 days

### Phase 3 Deliverables

| Deliverable | Est. Effort | Priority |
|-------------|-------------|----------|
| LangGraph integration + example | 5 days | P0 |
| Claude Agent SDK integration + example | 4 days | P0 |
| OpenAI Agents SDK integration + example | 3 days | P0 |
| Microsoft Agent Framework integration + example | 4 days | P1 |
| Pydantic AI integration + example | 2 days | P2 |
| Integration test suite (all frameworks) | 3 days | P0 |
| Dashboard: graph visualization for LangGraph | 3 days | P1 |
| Dashboard: MCP tool analytics view | 2 days | P1 |
| Documentation for all integrations | 3 days | P0 |

**Total estimated effort:** ~29 person-days

**Success Metrics:**
- All 4 major framework integrations published and documented
- Each integration adds <3 lines of code to existing agent applications
- Integration tests pass against latest stable version of each framework
- At least 1 example project per integration in `examples/` directory
- Zero-config auto-detection: if CrewAI/LangGraph is installed, offer to auto-instrument

**Dependencies:**
- Phase 1 SDK stable (no breaking API changes)
- Phase 2 dashboard functional (integrations need visual verification)

**Risk Factors:**
- Framework API breaking changes (mitigate: version-pinned integration modules, CI matrix testing against multiple versions)
- Claude Agent SDK is relatively new; API may be volatile (mitigate: tight feedback loop with Anthropic developer relations)
- Testing multi-framework in CI is expensive (mitigate: mock-based unit tests + weekly full integration test run)

---

## Phase 4: Community & Launch (Weeks 15-18)

### 4.1 Hacker News Launch Strategy

**Timing:** Mid-week (Tuesday or Wednesday), 9-10 AM ET

**Title format:** "Show HN: Tracecraft -- Open-source experiment tracking for AI agents (trace, store, replay)"

**Post body structure:**
1. One-sentence problem statement
2. What tracecraft does differently (artifact storage + replay)
3. 3-line code example
4. Link to live demo (pre-recorded video or hosted playground)
5. "We're open source (Apache 2.0) and self-hostable"
6. Ask: "What frameworks/features should we prioritize next?"

**Pre-launch preparation (2 weeks before):**
- [ ] Deploy a public demo instance (read-only, pre-populated with interesting multi-agent traces)
- [ ] Record a 90-second demo video showing: install -> instrument CrewAI app -> see traces in dashboard -> replay session
- [ ] Write the HN post and get feedback from 5 developer friends
- [ ] Ensure `pip install tracecraft` works flawlessly
- [ ] Ensure `docker-compose up` starts everything in <60 seconds
- [ ] Prepare for traffic: have the FAQ ready, monitor GitHub issues

**Day-of protocol:**
- Post at 9 AM ET
- Founder responds to every comment within 30 minutes for the first 4 hours
- Do NOT ask friends to upvote (HN detects and penalizes this)
- Share on X/Twitter only after HN post is 2+ hours old

### 4.2 GitHub Optimization

**README checklist:**
- [ ] Animated GIF/video at top (max 15 seconds, shows the "aha" moment)
- [ ] Badges: PyPI version, downloads, GitHub stars, license, CI status, Discord members
- [ ] "Get Started in 30 Seconds" section with copy-pasteable code
- [ ] Feature comparison table (tracecraft vs. Langfuse vs. LangSmith vs. MLflow)
- [ ] Framework integration logos (CrewAI, LangGraph, Claude, OpenAI, AutoGen)
- [ ] Architecture diagram (simple, not overwhelming)
- [ ] "Self-host in 1 minute" docker-compose snippet
- [ ] Contributing section with "good first issues" link
- [ ] Star history chart (add after 50+ stars)

**Repository hygiene:**
- [ ] Issue templates (bug report, feature request, integration request)
- [ ] PR template
- [ ] `good-first-issue` labels on 10+ issues
- [ ] GitHub Discussions enabled
- [ ] GitHub Sponsors enabled
- [ ] Release notes for every version (auto-generated + curated)

### 4.3 Content Strategy

**Blog posts (publish on blog.tracecraft.dev + cross-post to dev.to and Medium):**

| Week | Title | Purpose |
|------|-------|---------|
| 15 | "Why We Built Tracecraft: The Missing Layer in Agent Observability" | Origin story, problem statement |
| 16 | "Debugging a 47-Step CrewAI Agent in 5 Minutes with Tracecraft" | Tutorial, SEO for "CrewAI debugging" |
| 17 | "OpenTelemetry for AI Agents: A Practical Guide" | Technical depth, SEO for "OTel AI agents" |
| 18 | "Session Replay for AI Agents: See Exactly What Your Agent Did" | Feature showcase, differentiation |

**Video content:**
- 90-second product demo (for HN, X, README)
- 10-minute "Getting Started" tutorial (YouTube)
- 5-minute integration walkthrough per framework (YouTube series)

**Social media:**
- X/Twitter: 3 posts/week (tips, feature highlights, community showcases)
- Discord: Active community server with channels per framework
- Reddit: Engage in r/MachineLearning, r/LangChain, r/LocalLLaMA (contribute value, don't spam)

### 4.4 First 100 Stars Strategy

Based on research into successful OSS launches:

**Week 1-2 (Stars 0-30): Inner circle**
- Personal outreach to developer friends and colleagues
- Post in private Slack/Discord communities you're already active in
- Ask for genuine feedback, not just stars

**Week 2-3 (Stars 30-70): Warm community**
- Post in CrewAI Discord (with a real CrewAI example, not just self-promotion)
- Post in LangChain Discord
- Answer Stack Overflow questions about agent debugging, link to tracecraft where relevant
- Submit to dev.to and Hashnode

**Week 3-4 (Stars 70-100+): Public launch**
- Hacker News Show HN post
- X/Twitter thread with demo video
- Product Hunt launch (same week, different day from HN)
- r/MachineLearning post (weekend, as a "Project" flair)

### 4.5 PyPI Package

**Package name:** `tracecraft`
**Initial version:** `0.1.0` (signal: early but usable)

```
pip install tracecraft              # SDK only
pip install tracecraft[server]      # SDK + server dependencies
pip install tracecraft[crewai]      # SDK + CrewAI integration
pip install tracecraft[langgraph]   # SDK + LangGraph integration
pip install tracecraft[all]         # Everything
```

**Release cadence:** Weekly during Phase 4, biweekly after stabilization

### Phase 4 Deliverables

| Deliverable | Est. Effort | Priority |
|-------------|-------------|----------|
| Demo instance deployment | 2 days | P0 |
| Demo video (90s + 10min) | 3 days | P0 |
| README finalization + GIF creation | 2 days | P0 |
| Blog post #1 (origin story) | 1 day | P0 |
| Blog post #2 (CrewAI tutorial) | 1 day | P0 |
| Blog post #3 (OTel guide) | 1 day | P1 |
| Blog post #4 (session replay) | 1 day | P1 |
| HN launch execution | 1 day | P0 |
| Product Hunt listing | 1 day | P1 |
| Discord server setup + moderation plan | 1 day | P0 |
| GitHub issue/PR templates + good-first-issues | 1 day | P0 |
| PyPI package with extras | 1 day | P0 |
| docs site (Mintlify or Docusaurus) | 3 days | P0 |

**Total estimated effort:** ~19 person-days

**Success Metrics:**
- 100+ GitHub stars within 4 weeks of public launch
- HN front page (top 30) for at least 4 hours
- 50+ PyPI downloads in first week
- 20+ Discord members
- 5+ GitHub issues from external contributors
- 1+ external PR (even a typo fix counts)

**Dependencies:**
- Phases 1-3 complete and stable
- Demo-quality examples for at least 2 frameworks

**Risk Factors:**
- HN post doesn't gain traction (mitigate: have backup launch channels ready; post quality matters more than timing)
- Negative feedback on HN (mitigate: be responsive and genuine; incorporate feedback publicly)
- Demo instance goes down during launch (mitigate: over-provision, test under load, have a backup video)

---

## Phase 5: Monetization (Months 5-12)

### 5.1 Managed Cloud Service

**URL:** `app.tracecraft.dev`

**Architecture:**
- Multi-tenant SaaS on AWS/GCP
- Tenant isolation via row-level security (Postgres) + namespace-prefixed SeaweedFS keys
- Auto-scaling FastAPI workers behind ALB
- Managed SeaweedFS cluster (or migrate to S3-compatible storage for cloud tier)
- CDN for dashboard static assets

**Pricing model (based on Langfuse's proven structure):**

| Tier | Price | Included | Target |
|------|-------|----------|--------|
| **Free** | $0/mo | 50,000 steps/mo, 1GB artifacts, 30-day retention, 2 users | Individual developers |
| **Pro** | $49/mo | 500,000 steps/mo, 25GB artifacts, 1-year retention, 10 users | Small teams |
| **Team** | $199/mo | 5,000,000 steps/mo, 100GB artifacts, 3-year retention, unlimited users | Growing teams |
| **Enterprise** | Custom | Unlimited, custom retention, SSO/SAML, audit log, SLA, dedicated support | Large organizations |

**Overage pricing:** $5 per 100,000 additional steps; $0.50 per GB additional artifact storage

**Why this works:**
- Free tier is generous enough to get adoption (Langfuse's 50k free traces drove massive adoption)
- Pro price point ($49) is less than Langfuse Core ($29) + typical overage, but includes artifact storage they don't offer
- Team tier competes with Weights & Biases ($50/user/mo) but is per-team, not per-user
- Artifact storage as a differentiator justifies the price -- competitors charge nothing because they don't offer it

### 5.2 Enterprise Features (Gated, Not Open-Core)

The core product remains fully open source (Apache 2.0). Enterprise features are additional modules available only on the managed cloud or with an enterprise license:

| Feature | Description | Phase |
|---------|-------------|-------|
| **SSO/SAML** | Okta, Azure AD, Google Workspace integration | Month 6 |
| **Audit Log** | Immutable log of all user actions | Month 6 |
| **RBAC** | Role-based access control (viewer, editor, admin) | Month 7 |
| **Data Residency** | Choose region for data storage (EU, US, APAC) | Month 8 |
| **SOC 2 Type II** | Compliance certification | Month 9 |
| **Priority Support** | Dedicated Slack channel, 4-hour SLA | Month 6 |
| **Custom Integrations** | Professional services for bespoke framework integration | Month 7 |
| **Team Analytics** | Cross-team usage dashboards, cost allocation | Month 8 |
| **Evaluation Pipelines** | Automated eval runs on schedule, regression alerts | Month 10 |
| **Agent Benchmarking** | Standardized benchmark suite, leaderboard | Month 12 |

### 5.3 Revenue Projections (Conservative)

| Month | Cloud Users (free) | Cloud Users (paid) | MRR | Notes |
|-------|-------------------|-------------------|-----|-------|
| 5 | 50 | 2 | $298 | Soft launch to early adopters |
| 6 | 200 | 8 | $1,192 | Post-HN traction |
| 8 | 800 | 25 | $3,725 | Word-of-mouth growth |
| 10 | 2,000 | 60 | $8,940 | First enterprise deal |
| 12 | 5,000 | 120 | $22,880 | Mature pipeline |

### 5.4 Long-Term Business Model Options

1. **Open-core SaaS** (recommended): Free self-host, paid cloud with enterprise features. This is the Langfuse/GitLab model and has the strongest product-market fit for developer tools.

2. **Marketplace**: Once tracecraft has enough users, offer a marketplace for community-built integrations, evaluation templates, and dashboard plugins (take 20% commission).

3. **Data insights**: Aggregate anonymized, opt-in benchmark data across users to produce "State of AI Agents" reports and industry benchmarks. Monetize via sponsorships and enterprise subscriptions.

### Phase 5 Deliverables

| Deliverable | Est. Effort | Priority |
|-------------|-------------|----------|
| Multi-tenant cloud infrastructure | 3 weeks | P0 |
| Billing system (Stripe integration) | 1 week | P0 |
| Usage metering and limits | 1 week | P0 |
| SSO/SAML integration | 1 week | P0 |
| Audit logging | 3 days | P0 |
| RBAC system | 1 week | P1 |
| SOC 2 preparation | Ongoing | P1 |
| Marketing site (tracecraft.dev) | 1 week | P0 |
| Onboarding flow for cloud users | 3 days | P0 |
| Status page and monitoring | 2 days | P0 |

**Success Metrics:**
- $5,000 MRR by month 8
- 100+ cloud signups per month by month 7
- Free-to-paid conversion rate >3%
- Net promoter score >50
- <1% monthly churn on paid plans
- First enterprise contract ($2,000+/mo) by month 10

**Dependencies:**
- Strong open-source adoption (500+ GitHub stars) before cloud launch
- At least 3 framework integrations stable and documented
- Dashboard production-ready and performant

**Risk Factors:**
- Langfuse adds artifact storage (mitigate: move fast; our SeaweedFS integration is already built)
- Cloud infrastructure costs exceed revenue initially (mitigate: start with minimal infra, scale on demand; target <40% gross margin in month 5, >70% by month 12)
- Enterprise sales cycle is long (mitigate: product-led growth; let free tier do the selling; enterprise comes from bottom-up adoption)
- Open-source contributors fork the enterprise features (mitigate: enterprise features depend on managed infrastructure, not just code)

---

## Appendix A: Technology Stack Summary

| Component | Technology | Rationale |
|-----------|-----------|-----------|
| SDK | Python 3.10+ | Primary audience is Python AI developers |
| Server | FastAPI + Uvicorn | Already used in gnosis-track; async, fast |
| Database | PostgreSQL 16 | Robust, JSON support, row-level security for multi-tenancy |
| Migrations | Alembic | Standard for SQLAlchemy |
| Object Storage | SeaweedFS | Already integrated in gnosis-track; S3-compatible |
| Auth | JWT (existing) + API keys | JWT for dashboard; API keys for SDK |
| Dashboard | Next.js 15 + React 19 | Industry standard for OSS dev tools |
| UI Components | shadcn/ui + Tailwind CSS | Beautiful defaults, easy to customize |
| Charts | Recharts | Simple, React-native, sufficient for our needs |
| Tracing Protocol | OpenTelemetry (OTLP) | Industry standard; future-proof |
| CI/CD | GitHub Actions | Free for OSS; well-understood |
| Docs | Mintlify or Starlight | Modern docs-as-code with great DX |
| Package | PyPI | Standard Python distribution |
| Container | Docker + docker-compose | Standard self-hosting |

## Appendix B: Competitive Positioning Matrix

```
                    Agent-Native
                         |
                    tracecraft
                         |
            AgentOps ----+---- Langfuse
                         |
           Braintrust    |
                         |
    General-Purpose -----+------------ Agent-Specific
                         |
              W&B        |
                         |
            MLflow ------+---- LangSmith
                         |
                    Framework-Coupled
```

**Our quadrant:** Agent-specific + framework-agnostic. This is the underserved quadrant. Langfuse is close but leans general-purpose. LangSmith is agent-aware but framework-coupled. AgentOps is agent-specific but lacks storage depth.

## Appendix C: Key Metrics Dashboard (Internal)

Track these weekly from Phase 1 onward:

| Metric | Target (Week 18) | Target (Month 12) |
|--------|-------------------|---------------------|
| GitHub Stars | 200 | 2,000 |
| PyPI Weekly Downloads | 500 | 10,000 |
| Discord Members | 50 | 500 |
| Cloud Signups (total) | N/A | 5,000 |
| MRR | $0 | $22,880 |
| Contributors (external) | 5 | 30 |
| Framework Integrations | 5 | 8+ |
| Docs Pages | 20 | 60 |
| Blog Posts | 4 | 20 |

---

*This blueprint is a living document. Review and update at the end of each phase.*

## Sources

- [Top 5 AI Agent Observability Platforms 2026 Guide](https://o-mega.ai/articles/top-5-ai-agent-observability-platforms-the-ultimate-2026-guide)
- [Best AI Observability Tools for Autonomous Agents in 2026 -- Arize](https://arize.com/blog/best-ai-observability-tools-for-autonomous-agents-in-2026/)
- [AI Observability Tools: A Buyer's Guide (2026) -- Braintrust](https://www.braintrust.dev/articles/best-ai-observability-tools-2026)
- [7 Best LLM Tracing Tools for Multi-Agent AI Systems (2026) -- Braintrust](https://www.braintrust.dev/articles/best-llm-tracing-tools-2026)
- [12 Best AI Agent Frameworks in 2026 -- Data Science Collective](https://medium.com/data-science-collective/the-best-ai-agent-frameworks-for-2026-tier-list-b3a4362fac0d)
- [AI Agent Frameworks: CrewAI vs AutoGen vs LangGraph Compared (2026)](https://designrevision.com/blog/ai-agent-frameworks)
- [The 2026 AI Agent Framework Decision Guide -- DEV Community](https://dev.to/linou518/the-2026-ai-agent-framework-decision-guide-langgraph-vs-crewai-vs-pydantic-ai-b2h)
- [OpenTelemetry Semantic Conventions for Generative AI](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [OTel Semantic Conventions for Agentic Systems -- GitHub Issue](https://github.com/open-telemetry/semantic-conventions/issues/2664)
- [AI Agent Observability -- Evolving Standards (OpenTelemetry Blog)](https://opentelemetry.io/blog/2025/ai-agent-observability/)
- [Langfuse Pricing](https://langfuse.com/pricing)
- [LangSmith Pricing 2026](https://checkthat.ai/brands/langsmith/pricing)
- [Weights & Biases Pricing](https://wandb.ai/site/pricing/)
- [Observability for Claude Agent SDK with Langfuse](https://langfuse.com/integrations/frameworks/claude-agent-sdk)
- [Trace Claude Agent SDK Applications -- LangSmith](https://docs.langchain.com/langsmith/trace-claude-agent-sdk)
- [10 Proven Ways to Boost Your GitHub Stars in 2026](https://scrapegraphai.com/blog/gh-stars)
- [What to Expect for Open Source in 2026 -- GitHub Blog](https://github.blog/open-source/maintainers/what-to-expect-for-open-source-in-2026/)
- [15 AI Agent Observability Tools in 2026 -- AIM](https://aimultiple.com/agentic-monitoring)
- [Getting Started with Langfuse (2026 Guide)](https://www.analyticsvidhya.com/blog/2025/11/langfuse-guide/)
