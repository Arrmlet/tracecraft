# Session mirror

`tracecraft session mirror` copies a coding agent's session transcript into your
bucket, alongside the coordination state (memory, messages, claims, artifacts)
that tracecraft already stores under the same `<project>/` prefix. One bucket
ends up holding the full record of a multi-agent run: every agent's reasoning
**and** every message between them.

Sessions are never modified at the source. The mirror is a read-only tail.

## Supported harnesses

| `--harness` | Source | Storage |
|---|---|---|
| `claude-code` | `~/.claude/projects/<encoded-cwd>/<id>.jsonl` | append-only JSONL |
| `codex` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | append-only JSONL |
| `openclaw` | `<state>/agents/<agentId>/sessions/<id>.jsonl` | append-only JSONL |
| `hermes` | `~/.hermes/state.db` (`messages` table) | SQLite (WAL) |

All four expose the same interface to the mirror loop via the `Harness`
protocol (`sdk/tracecraft/harness/base.py`). Adding a fifth harness is one
file plus a `REGISTRY` entry.

### Harness notes

- **OpenClaw** state dir resolves `OPENCLAW_STATE_DIR` → `OPENCLAW_HOME` →
  `~/.openclaw`. `--dev`/`--profile <name>` map to `~/.openclaw-dev` /
  `~/.openclaw-<name>` — point `OPENCLAW_STATE_DIR` at those if you use them.
  The mutable `sessions.json` index and `*.tmp` staging files are skipped.
  Session ids are unique only within an `agentId`, so the mirrored id is
  `<agentId>__<sessionId>`.
- **Hermes** is SQLite, not a file. The adapter opens the DB **read-only**
  (`mode=ro`, never `immutable`) so it is safe to run while Hermes is writing —
  WAL mode allows concurrent readers. It reads new rows with
  `WHERE id > :cursor ORDER BY id` (the same incremental pattern Hermes uses
  internally) and synthesizes one JSON line per message. Multimodal `content`
  stored with Hermes' `\x00json:` sentinel is decoded back to JSON.

## Commands

```bash
tracecraft session mirror --harness <name> [--session-id ID] [--cwd PATH]
                          [--no-redact] [--min-bytes N]
                          [--follow/-f] [--interval SECONDS] [--all]
tracecraft session list [--harness NAME] [--limit N] [--sort-by recent|size]
tracecraft session show <session-id> [--tail N]
tracecraft session stop <session-id>
tracecraft session compact <session-id> [--keep-tail N]
```

### mirror

Single-shot by default. Reads everything new since the last run, redacts,
uploads it as a new part, updates `meta.json`, and advances the cursor. Safe to
run repeatedly (e.g. from a cron or a `SessionEnd` hook).

```bash
# Auto-pick the most recent claude-code session for the current directory
tracecraft session mirror --harness claude-code

# Explicit session, codex
tracecraft session mirror --harness codex --session-id abc123

# Hermes (session id is the sessions.id TEXT value, e.g. 20260529_120000_abc123)
tracecraft session mirror --harness hermes --session-id 20260529_120000_abc123
```

If `--session-id` is omitted, the most recently active session is chosen
(for Hermes, the session owning the highest message id).

### mirror --follow

Near-real-time mirroring. `--follow` (or `-f`) resolves the session once, then
re-flushes every `--interval` seconds (default 5) until you press Ctrl-C — so a
crash loses at most one interval of trace instead of the whole run.

```bash
# Keep this session mirrored live, flushing every 5s
tracecraft session mirror --harness claude-code --follow

# Tighter cadence for a long, important run
tracecraft session mirror --harness claude-code -f --interval 2
```

`--follow` reuses the same incremental cursor and `--min-bytes` gate, so cycles
with no new bytes upload nothing (they print `nothing new` and cost no PUT). On
Ctrl-C it stops cleanly and stamps `ended_at` on the session's `meta.json`.

