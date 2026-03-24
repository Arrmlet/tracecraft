# tracecraft

**Coordination layer for multi-agent AI systems.** Shared memory, messaging, and task coordination.

```bash
pip install tracecraft-ai
```

---

When you run multiple AI agents in parallel, they need to coordinate — share results, claim tasks, wait for each other, pass context forward. Tracecraft is a CLI that does this through any S3-compatible storage.

```bash
# Agent A finishes a step
tracecraft memory set s1a.status "complete"
tracecraft complete S1.A --note "SDK core built. Watch out for race in queue.py"

# Agent B picks it up
tracecraft wait-for S1.A
tracecraft memory get s1a.status
tracecraft claim S1.B
```

Works with any agent that can run a shell command — Claude Code, OpenClaw, Hermes Agent, Codex, custom scripts, anything.

---

## What it does

| Capability | Command | What happens |
|-----------|---------|-------------|
| **Shared memory** | `tracecraft memory set key value` | Agents read/write persistent key-value state |
| **Messaging** | `tracecraft send agent-b "done"` | Direct or broadcast messages between agents |
| **Task claiming** | `tracecraft claim S1.A` | Claim a step so agents don't collide |
| **Barriers** | `tracecraft wait-for S1.A S1.B` | Block until dependencies complete |
| **Handoffs** | `tracecraft complete S1.A --note "..."` | Structured context for the next agent |
| **Artifacts** | `tracecraft artifact upload file.pdf --step s1a` | Share files between agents |
| **Agent registry** | `tracecraft agents` | See who's online and what they're working on |

---

## Quick start

### 1. Install

```bash
pip install tracecraft-ai
```

### 2. Point to any S3

```bash
# Local MinIO
tracecraft init --project myproject --agent agent-1 \
  --endpoint http://localhost:9000 --bucket tracecraft \
  --access-key admin --secret-key admin123456

# AWS S3
tracecraft init --project myproject --agent agent-1 \
  --endpoint https://s3.amazonaws.com --bucket my-tracecraft

# Cloudflare R2, SeaweedFS, any S3-compatible storage — same interface

# HuggingFace Buckets
tracecraft init --backend hf --bucket username/my-bucket \
  --project myproject --agent agent-1
```

### 3. Coordinate

```bash
tracecraft memory set research.findings '{"papers": 47}'
tracecraft send agent-writer "Research complete"
tracecraft claim research
tracecraft complete research --note "Found 12 relevant papers"
tracecraft artifact upload results.json --step research
```

For multiple agents in the same directory:
```bash
TRACECRAFT_AGENT=designer tracecraft inbox
TRACECRAFT_AGENT=developer tracecraft inbox
```

---

## Storage backends

Tracecraft stores everything as JSON files in S3. No servers, no databases. Bring your own storage:

| Backend | Setup |
|---------|-------|
| **MinIO** | `docker run -p 9000:9000 minio/minio server /data` |
| **SeaweedFS** | `docker run -p 8333:8333 chrislusf/seaweedfs server -s3` |
| **AWS S3** | Create a bucket, pass credentials |
| **Cloudflare R2** | Free tier, S3-compatible |
| **HuggingFace Buckets** | `pip install tracecraft-ai[huggingface]` |

---

## CLI reference

```bash
# Setup
tracecraft init                           # Configure S3 + project + agent
tracecraft agents                         # Who's online?

# Shared memory
tracecraft memory set <key> <value>       # Write (dots become path separators)
tracecraft memory get <key>               # Read
tracecraft memory list [prefix]           # List keys

# Messaging
tracecraft send <agent-id> <message>      # Direct message
tracecraft send _broadcast <message>      # Broadcast to all
tracecraft inbox                          # Read messages
tracecraft inbox --delete                 # Read and clear

# Task coordination
tracecraft claim <step-id>                # Claim a step
tracecraft complete <step-id> [--note X]  # Mark done + handoff
tracecraft step-status <step-id>          # Check status
tracecraft wait-for <step-ids...>         # Block until complete

# Artifacts
tracecraft artifact upload <path> [--step id]   # Share a file
tracecraft artifact download <name> [--step id] # Get a file
tracecraft artifact list [--step id]             # List files
```

---

## How it works

```
Any agent (Claude Code, OpenClaw, Hermes, scripts)
    |
    |  tracecraft CLI
    |
    v
Any S3-compatible storage
    |
    +--- s3://bucket/project/memory/    → shared key-value state
    +--- s3://bucket/project/messages/  → agent inboxes
    +--- s3://bucket/project/steps/     → claims, status, handoffs
    +--- s3://bucket/project/agents/    → who's alive
    +--- s3://bucket/project/artifacts/ → shared files
```

All coordination state is JSON files in S3. Any agent that can call `tracecraft` can participate.

---

## Tested with

- Claude Code (multiple instances in worktrees)
- HuggingFace Buckets ([live demo](https://huggingface.co/buckets/arrmlet/tracecraft-test))
- MinIO (local dev)

---

## License

MIT
