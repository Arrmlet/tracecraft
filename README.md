# tracecraft

[![PyPI](https://img.shields.io/pypi/v/tracecraft-ai)](https://pypi.org/project/tracecraft-ai/)
[![Python](https://img.shields.io/pypi/pyversions/tracecraft-ai)](https://pypi.org/project/tracecraft-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/Arrmlet/tracecraft/actions/workflows/ci.yml/badge.svg)](https://github.com/Arrmlet/tracecraft/actions/workflows/ci.yml)

**Tracecraft is a CLI coordination layer for multi-agent AI systems** — shared **memory**, a **mailbox**, atomic task **claims**, **handoffs**, and **artifacts**, plus mirrored **session transcripts**, all stored as plain JSON in any **S3** or **HuggingFace** bucket. No server. No database. No SDK lock-in.

<p align="center">
  <img width="100%" alt="Two agents race for the same task; the second is atomically rejected — no server" src="docs/assets/tracecraft-claim-race.gif">
</p>

> Two agents, one bucket — they can't grab the same work, enforced by an S3 conditional write. No server, no lock service. All state is plain JSON you own; open it in the MinIO console or [HuggingFace Hub](https://huggingface.co/buckets/arrmlet/tracecraft-test) and watch it live.

---

## Quick start

```bash
pip install tracecraft-ai
```

The only infra is a bucket. For local dev, run MinIO (in production, point at AWS / R2 / HF instead):

```bash
docker run -d -p 9000:9000 \
  -e MINIO_ROOT_USER=admin -e MINIO_ROOT_PASSWORD=admin123456 \
  minio/minio server /data
```

(From a checkout, `docker compose -f docker-compose.dev.yml up -d` does the same and adds the MinIO console on `:9001`.)

Register two agents against the same project. Credentials come from the standard AWS env vars, so they never land in your shell history:

```bash
export AWS_ACCESS_KEY_ID=admin
export AWS_SECRET_ACCESS_KEY=admin123456

# Terminal 1
tracecraft init --project demo --agent designer \
  --endpoint http://localhost:9000 --bucket tracecraft

# Terminal 2 — same flags, --agent developer
tracecraft init --project demo --agent developer \
  --endpoint http://localhost:9000 --bucket tracecraft
```

`init` writes the config to `.tracecraft.json` with mode `600` and auto-adds it to `.gitignore` when you're in a git repo.

Now the core move — **two agents cannot grab the same work**, with no lock service and no server to run:

```console
# Terminal 1 — designer claims the task
$ tracecraft claim design
Claimed step design as designer

# Terminal 2 — developer tries the SAME task, atomically rejected (S3 If-None-Match)
$ tracecraft claim design
Error: Step design already claimed by designer

# designer finishes and leaves a handoff note for whoever picks up next
$ tracecraft complete design --note "API in api.py, see memory key design.contract"
Completed step design

# developer was blocked on it — now it unblocks
$ tracecraft wait-for design
All steps complete: design
```

Every call is stateless. Everything you just did is JSON files in the bucket — no server stayed running, nothing to tear down.

---

## Agents talk to each other

Beyond claiming work, agents coordinate by messaging through the bucket — direct messages and broadcasts, each one a JSON file in a per-agent mailbox.

<p align="center">
  <img width="100%" alt="One agent sends a handoff, another reads its inbox and replies, then a broadcast to the team" src="docs/assets/tracecraft-messaging.gif">
</p>

```bash
tracecraft send developer "contract is in memory key design.contract"
tracecraft inbox                       # read your direct + broadcast messages
tracecraft send _broadcast "v1 cut at 3pm, wrap your tasks"
```

---

## Why tracecraft

- **Atomic task claims** — two agents never grab the same work, enforced by S3 `If-None-Match` conditional puts, with no central coordinator.
- **Coordinate across hosts** — the bucket *is* the coordinator, so agents on different machines or clouds work together by default — not just processes sharing one laptop.
- **No server, no database** — every CLI call is stateless; all state is JSON in a bucket you already own.
- **Any backend, zero lock-in** — AWS, Cloudflare R2, MinIO, Backblaze B2, Wasabi, SeaweedFS, and HuggingFace Buckets all work today.
- **Harness-agnostic** — Claude Code, Codex, OpenClaw, Hermes, bash, Python, or anything that can run a shell command.
- **Coordination + reasoning together** — the events *and* each agent's full session transcript live in one bucket, not two systems.

> Frameworks like CrewAI and LangGraph own the agent loop; memory layers like Mem0 store one agent's recall; in-process coordination tools assume every agent shares one machine. Tracecraft owns neither the loop nor the model — just the shared bucket the agents coordinate *through* — so it works across hosts, across clouds, and with any harness, via a plain CLI.

---

## Why not LangGraph / Redis / message queues?

- **Frameworks (LangGraph, CrewAI, AutoGen)** orchestrate agents *inside one process*. Tracecraft coordinates *any* processes across machines — different harnesses, different clouds, different teams — through storage they already have.
- **Redis / Postgres / a queue** means operating a server: provisioning, auth, uptime, backups. A bucket is zero infra, and every state change is a browsable JSON file — you get an audit trail for free just by opening the bucket.
- **A2A / MCP** are live wire protocols between *running* agents. Tracecraft is durable state for agents that aren't running at the same time — one agent finishes Tuesday, the next picks up the handoff Wednesday.

## Status & limitations

Tracecraft is **pre-alpha**. Honest sharp edges, as of now:

- **No TTL on claims** — a crashed claim-holder keeps the lock until someone runs `complete --force`.
- **Heartbeat isn't refreshed** — `agents` shows who registered, not who's alive right now.
- **HF claims are best-effort** — HuggingFace Buckets have no conditional write, so atomic claims need an S3-compatible backend.

Open issues and roadmap → [github.com/Arrmlet/tracecraft/issues](https://github.com/Arrmlet/tracecraft/issues)

---

## Session mirroring

Most coordination tools store the *events* — who claimed what, who messaged whom. Tracecraft stores those **and** each agent's full reasoning, by mirroring coding-agent session transcripts into the same bucket. When a run goes sideways, one `tracecraft session show` gives you the handoffs **and** the chain of thought behind them — same place, same JSON, no second system to wire up.

```bash
tracecraft session mirror --harness claude-code   # upload this session's new bytes
tracecraft session list                           # browse mirrored sessions
tracecraft session show <id> --tail 50            # replay: meta + last N transcript lines
tracecraft session stop <id>                      # clear local cursor, mark session ended
```

- **Four harnesses** — `claude-code`, `codex`, `openclaw`, `hermes`. Anything else can mirror by writing JSONL to the same layout.
- **Incremental cursor uploads** — `mirror` keeps a per-session byte offset and uploads only what's new as numbered parts, so re-running it from a cron or hook is safe and cheap; a run with nothing new is a no-op. The part sequence is derived from the bucket, so it even survives losing the local state file.
- **Redaction on by default** — AWS / Anthropic / OpenAI / HF / GitHub / Slack token shapes are scrubbed before upload, with per-pattern match counts recorded in the session's `meta.json` (pass `--no-redact` to opt out). Source transcripts are never modified.
- **Replay** — `session show <id> --tail N` concatenates the uploaded parts and prints the last N transcript lines next to the session metadata.

Harness matrix, storage formats, and redaction details → **[docs/session-mirror.md](docs/session-mirror.md)**

---

## How it works

Every agent action is a JSON file under `<bucket>/<project>/`:

```
s3://bucket/demo/
  agents/designer.json                       ← who's alive, what they're doing
  memory/design/contract.json                ← shared key-value state
  messages/developer/1738f3_designer.json    ← per-agent mailbox
  steps/design/claim.json                    ← who claimed what (atomic)
  steps/design/status.json                   ← pending → in_progress → complete
  steps/design/handoff.json                  ← note for the next agent
  artifacts/design/mockup.html               ← shared files
  sessions/claude-code/<id>/part-00000-….jsonl  ← mirrored agent transcript
  sessions/claude-code/<id>/meta.json            ← cumulative session metadata
```

Any process that can call `tracecraft` participates. Any S3 browser (MinIO console, AWS console, HuggingFace Hub) lets you watch agents coordinate in real time. Atomicity details and the HuggingFace fallback are in **[docs/s3-architecture.md](docs/s3-architecture.md)**.

---

## Backends

Bring your own bucket — no vendor lock-in:

| Backend | `init` flag | Notes |
|---|---|---|
| MinIO | `--endpoint http://localhost:9000` | recommended for local dev |
| SeaweedFS | `--endpoint http://localhost:8333` | self-hosted |
| AWS S3 | `--endpoint https://s3.amazonaws.com` | |
| Cloudflare R2 | `--endpoint https://<acct>.r2.cloudflarestorage.com` | zero egress fees |
| Backblaze B2 / Wasabi | S3-compatible endpoint | |
| HuggingFace Buckets | `--backend hf --bucket user/name` | browsable on the Hub; `pip install tracecraft-ai[huggingface]` |

**HuggingFace privacy:** `init` creates the bucket **private by default** (pass `--public` to opt out) and prints the bucket's *actual* visibility, read back from the Hub — e.g. `Backend: HuggingFace Buckets  Bucket: user/x (private)`. If the bucket already exists as public and you didn't ask for that, init warns loudly: coordination data and mirrored transcripts would be publicly visible. Visibility can't be flipped after creation (`huggingface_hub` has no `update_bucket`) — the only way to change it is delete + recreate.

---

## Use cases

- **Multi-agent coding** — run several Claude Code / Codex agents in parallel; they claim modules, share artifacts, wait at barriers, and hand off context instead of stepping on each other.
- **Autonomous research** — agents claim experiments, share results via memory, and avoid duplicating work across a fleet.
- **Pipelines** — lint → test → build → deploy as claimed steps; each stage waits for its dependencies.

---

<details>
<summary><strong>Full CLI reference</strong></summary>

```bash
tracecraft init                           # Configure backend + project + agent
tracecraft agents                         # Who's online?

tracecraft memory set <key> <value>       # Write (dots become path separators)
tracecraft memory get <key>               # Read
tracecraft memory list [prefix]           # List keys

tracecraft send <agent-id> <message>      # Direct message
tracecraft send _broadcast <message>      # Broadcast to all
tracecraft inbox                          # Read messages
tracecraft inbox --delete                 # Read and clear

tracecraft claim <step-id>                # Claim a step (atomic)
tracecraft complete <step-id> [--note X] [--to AGENT] [--next-action X]
                                          [--blocked|--needs-review]
                                          [--changed-files-from-git]  # Structured handoff record
tracecraft step-status <step-id>          # Check status
tracecraft wait-for <step-ids...>         # Block until complete (default 300s timeout)

tracecraft artifact upload <path> [--step id]    # Share a file
tracecraft artifact download <name> [--step id]  # Get a file
tracecraft artifact list [--step id]             # List files

tracecraft session mirror --harness <name>       # Mirror a session into the bucket
tracecraft session list                          # Browse mirrored sessions
tracecraft session show <id> [--tail N]          # Inspect meta + transcript tail
tracecraft session stop <id>                     # Clear local state, mark ended
```

Run multiple agents from one directory by overriding identity per call:

```bash
TRACECRAFT_AGENT=designer  tracecraft inbox
TRACECRAFT_AGENT=developer tracecraft inbox
```

</details>

---

## Python API

The CLI is the stable interface; for code that wants direct bucket access, the store factory is the escape hatch:

```python
from tracecraft.store import get_store

store, cfg = get_store()  # reads .tracecraft.json like the CLI does
store.put_json("memory/build/status.json", {"value": "passing", "set_by": cfg["agent_id"]})
```

---

## More

- [docs/session-mirror.md](docs/session-mirror.md) — session mirroring: harnesses, formats, redaction
- [docs/s3-architecture.md](docs/s3-architecture.md) — atomicity, key layout, HuggingFace fallback
- [plans/](plans/) — roadmap, research, and known gaps

---

## License

MIT
