# traces-v1 — Session Mirror & Replay

**Branch:** `traces-v1`
**Target release:** `0.2.0`
**Estimated effort:** 12–14 working days
**Status:** drafted 2026-05-20

---

## 1. Why this exists (the only thing that matters)

The 2026-05 market scan (`plans/MARKET_REPORT_SESSIONS_2026_05.md`) found
session-mirroring is **commodity**:

- Anthropic ships **SessionStore** (Claude-Code-native, opaque cloud)
- HuggingFace ships **Storage Buckets + Agent Trace Viewer** (HF-only)
- **DataClaw** (2.1k★) and **claude-sync** (119★) already mirror local JSONL

So copying any of them is a waste. Tracecraft's session mirror only earns
its place if it does **three things none of them do**:

1. **Cross-backend.** Any S3-compatible bucket (AWS, R2, MinIO, B2, Wasabi)
   *and* HF Buckets. The user owns the data; we never see it.
2. **Sessions + coordination in one bucket.** Tracecraft already stores
   memory / mailbox / claims / artifacts under `<project>/`. Putting
   harness sessions under the same `<project>/sessions/` namespace
   means one bucket holds the *entire* multi-agent history.
3. **Cross-harness replay.** Claude Code JSONL + Codex JSONL + tracecraft
   coordination events merged into one timeline. This is the killer
   demo: "watch four Claude Code agents coordinate, see each one's
   reasoning, see the messages between them, in a single HTML."

If at any point during implementation we feel pulled toward features
that don't serve those three goals, stop and re-read this section.

---

## 2. Non-goals

These look tempting and are deliberately excluded from `0.2.0`:

- **Real-time UI.** Replay is a static HTML render of a finished bucket.
  No live websocket, no dashboard server.
- **LLM-based redaction.** Regex denylist v0 only; LLM redaction is a
  later-tier item once we know the false-positive rate.
- **Trace signing / SN13 submission.** That's `SN13_AGENT_TRACES_PITCH.md`
  territory, separate 3-week de-risk plan.
- **Anthropic SessionStore integration.** Their API, their schema,
  their lock-in. We mirror the local JSONL — that's the open path.
- **MCP server.** Already decided redundant given CLI + SKILL.md.
- **Cursor / Cline / Aider support.** Claude Code + Codex first. Others
  follow only if there's demand and a JSONL-equivalent format.
- **TTL claims, heartbeat refresh, message-key collision.** These are
  Tier 1 fixes from `RESEARCH_2026_05.md`. Bundle them in `0.2.1` if
  traces-v1 didn't subsume the need.

---

## 3. Scope: nine deliverables

| # | Deliverable | Approx LoC | Days |
|---|-------------|-----------|------|
| D1 | `tracecraft session mirror` (Claude Code) | 150 | 2 |
| D2 | Claude Code plugin (`.claude-plugin/`) | 250 | 1 |
| D3 | Codex variant | 80 | 1 |
| D4 | `tracecraft session list / show` | 80 | 1 |
| D5 | `tracecraft replay` (the killer demo) | 350 | 2 |
| D6 | Redaction v0 (regex denylist) | 100 | 0.5 |
| D7 | Tests (moto + golden JSONL fixtures) | 250 | 1.5 |
| D8 | Docs (README + SKILL.md + plugin README) | — | 1 |
| D9 | Launch artifact (4-agent demo recording) | — | 1 |

Total: ~1,260 LoC, 11 working days + 1 day slack.

---

## 4. Bucket layout (additive — does not touch existing keys)

```
<bucket>/<project>/
  …existing keys (agents/, memory/, messages/, steps/, artifacts/)…
  sessions/
    claude-code/
      <session-id>.jsonl          ← raw JSONL stream (append-only)
      <session-id>.meta.json      ← cwd, started_at, ended_at, agent_id,
                                    line_count, redacted_count, schema_version
    codex/
      <session-id>.jsonl
      <session-id>.meta.json
    _index.json                   ← list of all sessions (rebuilt on each upload)
```

**Why a separate top-level `sessions/` instead of nesting under `agents/`:**
sessions belong to a *harness instance*, not always to a registered tracecraft
agent. A solo dev running Claude Code with no `tracecraft init agents/...` still
benefits from the mirror. Linking to an `agent_id` is optional metadata.

---

## 5. D1 — `tracecraft session mirror` (the foundation)

### Command
```
tracecraft session mirror [--harness claude-code|codex] [--session-id <id>]
                          [--watch-dir <path>] [--batch-seconds 5]
                          [--once] [--detach]
```

