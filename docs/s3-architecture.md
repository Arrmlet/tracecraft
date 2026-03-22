# Tracecraft S3 Architecture

Everything is S3. No databases. Agents coordinate through S3 objects.

Users bring their own S3: SeaweedFS (local), AWS S3, Cloudflare R2, MinIO — all the same boto3 interface.

## Bucket Structure

```
s3://bucket/
  {project}/                          # top-level namespace per project

    agents/                           # who's alive
      {agent-id}.json                 # presence + heartbeat + what they're doing

    memory/                           # shared key-value state
      {key/path}.json                 # dots become slashes: phase1.s1a.status → memory/phase1/s1a/status.json

    messages/                         # agent-to-agent communication
      {recipient-agent-id}/           # inbox per agent
        {timestamp}_{sender-id}.json  # each message is a file
      _broadcast/                     # broadcast messages everyone reads
        {timestamp}_{sender-id}.json

    steps/                            # coordination / task management
      {step-id}/
        claim.json                    # who claimed it, when
        status.json                   # pending/in_progress/complete/failed
        handoff.json                  # notes from completing agent

    artifacts/                        # files agents produce and share
      {step-id}/                      # organized by what step produced them
        {filename}                    # any file: code, data, reports
      shared/                         # cross-step shared artifacts
        {filename}

    runs/                             # experiment tracking
      {run-id}/
        meta.json                     # run config, params, status
        metrics.jsonl                 # append-only metrics log
        steps/                        # step-by-step trace
          {timestamp}_{step-name}.json
        artifacts/
          {filename}
```

## Why This Structure

### Project-level namespace
Multiple projects on the same bucket don't collide. `tracecraft-build/` and `research-exp-1/` side by side.

### Agents as files
An agent writes `agents/claude-code-1.json`:
```json
{
  "id": "claude-code-1",
  "status": "active",
  "step": "S1.A",
  "worktree": "/path/to/worktree",
  "started_at": "2026-03-22T15:00:00Z",
  "heartbeat": "2026-03-22T15:05:00Z",
  "summary": "Building SDK core with shared memory client"
}
```
Other agents LIST `agents/` to see who's alive. Stale heartbeats (>5min old) = dead agent.

### Memory as files with dot-path keys
`tracecraft memory set phase1.s1a.status complete` writes to `memory/phase1/s1a/status.json`. Dots become directory separators — S3 prefixes are natural hierarchies. LIST `memory/phase1/` to see all phase 1 state.

### Messages as timestamped inbox files
Each agent has an inbox folder. `tracecraft send agent-b "step done"` writes `messages/agent-b/1711234567_agent-a.json`. Agent B does LIST on their inbox, reads new files, deletes after processing. `_broadcast/` is for everyone.

### Steps as folders
Each blueprint step gets a folder. `claim.json` is atomic — first agent to write it owns the step. `status.json` tracks progress. `handoff.json` is what the completing agent leaves for the next one.

### Artifacts per step
When Agent A finishes S1.A and produces `schema.sql`, it goes to `artifacts/s1a/schema.sql`. Agent B working on S1.B knows exactly where to find it.

## Agent-to-Agent Communication Flow

