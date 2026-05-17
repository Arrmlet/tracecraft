# Tracecraft

Coordination layer for multi-agent AI systems. Shared memory, mailbox, atomic task claims,
handoffs, and artifacts — all stored as JSON files in any S3-compatible bucket
(AWS, R2, MinIO, B2, Wasabi, HuggingFace).

## Quick Reference

- CLI: `tracecraft`
- Language: Python 3.10+
- Backends: S3 (boto3) + HuggingFace Buckets (HfFileSystem)
- Install: `pip install tracecraft-ai`
- License: MIT

## Architecture (what actually ships)

```
sdk/tracecraft/          Python SDK + CLI (~530 LoC)
  cli/                   click-based CLI commands
    init_cmd.py          init: configure + register agent
    agents.py            agents: list active agents
    memory.py            memory set/get/list
    messages.py          send/inbox
    steps.py             claim/complete/step-status/wait-for
    artifacts.py         artifact upload/download/list
  s3.py                  boto3 wrapper (project-scoped keys, atomic put via If-None-Match)
  hf.py                  HuggingFace Buckets backend (same interface)
  store.py               backend factory
  config.py              .tracecraft.json / ~/.tracecraft/config.json loader
```

No FastAPI server, no PostgreSQL, no Redis. Earlier scaffolding from the gnosis-track
pivot lives in `plans/server-archive/` for reference only — nothing in the SDK imports it.

## Bucket layout

```
<bucket>/<project>/
  agents/<agent_id>.json                ← agent registration + heartbeat
  memory/<dotted.key>.json              ← shared key-value state
  messages/<recipient>/<ts>_<from>.json ← per-agent mailbox
  messages/_broadcast/<ts>_<from>.json  ← broadcast
  steps/<step_id>/claim.json            ← atomic claim (If-None-Match=*)
  steps/<step_id>/status.json           ← pending / in_progress / complete
  steps/<step_id>/handoff.json          ← note + from_agent for next agent
  artifacts/<step_id|shared>/<file>     ← arbitrary files
```

## Key Design Decisions (actual)

- **CLI-first**: primary interface is the `tracecraft` shell command.
- **Backend-agnostic**: any S3-compatible bucket + HuggingFace Buckets.
- **Atomic claim via If-None-Match=`*`**: S3 conditional put rejects races without a
  server-side coordinator. HF backend falls back to check-then-write (documented).
- **Project-scoped keys**: every key is prefixed by `<project>/` so one bucket can host
  many isolated projects.
- **No server, no daemon**: each CLI call is stateless; state lives on the bucket.
- **No vendor lock-in**: AWS, R2, MinIO, B2, Wasabi, HuggingFace all work today.

## Known gaps (May 2026)

- No TTL on claims (a crashed claim-holder keeps the lock forever) — Tier 1 work.
- Heartbeat is written at `init` only, never refreshed — Tier 1 work.
- Messages keyed by `<ts>_<sender>.json` can collide same-second — Tier 1 work.
- No tests in `sdk/tests/` — Tier 1 work.

## Building

```bash
pip install -e "sdk/[dev]"                              # SDK + CLI
docker compose -f docker-compose.dev.yml up -d          # local MinIO for testing
```

## Plans

See `plans/`:
- `RESEARCH_2026_05.md` — 2026 agentic-AI landscape, competitor scan, roadmap.
- `MARKET_REPORT_SESSIONS_2026_05.md` — novelty analysis on session storage.
- `CONSEQUENCES_2026_05.md` — what shipping the Tier 0/1 bundle implies.
- `WHAT_IS_A_HARNESS_EN.md` / `_UA.md` — what "harness" means in 2026 vocabulary.
- `server-archive/` — earlier FastAPI scaffolding; reference only, not shipped.
- `tracecraft-blueprint-v2.md` — original full-stack blueprint (aspirational).