### Behaviour
1. Auto-detect the active session if `--session-id` is omitted:
   - **Claude Code:** glob `~/.claude/projects/<encoded-cwd>/*.jsonl`,
     pick the one with the most recent `mtime`.
   - **Codex:** glob `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl`,
     same heuristic.
2. Tail the file (resume from byte offset stored in
   `~/.tracecraft/mirror-<session-id>.state`).
3. Every `--batch-seconds` (default 5), flush the new bytes to
   `sessions/<harness>/<session-id>.jsonl` using
   **multipart append via copy-then-put** (S3 has no native append;
   we re-upload the growing object, see §5.3).
4. Update `<session-id>.meta.json` on every flush.
5. Track PID in `~/.tracecraft/mirror.pid` (per-session, not global) so
   the user can `tracecraft session stop <session-id>` cleanly.
6. `--detach` forks a background process (Unix `os.fork()`,
   on Windows fall back to subprocess + log file).
7. `--once` does a single sync and exits (good for cron / hooks).

### 5.1 Append strategy on S3

S3 has no `append`. Options considered:

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Re-upload full file every batch | Trivial | Cost grows O(n²) for long sessions | ✗ |
| One object per batch (`<sid>.<seq>.jsonl`) | Cheap, no read-back | Replay must list+merge | ✓ chosen |
| S3 multipart upload kept open | True append-ish | Multipart sessions abort on agent crash | ✗ |

**Chosen:** one object per batch. Final layout:
```
sessions/claude-code/<session-id>/
  part-00000.jsonl
  part-00001.jsonl
  …
  meta.json
```
Replay/show concatenates parts in order. `tracecraft session compact <sid>`
(later) merges into one file for archival.

Trade-off accepted: more list operations during replay. Cheap on S3
($0.005 per 1000 LIST). For long sessions this is materially better.

### 5.2 State file format

`~/.tracecraft/mirror-state/<session-id>.json`:
```json
{
  "harness": "claude-code",
  "session_id": "abc123",
  "source_path": "/Users/x/.claude/projects/.../abc123.jsonl",
  "bucket_prefix": "sessions/claude-code/abc123/",
  "byte_offset": 142857,
  "next_part_seq": 12,
  "last_flush": "2026-05-20T10:15:00Z",
  "pid": 4523
}
```

### 5.3 Graceful shutdown
- `SIGTERM` / `SIGINT` → flush pending buffer, write final meta, remove pid.
- Crash → state file lets next `mirror` invocation resume from `byte_offset`.
- Idempotency: if `part-<seq>.jsonl` already exists at the target key,
  bump `next_part_seq` until empty slot found (defends against duplicate
  uploads after partial crash).

---

## 6. D2 — Claude Code plugin

### Why a plugin (vs a hook the user installs manually)
The whole point is **zero-friction**. If the user has to edit JSON
config files, we lose. `/plugin install tracecraft` should be the path.

### Files in `plugins/claude-code/`
```
plugins/claude-code/
  .claude-plugin/
    plugin.json              ← name, version, hooks, commands
  hooks/
    session-start.sh         ← spawns `tracecraft session mirror --detach`
    session-end.sh           ← `tracecraft session stop $CLAUDE_SESSION_ID`
  skills/
    tracecraft.md            ← SKILL.md so Claude inside Claude Code knows
                               how to use tracecraft for coordination
  commands/
    tc-mirror.md             ← /tc-mirror slash command (start/stop/status)
    tc-replay.md             ← /tc-replay slash command
  README.md
```

### Submission target
Anthropic's plugin marketplace + GitHub direct-install path
(`/plugin install Arrmlet/tracecraft`).

### Open question to resolve during impl
Does `SessionStart` hook fire on `claude --resume`? If not, we also
need a `UserPromptSubmit` hook with a "have we started mirroring?" guard.
(Test on day 1 of D2; cheap to verify.)

---

## 7. D3 — Codex variant