```bash
# Agent A starts working
tracecraft init --project tracecraft-build --agent claude-code-1
tracecraft claim S1.A
# → PUT {project}/steps/s1a/claim.json = {"agent": "claude-code-1", "at": "..."}

# Agent A checks if dependency is done
tracecraft step-status S0.1
# → GET {project}/steps/s0.1/status.json → {"status": "complete"}

# Agent A reads the handoff from whoever did S0.1
tracecraft handoff S0.1
# → GET {project}/steps/s0.1/handoff.json → {"summary": "...", "warnings": [...]}

# Agent A works... and shares state as it goes
tracecraft memory set s1a.progress "50%"
# → PUT {project}/memory/s1a/progress.json

# Agent A finishes and shares results
tracecraft artifact upload schema.sql --step s1a
# → PUT {project}/artifacts/s1a/schema.sql

tracecraft complete S1.A --note "SDK core done. Watch race condition in queue.py"
# → PUT {project}/steps/s1a/status.json = {"status": "complete"}
# → PUT {project}/steps/s1a/handoff.json = {"note": "...", "agent": "claude-code-1"}

tracecraft broadcast "Phase 1 S1.A complete"
# → PUT {project}/messages/_broadcast/1711234567_claude-code-1.json

# Agent B (in another terminal/worktree) sees it
tracecraft inbox
# → LIST {project}/messages/claude-code-2/ + LIST {project}/messages/_broadcast/
# → "Agent claude-code-1: Phase 1 S1.A complete"

tracecraft wait-for S1.A
# → polls GET {project}/steps/s1a/status.json until status == "complete"

tracecraft artifact download schema.sql --step s1a
# → GET {project}/artifacts/s1a/schema.sql
```

## Configuration

```bash
# Local SeaweedFS
tracecraft init \
  --project tracecraft-build \
  --agent claude-code-1 \
  --endpoint http://localhost:8333 \
  --bucket tracecraft \
  --access-key admin \
  --secret-key secret

# AWS S3
tracecraft init \
  --project tracecraft-build \
  --agent claude-code-1 \
  --endpoint https://s3.amazonaws.com \
  --bucket my-tracecraft-bucket

# Cloudflare R2
tracecraft init \
  --project tracecraft-build \
  --agent claude-code-1 \
  --endpoint https://xxx.r2.cloudflarestorage.com \
  --bucket tracecraft

# MinIO
tracecraft init \
  --project tracecraft-build \
  --agent claude-code-1 \
  --endpoint http://minio:9000 \
  --bucket tracecraft
```

Config stored at `~/.tracecraft/config.json`.

## File Formats

### agents/{id}.json
```json
{
  "id": "claude-code-1",
  "status": "active",
  "step": "S1.A",
  "worktree": "/Users/me/tracecraft-s1a",
  "started_at": "2026-03-22T15:00:00Z",
  "heartbeat": "2026-03-22T15:05:00Z",
  "summary": "Building SDK core"
}
```

### memory/{path}.json
```json
{
  "value": "complete",
  "set_by": "claude-code-1",
  "set_at": "2026-03-22T15:10:00Z"
}
```

### messages/{recipient}/{ts}_{sender}.json
```json
{
  "from": "claude-code-1",
  "to": "claude-code-2",
  "message": "S1.A complete, schema at artifacts/s1a/schema.sql",
  "sent_at": "2026-03-22T15:10:00Z"
}
```

### steps/{id}/claim.json
```json
{
  "agent": "claude-code-1",
  "claimed_at": "2026-03-22T15:00:00Z"
}
```

### steps/{id}/status.json
```json
{
  "status": "complete",
  "agent": "claude-code-1",
  "started_at": "2026-03-22T15:00:00Z",
  "completed_at": "2026-03-22T16:30:00Z"
}
```

### steps/{id}/handoff.json
```json
{
  "from_agent": "claude-code-1",
  "from_step": "S1.A",
  "summary": "SDK core built with shared memory client stubs",
  "findings": ["CAS-based memory works well", "Background batching at 100ms"],
  "warnings": ["Race condition in transport/queue.py under investigation"],
  "artifacts": ["artifacts/s1a/schema.sql", "artifacts/s1a/sdk-core.tar.gz"],
  "created_at": "2026-03-22T16:30:00Z"
}
```

### runs/{id}/meta.json
```json
{
  "id": "run-abc123",
  "name": "prompt-comparison-v2",
  "experiment": "exp-1",
  "status": "running",
  "params": {"model": "claude-sonnet-4-20250514", "temperature": 0.7},
  "started_at": "2026-03-22T15:00:00Z"
}
```