It batches one upload per interval rather than streaming per event on purpose:
on per-operation-priced backends (R2 Class A writes, S3 PUTs) a flush-per-event
loop would multiply write cost without making the trace meaningfully fresher.
For a fixed cadence outside the process (a cron every minute, say), the plain
one-shot `mirror` is still the right tool — `--follow` is for an interactive run
you want kept live while it's happening.

### mirror --all

Follow **every** session under `--cwd`, not just the active one — including
sessions that start *after* the loop begins. This is the "one terminal mirrors
the whole project" mode: open several agents in the same folder and they all get
mirrored, each into its own `sessions/<harness>/<id>/` folder in the bucket.

```bash
# one terminal, mirrors every claude-code session in this project as they appear
tracecraft session mirror --harness claude-code --all
```

`--all` implies `--follow` and ignores `--session-id` (it mirrors all of them).
Each session keeps an independent cursor, so flushing one never disturbs another;
new sessions are announced with `+ now following session=<id>` as they appear.
On Ctrl-C it marks every followed session ended.

Note: `--all` is scoped to one cwd and one harness. Sessions in other folders, or
from a different harness (e.g. Codex), need their own `--all` invocation — or use
the SessionStart hook, which auto-pins each session regardless of folder/harness.

### compact

Over a long `--follow` run a session accumulates many small part files (one per
flush). They're cheap to write and reassemble transparently on read, but you can
consolidate them:

```bash
tracecraft session compact <session-id>              # merge all parts into one
tracecraft session compact <session-id> --keep-tail 1 # leave the newest part (live --follow)
```

compact concatenates the parts in seq order, byte-for-byte, into a single new
part and deletes the originals — `session show` output is identical before and
after. It uploads the merged part and rewrites `meta.json` **before** deleting
anything, so an interrupted compact leaves a harmless duplicate, never a gap.
Use `--keep-tail N` to avoid racing a `--follow` loop that's still appending.

### list / show / stop

```bash
tracecraft session list                       # every mirrored session
tracecraft session show <id>                   # print meta.json
tracecraft session show <id> --tail 50         # + last 50 lines of the transcript
tracecraft session stop <id>                   # clear local state, mark ended_at
```

## Bucket layout

Additive — does not touch existing coordination keys.

```
<bucket>/<project>/
  agents/        memory/        messages/        steps/        artifacts/   ← coordination
  sessions/
    <harness>/
      <session-id>/
        part-00000-<uuid8>.jsonl   ← one per mirror flush, disjoint
        part-00001-<uuid8>.jsonl
        meta.json                  ← cumulative metadata + redaction counts
```

Parts are append-disjoint and reassemble byte-for-byte (file harnesses) or
row-for-row (Hermes). The `<uuid8>` suffix makes concurrent flushes from
different machines collision-safe; reassembly sorts by sequence number.

## The cursor model

The mirror tracks a per-session **cursor** in
`~/.tracecraft/mirror-state/<session-id>.json`. The cursor is opaque:

- file harnesses → a **byte offset**
- Hermes → the highest **`messages.id`** (an AUTOINCREMENT rowid)

`read_new(session, cursor)` returns `(new_bytes, new_cursor)` so advancement is
race-free — the loop advances to exactly what it consumed, never to a
separately-sampled size. Losing the state file is non-destructive: the next run
re-derives the next part sequence number from a bucket LIST, and overlap is
re-uploaded as a fresh part rather than clobbering existing ones.

## Redaction

Redaction is **on by default** and runs before any bytes leave the machine. It
is a regex denylist (`sdk/tracecraft/redact.py`) covering AWS, Anthropic,
OpenAI, HuggingFace, GitHub, and Slack token shapes plus bearer tokens. Every
match is **counted** in `meta.json` (`redaction_counts`), never silently
dropped.

```bash
tracecraft session mirror --harness claude-code            # redaction on (default)
tracecraft session mirror --harness claude-code --no-redact # raw, trusted buckets only
```

Redaction v0 catches well-known token shapes. It does **not** detect arbitrary
secrets, custom internal token formats, or proprietary content. Treat it as a
safety net, not a guarantee — and prefer a private bucket for session data.