Codex CLI writes to `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-*.jsonl`.
Schema differs (it's not Claude-Code JSONL) but the *act of tailing* is
identical. ~50 LoC: just a new `Harness` adapter that knows the
glob pattern and (optionally) translates entries to a normalized schema.

For replay we'll keep entries in their native schema and let the
renderer handle two harness types side-by-side. **No premature
normalization** — if a third harness lands, then we extract a base.

---

## 8. D4 — `session list` / `session show`

```
tracecraft session list [--harness claude-code|codex] [--limit 20]
tracecraft session show <session-id> [--tail 50]
tracecraft session stop <session-id>
```

Reads `<project>/sessions/_index.json`. `_index.json` is rewritten on
each meta update (write whole file — it's tiny; ~1 KB per 100 sessions).

---

## 9. D5 — `tracecraft replay` (the killer demo)

This is where tracecraft stops looking like "yet another session
mirror" and becomes a coordination viewer.

### Command
```
tracecraft replay [--project <name>] [--out replay.html] [--open]
                  [--since <iso>] [--until <iso>]
```

### What it does
1. Pulls **all** of `<project>/`:
   - `agents/*.json` (registered agents)
   - `memory/*.json` (every memory write — but memory keys don't have
     timestamps; we'll need to add `_updated_at` to memory writes —
     small backwards-compatible change)
   - `messages/**/*.json` (every message)
   - `steps/**/*.json` (every claim/handoff/status)
   - `sessions/**/part-*.jsonl` (every harness event)
2. Builds a unified timeline (single sorted array of events,
   each tagged with `event_type` and `agent_id`).
3. Renders a **single self-contained HTML file** (no server) with:
   - vertical timeline (newest at top or oldest at top, toggle)
   - one swim-lane per agent
   - colour-coding: coordination events (claim/message/memory) vs
     harness events (tool-use, reasoning, file-edit)
   - click any event → expand JSON
   - filter by agent / event type / text search

### Tech for the HTML
- Pure HTML + vanilla JS embedded in one file. **No build step.**
  React/Vite would be faster to write but harder to ship and harder
  for users to inspect/trust.
- One inlined `<script>` with the events array as JSON.
- ~350 LoC including CSS.

### Why this is the artifact
When we show "four Claude Code agents coordinating on a real project,
here's the HTML, every reasoning step + every message + every claim
visible on one timeline" — *nobody else has that*. Anthropic's
SessionStore can't see your other agents. HF's Trace Viewer is
single-session. This is the differentiation made real.

---

## 10. D6 — Redaction v0

Regex denylist applied **at flush time** (before bytes leave the machine):

- AWS keys: `(?i)(aws_(access|secret)_(key|access_key_id)\s*[:=]\s*['"]?)[A-Za-z0-9/+=]{16,}`
- Anthropic: `sk-ant-[A-Za-z0-9_-]{20,}`
- OpenAI: `sk-[A-Za-z0-9]{20,}` (plus `sk-proj-`, `sk-svcacct-`)
- HF: `hf_[A-Za-z0-9]{30,}`
- GitHub: `ghp_[A-Za-z0-9]{30,}` `gho_` `ghu_` `ghs_` `ghr_`
- Generic envvar leaks: lines matching `[A-Z_]+_TOKEN=` / `_KEY=` / `_SECRET=`
- Bearer tokens: `Bearer [A-Za-z0-9_.-]{20,}`
- Absolute home paths → `~`

Each redaction is **counted, not silenced**: meta.json records
`{"redactions": {"aws_key": 2, "anthropic_key": 1, ...}}` so users
can audit. Add `--no-redact` for users who *want* raw (e.g., they
control the bucket entirely and prefer full fidelity).

False-positive escape valve: `.tracecraft-redact.yml` in cwd can
add/remove patterns.

---

## 11. D7 — Tests

Build on the `moto`-based test infra from Tier 0.

**Core tests:**
- `test_mirror_creates_part_objects` — write JSONL locally, run mirror
  with `--once`, assert `part-00000.jsonl` exists with correct bytes.
- `test_mirror_resumes_from_offset` — partial flush, re-run, verify
  only new bytes go to `part-00001.jsonl`.
- `test_mirror_idempotent_on_crash_recovery` — pre-create
  `part-00000.jsonl`, verify mirror bumps to `part-00001.jsonl`.
- `test_redaction_v0_catches_aws_key` — feed a JSONL line with an
  AWS key, verify it's `[REDACTED:aws_key]` in the part object and
  counted in meta.
- `test_redaction_no_redact_flag_passes_through` — same line,
  `--no-redact`, raw bytes preserved.
- `test_session_list_returns_all_harnesses`
- `test_session_show_concatenates_parts_in_order`
- `test_replay_merges_coordination_and_harness_events_by_timestamp` —
  the critical one. Seed bucket with a memory write at t=1, a message
  at t=2, a harness JSONL line at t=3, verify the HTML output's
  embedded JSON array contains all three in order.

**Golden JSONL fixtures:** `sdk/tests/fixtures/claude-code-sample.jsonl`
and `codex-sample.jsonl` — small, real-shape, scrubbed.

---

## 12. D8 — Docs

- `README.md`: add a "Session mirror" section after the existing
  coordination examples, with a 4-line quickstart.
- `docs/session-mirror.md`: full reference (commands, flags,
  state file format, redaction config).
- `plugins/claude-code/README.md`: install instructions.
- `CLAUDE.md`: add `sessions/` to the bucket-layout diagram.

---

## 13. D9 — Launch artifact

Record (asciinema or screencap) a real demo:

1. `tracecraft init` in a fresh dir.
2. Spawn 4 Claude Code instances, each as a different agent.
3. Give them a small shared task ("build a CLI that parses JSON")
   — one claims `design`, one `impl`, one `tests`, one `docs`.
4. Let them coordinate via tracecraft (mailbox + handoffs).
5. Each Claude Code instance auto-mirrors its session via the plugin.
6. Run `tracecraft replay` → open the HTML.
7. Screenshot the swim-lane view showing all four agents'
   reasoning + their cross-agent messages on one timeline.

This is the asset that ships with the 0.2.0 release post.

---

## 14. Sequencing & dependencies

```
D1 (mirror core) ─┬─► D3 (codex) ─┐
                  ├─► D6 (redact)  ├─► D7 (tests)
                  └─► D4 (list/show)┘                          ─► D8 (docs) ─► D9 (demo) ─► release 0.2.0
D1 ─► D2 (plugin)                  ─► D5 (replay, needs sessions in bucket)
```

D5 (replay) is the long pole and the differentiator. If we slip,
slip everything else, not replay.

---

## 15. Risk register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Claude Code JSONL schema changes mid-build | Med | Med | Pin to current schema, golden fixture, version-detect via first-line metadata |
| Anthropic launches matching coordination viewer | Low | High | Replay's value is *cross-harness*; their viewer will be Claude-only |
| Plugin install UX requires Anthropic approval | Med | Med | Ship as `git clone` first, marketplace second |
| Mirror crashes silently and user thinks they have a backup | Med | High | Loud failure: write `~/.tracecraft/mirror-errors.log`, surface in `tracecraft session list` |
| Bucket cost surprise for heavy users | Low | Med | Doc the storage math, suggest lifecycle rules |
| Redaction misses something and a secret lands in a public bucket | Low | Critical | Default-on redaction, count + show redactions in meta, doc the limits clearly |

---

## 16. Definition of done for 0.2.0

- [ ] `tracecraft session mirror`, `list`, `show`, `stop` shipped
- [ ] Claude Code plugin published to GitHub (`Arrmlet/tracecraft`)
- [ ] Codex harness supported
- [ ] `tracecraft replay` produces a self-contained HTML with
      cross-agent + cross-harness timeline
- [ ] Redaction v0 on by default, counted in meta, `.tracecraft-redact.yml`
      escape valve documented
- [ ] All Tier 0 tests still green; new tests for mirror + replay green
- [ ] CI green on Python 3.10 / 3.11 / 3.12 / 3.13
- [ ] Demo HTML committed to `examples/replay-demo.html`
- [ ] PyPI 0.2.0 published via the trusted-publishing pipeline
- [ ] Launch post drafted in `plans/LAUNCH_TWEET.md` (or sibling)

---

## 17. What we explicitly defer to 0.2.x / 0.3.0

- Tier 1 fixes (TTL claims, heartbeat refresh, message-key collisions)
- LLM-based redaction
- Cursor / Cline / Aider harnesses
- Live replay (websocket)
- Trace signing (Ed25519) — prerequisite for SN13 pitch, separate plan
- Memory `_updated_at` timestamps — *unless* replay needs it; if so,
  pull forward into D5

---

## 18. Sign-off checklist (review before writing the first line of code)

- [ ] Does every deliverable serve at least one of: cross-backend,
      coordination+sessions in one place, cross-harness replay?
- [ ] Have we re-read `plans/MARKET_REPORT_SESSIONS_2026_05.md`
      and confirmed nothing here duplicates SessionStore / HF Viewer /
      DataClaw / claude-sync?
- [ ] Is anything here *not* required for the 4-agent launch demo?
- [ ] If we shipped only D1+D2+D5, would the launch story still hold?
      (If yes, that's our minimum lovable cut.)

---

**Next step:** review this plan; if it holds, start D1. Minimum
lovable cut is D1 + D2 + D5 — if time pressure hits, drop D3 (Codex),
D4 (list/show CLI sugar), D6 (redaction v0 default), and ship the
rest in 0.2.1.
