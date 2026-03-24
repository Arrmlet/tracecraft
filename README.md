# tracecraft

Coordination layer for multi-agent AI systems.

```
  Terminal 1 (designer)              Terminal 2 (developer)
  ┌──────────────────────┐           ┌──────────────────────┐
  │ tracecraft claim      │           │ tracecraft wait-for   │
  │   design              │           │   design              │
  │                       │           │   ...waiting...       │
  │ tracecraft complete   │  ──────>  │                       │
  │   design --note "done"│           │ ✓ design complete     │
  │                       │           │                       │
  │                       │  <──────  │ tracecraft send       │
  │                       │           │   designer "starting" │
  └──────────────────────┘           └──────────────────────┘
              \                  /
               \                /
            ┌──────────────────────┐
            │  Any S3 bucket       │
            │  (MinIO, AWS, R2,    │
            │   HuggingFace)       │
            └──────────────────────┘
```

## Quick start

```bash
pip install tracecraft-ai
```

Start MinIO locally (or use AWS S3, Cloudflare R2, HuggingFace Buckets):
```bash
docker run -d -p 9000:9000 -e MINIO_ROOT_USER=admin -e MINIO_ROOT_PASSWORD=admin123456 minio/minio server /data
```

Initialize two agents:
```bash
# Terminal 1
tracecraft init --project myproject --agent designer \
  --endpoint http://localhost:9000 --bucket tracecraft \
  --access-key admin --secret-key admin123456

# Terminal 2
tracecraft init --project myproject --agent developer \
  --endpoint http://localhost:9000 --bucket tracecraft \
  --access-key admin --secret-key admin123456
```

Now they can coordinate:
```bash
# Designer claims a task and shares state
$ tracecraft claim design
Claimed step design as designer

$ tracecraft memory set design.status "complete"
Set design.status = complete

$ tracecraft send developer "Design is ready"
Sent to developer: Design is ready

# Developer checks messages and picks it up
$ tracecraft inbox
[2026-03-24T14:00:00Z] (direct) designer: Design is ready

$ tracecraft memory get design.status
complete

$ tracecraft claim implementation
Claimed step implementation as developer
```

Everything is stored as JSON files in S3. No servers. No databases.

---

## What agents get

- **Shared memory** — `tracecraft memory set/get/list` — persistent key-value state any agent can read/write
- **Messaging** — `tracecraft send/inbox` — direct messages or broadcast to all agents
- **Task claiming** — `tracecraft claim/complete` — claim steps so agents don't collide
- **Barriers** — `tracecraft wait-for step1 step2` — block until dependencies complete
- **Handoffs** — `tracecraft complete step --note "context for next agent"`
- **Artifacts** — `tracecraft artifact upload/download/list` — share files between agents
- **Agent registry** — `tracecraft agents` — see who's online and what they're working on

Works with any process that can call a CLI — Claude Code, OpenClaw, Hermes Agent, Codex, bash scripts, Python, anything.

---

## Storage backends

No vendor lock-in. Bring your own S3:

```bash
# Local development (recommended to start)
tracecraft init --endpoint http://localhost:9000 ...    # MinIO
tracecraft init --endpoint http://localhost:8333 ...    # SeaweedFS

# Production
tracecraft init --endpoint https://s3.amazonaws.com ... # AWS S3
tracecraft init --endpoint https://xxx.r2.cloudflarestorage.com ... # Cloudflare R2

# HuggingFace Buckets (browsable on the Hub)
pip install tracecraft-ai[huggingface]
tracecraft init --backend hf --bucket username/my-bucket ...
```

---

## How it works

All coordination state is JSON files in S3:

```
s3://bucket/project/
  agents/designer.json          ← who's alive, what they're doing
  memory/design/status.json     ← shared key-value state
  messages/developer/1234.json  ← agent inboxes
  steps/design/claim.json       ← who claimed what
  steps/design/status.json      ← pending → in_progress → complete
  steps/design/handoff.json     ← notes for the next agent
  artifacts/design/mockup.html  ← shared files
```

Any agent that can call `tracecraft` can participate. Any S3 browser (MinIO console, AWS console, HuggingFace Hub) lets you watch agents coordinate in real-time.

---

## CLI reference

```bash
tracecraft init                           # Configure S3 + project + agent
tracecraft agents                         # Who's online?

tracecraft memory set <key> <value>       # Write (dots become path separators)
tracecraft memory get <key>               # Read
tracecraft memory list [prefix]           # List keys

tracecraft send <agent-id> <message>      # Direct message
tracecraft send _broadcast <message>      # Broadcast to all
tracecraft inbox                          # Read messages
tracecraft inbox --delete                 # Read and clear

tracecraft claim <step-id>                # Claim a step
tracecraft complete <step-id> [--note X]  # Mark done + handoff
tracecraft step-status <step-id>          # Check status
tracecraft wait-for <step-ids...>         # Block until complete (default 300s timeout)

tracecraft artifact upload <path> [--step id]   # Share a file
tracecraft artifact download <name> [--step id] # Get a file
tracecraft artifact list [--step id]             # List files
```

For multiple agents in the same directory, set identity via env var:
```bash
TRACECRAFT_AGENT=designer tracecraft inbox
TRACECRAFT_AGENT=developer tracecraft inbox
```

---

## Live demo

Two Claude Code agents coordinated through HuggingFace Buckets — browsable on the Hub:

https://huggingface.co/buckets/arrmlet/tracecraft-test

---

## License

MIT
