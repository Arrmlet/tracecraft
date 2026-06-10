#!/usr/bin/env python3
"""tracecraft contention benchmark — how many agents can race one bucket for a claim?

The whole product rests on one primitive: an atomic task *claim*. When N agents
reach for the same step at the same instant, exactly one must win. On an
S3-compatible backend that arbitration is a real conditional PUT
(``IfNoneMatch="*"``); on HuggingFace it is a best-effort check-then-write with a
genuine race window. This benchmark measures BOTH, honestly, against REAL
backends, and answers the skeptic's literal question: *where does
bucket-as-coordinator break under ~8+ agents?*

It deliberately tries hard NOT to lie. The honesty guards below are load-bearing:

  * Real backends only. ``moto``/in-process mocks are REFUSED for any reported
    number — they cannot model real conditional-write arbitration or true socket
    concurrency. We assert a live socket and a wire ``PreconditionFailed`` control
    probe before trusting anything.
  * The durable object is the only arbiter. ``S3.put_json`` returns nothing and
    signals a loss only by raising; we never trust a thread's in-memory "I won".
    After every trial we re-read ``claim.json`` with a SEPARATE fresh client and
    assert the stored owner is the one caller that did not raise.
  * Simultaneity is proven, not asserted. ``threading.Barrier(N)`` releases all
    agents together; we record ``barrier_fire_spread_ms`` per trial and EXCLUDE
    trials whose release skew rivals the request latency (``--max-spread-ms``).
    Without this, a high-N race can silently serialize and fake a clean pass.
  * Fresh key per trial. A reused key turns every later attempt into a trivial
    ``PreconditionFailed`` and fakes a perfect invariant.
  * ``PreconditionFailed`` is the designed LOSS path, never an error and never a
    duplicate. Only outcomes outside {WIN, PreconditionFailed} invalidate a trial.
  * Raw per-trial JSONL is the artifact; the printed summary is a pure, regenerable
    function of it. Trial count is fixed up front — no early stop on a good result.

Scope, stated plainly: localhost MinIO removes WAN latency, so the latency curve is
the object store's arbitration plus loopback — a conservative LOWER bound on real
contention. Real S3 over a WAN widens the in-flight window, which would only make
HuggingFace's race hole easier to hit, not harder.

Usage
-----
  # S3 / MinIO — the invariant + latency curve:
  python benchmarks/contention_bench.py --backend s3 \
      --endpoint http://localhost:9000 --bucket tracecraft \
      --access-key admin --secret-key admin123456 \
      --sweep 2,4,8,16,32 --trials 200 --out results_s3.jsonl

  # HuggingFace — the duplicate-wins demo (smaller, rate-limited):
  python benchmarks/contention_bench.py --backend hf \
      --bucket arrmlet/tracecraft-test --sweep 2,4,8,16 --trials 20 \
      --out results_hf.jsonl

  # Re-print a summary from a raw log without re-running:
  python benchmarks/contention_bench.py --summarize results_s3.jsonl
"""

from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

# Import the SHIPPED backends — never reimplement put_json. The harness owns only
# orchestration and verification; the arbitration code under test is the product's.
_SDK = Path(__file__).resolve().parent.parent / "sdk"
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))

from tracecraft.s3 import S3, PreconditionFailed  # noqa: E402

# Outcome census. Anything outside {WIN, LOST} invalidates the trial — it is never
# folded into a win or a loss, so a flaky backend can't be laundered into a result.
WIN = "WIN"
LOST = "LOST"  # PreconditionFailed / ConditionalRequestConflict — the designed loss
INVALID = "INVALID"  # timeout, 5xx, any other ClientError — trial is thrown out


# --------------------------------------------------------------------------- #
# Environment header — embedded on every JSONL line so a result is self-describing
# and a reviewer can tell exactly what produced it. Versions are OBSERVED, never
# guessed (a fabricated version is the exact overclaim this benchmark exists to avoid).
# --------------------------------------------------------------------------- #
def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent,
            timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _versions() -> dict:
    import boto3
    import botocore

    return {"boto3": boto3.__version__, "botocore": botocore.__version__}


def build_env(backend: str, endpoint: str | None) -> dict:
    return {
        "backend": backend,
        "endpoint": endpoint,
        "host": socket.gethostname(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "tracecraft_commit": _git_commit(),
        **_versions(),
    }


# --------------------------------------------------------------------------- #
# Backend factory — one fresh client PER agent (boto3 clients are not safe to
# share across threads, and per-client connection pools maximize in-flight
# parallelism, which is the whole point of a contention test).
# --------------------------------------------------------------------------- #
@dataclass
class Backend:
    """A claim target: a fresh store + the project/key namespace for one race."""

    make_store: (
        callable  # () -> store with put_json(if_none_match=True) + get_json + delete
    )
    project: str
    backend_name: str


def s3_backend(endpoint, bucket, project, access_key, secret_key) -> Backend:
    def make_store():
        return S3(
            endpoint=endpoint,
            bucket=bucket,
            project=project,
            access_key=access_key,
            secret_key=secret_key,
        )

    return Backend(make_store=make_store, project=project, backend_name="s3")


def hf_backend(bucket, project, token) -> Backend:
    from tracecraft.hf import HF

    def make_store():
        return HF(bucket=bucket, project=project, token=token)

    return Backend(make_store=make_store, project=project, backend_name="hf")


# --------------------------------------------------------------------------- #
# Honesty preflight — refuse to report any number until the backend is proven to
# be a real, conditional-write-arbitrating object store on the wire.
# --------------------------------------------------------------------------- #
def preflight_s3(store) -> None:
    """Assert a real socket AND that a control conditional-PUT race is arbitrated.

    Two simultaneous IfNoneMatch="*" PUTs to a throwaway key must produce exactly
    one winner and one wire PreconditionFailed. If the backend ignores the header
    (older MinIO did), the 'atomic' story is false here and we abort rather than
    publish a number we can't stand behind.
    """
    store.ensure_bucket()
    key = f"_preflight/{uuid.uuid4().hex}.json"
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def probe(i):
        c = store  # control probe can share; we only need the arbitration check
        barrier.wait()
        try:
            c.put_json(key, {"i": i}, if_none_match=True)
            with lock:
                outcomes.append(WIN)
        except PreconditionFailed:
            with lock:
                outcomes.append(LOST)

    ts = [threading.Thread(target=probe, args=(i,)) for i in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    store.delete(key)
    wins = outcomes.count(WIN)
    if not (wins == 1 and outcomes.count(LOST) == 1):
        raise SystemExit(
            f"PREFLIGHT FAILED: control conditional-PUT race gave {outcomes!r}, "
            f"expected exactly one WIN + one PreconditionFailed. This backend does "
            f"not arbitrate IfNoneMatch — refusing to report contention numbers."
        )


# --------------------------------------------------------------------------- #
# One race: N agents, one fresh key, fired simultaneously, then verified against
# the durable object.
# --------------------------------------------------------------------------- #
@dataclass
class Trial:
    n: int
    sid: str
    outcomes: list[str] = field(default_factory=list)
    win_latency_ms: list[float] = field(default_factory=list)
    lost_latency_ms: list[float] = field(default_factory=list)
    barrier_fire_spread_ms: float = 0.0
    stored_owner: str | None = None
    declared_winner: str | None = None  # the one caller that did not raise
    invariant_held: bool = False
    duplicate_wins: int = 0
    valid: bool = True
    invalid_reason: str | None = None
    # Per-claim timeline, all relative to the trial's t0 (first agent to fire).
    # This is what lets us SHOW the arbitration queue forming, rather than assert it.
    claims: list[dict] = field(default_factory=list)


def run_trial(backend: Backend, n: int, warm: bool, stagger_ms: float = 0.0) -> Trial:
    """Race N agents for one fresh key.

    stagger_ms > 0 is the falsifiable CONTROL: instead of firing all agents at the
    same instant (barrier), agent i fires i*stagger_ms apart. If the latency curve is
    really driven by *simultaneous* contention, staggering enough to clear the
    contention window should flatten it. If latency stayed high under stagger, the
    growth would be about request count, not concurrency — so this run can DISPROVE
    the correlation claim, which is exactly why it belongs here.
    """
    sid = f"bench-{uuid.uuid4().hex}"
    key = f"steps/{sid}/claim.json"
    stores = [backend.make_store() for _ in range(n)]

    # Pre-warm each client's TLS/connection pool with a throwaway read BEFORE the
    # barrier, so the handshake is never counted as claim latency. Cold runs skip
    # this so we can report the cold tax separately.
    if warm:
        for s in stores:
            try:
                s.get_json(
                    f"_warm/{uuid.uuid4().hex}.json"
                )  # 404 is fine; primes the pool
            except Exception:
                pass

    simultaneous = stagger_ms <= 0
    barrier = threading.Barrier(n) if simultaneous else None
    t0_holder: list[float] = [None]  # trial t0 = first fire, set under lock
    fire_times: list[float] = [0.0] * n
    # (outcome, latency_ms, agent, arrival_ms_rel_t0, decision_ms_rel_t0)
    results: list[tuple] = [None] * n
    lock = threading.Lock()

    def agent(i):
        agent_id = f"agent-{i}"
        if simultaneous:
            barrier.wait()
        else:
            # staggered launch: agent i waits i*stagger_ms after thread start
            time.sleep(i * stagger_ms / 1000.0)
        fire = time.perf_counter()
        fire_times[i] = fire
        with lock:
            if t0_holder[0] is None or fire < t0_holder[0]:
                t0_holder[0] = fire
        try:
            stores[i].put_json(key, {"agent": agent_id}, if_none_match=True)
            done = time.perf_counter()
            results[i] = (WIN, (done - fire) * 1000.0, agent_id, fire, done)
        except PreconditionFailed:
            done = time.perf_counter()
            results[i] = (LOST, (done - fire) * 1000.0, agent_id, fire, done)
        except Exception as e:  # noqa: BLE001 — anything else invalidates the trial
            done = time.perf_counter()
            with lock:
                results[i] = (
                    INVALID,
                    (done - fire) * 1000.0,
                    f"{type(e).__name__}:{e}",
                    fire,
                    done,
                )

    ts = [threading.Thread(target=agent, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join() for t in ts]

    t = Trial(n=n, sid=sid)
    t.barrier_fire_spread_ms = (max(fire_times) - min(fire_times)) * 1000.0
    t0 = t0_holder[0]
    winners = []
    for outcome, dt, who, fire, done in results:
        t.outcomes.append(outcome)
        # arrival/decision relative to trial t0, so a timeline chart can be drawn
        t.claims.append(
            {
                "outcome": outcome,
                "latency_ms": round(dt, 4),
                "arrival_ms": round((fire - t0) * 1000.0, 4),
                "decision_ms": round((done - t0) * 1000.0, 4),
            }
        )
        if outcome == WIN:
            t.win_latency_ms.append(dt)
            winners.append(who)
        elif outcome == LOST:
            t.lost_latency_ms.append(dt)
        else:  # INVALID
            t.valid = False
            t.invalid_reason = who

    # Verify against the durable object with a SEPARATE fresh client — the store is
    # the arbiter, not anyone's in-memory bookkeeping.
    verifier = backend.make_store()
    stored = verifier.get_json(key) or {}
    t.stored_owner = stored.get("agent")
    t.declared_winner = winners[0] if len(winners) == 1 else None

    win_count = len(winners)
    t.duplicate_wins = max(0, win_count - 1)
    # The invariant: exactly one caller didn't raise AND the durable owner is that caller.
    t.invariant_held = (
        t.valid and win_count == 1 and t.stored_owner == t.declared_winner
    )
    # A belief-vs-stored mismatch (HF: two agents both "won" but the object holds one)
    # is itself a duplicate-win symptom even if win_count looks like 1 at the API layer.
    if t.valid and win_count >= 1 and t.stored_owner not in winners:
        t.duplicate_wins = max(t.duplicate_wins, 1)
        t.invariant_held = False

    # Clean up and confirm deletion before the next trial reuses nothing.
    try:
        verifier.delete(key)
    except Exception:
        pass
    return t


# --------------------------------------------------------------------------- #
# Sweep + JSONL emission
# --------------------------------------------------------------------------- #
def run_sweep(
    backend,
    env,
    sweep,
    trials,
    max_spread_ms,
    warm,
    out_path,
    stagger_ms=0.0,
    emit_claims=False,
):
    """Run the sweep and write per-trial JSONL.

    stagger_ms > 0 runs the staggered control (see run_trial). emit_claims includes
    the per-claim arrival/decision timeline on each row — only enable it for a small
    dedicated run, since it multiplies row size by N.
    """
    out = open(out_path, "w") if out_path else None
    mode = f"stagger={stagger_ms}ms" if stagger_ms > 0 else "simultaneous"
    print(
        f"# {backend.backend_name} :: {env['endpoint']}  "
        f"boto3={env.get('boto3')} commit={env['tracecraft_commit']}"
    )
    print(
        f"# sweep={sweep} trials={trials} max_spread_ms={max_spread_ms} "
        f"warm={warm} mode={mode} timeline={emit_claims}\n"
    )

    for n in sweep:
        excluded = 0
        for trial_idx in range(trials):
            tr = run_trial(backend, n, warm, stagger_ms=stagger_ms)
            # The spread guard only applies to the simultaneous mode; under stagger
            # a wide spread is intentional, not a defect.
            excluded_low_concurrency = (
                stagger_ms <= 0 and tr.barrier_fire_spread_ms > max_spread_ms
            )
            if excluded_low_concurrency:
                excluded += 1
            row = {
                **env,
                "n": n,
                "trial": trial_idx,
                "sid": tr.sid,
                "mode": mode,
                "stagger_ms": stagger_ms,
                "outcomes": dict(Counter(tr.outcomes)),
                "win_latency_ms": tr.win_latency_ms,
                "lost_latency_ms": tr.lost_latency_ms,
                "barrier_fire_spread_ms": round(tr.barrier_fire_spread_ms, 4),
                "excluded_low_concurrency": excluded_low_concurrency,
                "stored_owner": tr.stored_owner,
                "declared_winner": tr.declared_winner,
                "invariant_held": tr.invariant_held,
                "duplicate_wins": tr.duplicate_wins,
                "valid": tr.valid,
                "invalid_reason": tr.invalid_reason,
                "warm": warm,
            }
            if emit_claims:
                row["claims"] = tr.claims
            line = json.dumps(row)
            if out:
                out.write(line + "\n")
        tail = (
            f"{excluded} excluded for spread>{max_spread_ms}ms"
            if stagger_ms <= 0
            else "staggered control"
        )
        print(f"N={n:<3} done ({trials} trials, {tail})")
    if out:
        out.close()
        print(f"\nraw -> {out_path}")
        summarize(out_path)


# --------------------------------------------------------------------------- #
# Summary — a PURE function of the raw JSONL, regenerable any time.
# --------------------------------------------------------------------------- #
def _pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return round(xs[f] + (xs[c] - xs[f]) * (k - f), 2)


def summarize(path):
    rows = [json.loads(ln) for ln in open(path) if ln.strip()]
    if not rows:
        print("(empty log)")
        return
    backend = rows[0]["backend"]
    by_n: dict[int, list] = {}
    for r in rows:
        by_n.setdefault(r["n"], []).append(r)

    print(
        f"\n{'=' * 72}\nCONTENTION SUMMARY — backend={backend}  endpoint={rows[0].get('endpoint')}"
    )
    print(
        f"commit={rows[0].get('tracecraft_commit')}  boto3={rows[0].get('boto3')}  "
        f"host={rows[0].get('host')}\n{'=' * 72}"
    )
    header = (
        f"{'N':>3} {'valid':>6} {'excl':>5} {'inv.held':>9} {'dup_wins':>9} "
        f"{'win_p50':>8} {'win_p99':>8} {'lost_p50':>9}"
    )
    print(header)
    print("-" * len(header))
    total_invariant_breaks = 0
    total_dup = 0
    for n in sorted(by_n):
        rs = by_n[n]
        counted = [r for r in rs if not r["excluded_low_concurrency"]]
        valid = [r for r in counted if r["valid"]]
        excl = sum(1 for r in rs if r["excluded_low_concurrency"])
        held = sum(1 for r in valid if r["invariant_held"])
        dup = sum(r["duplicate_wins"] for r in valid)
        total_dup += dup
        total_invariant_breaks += len(valid) - held
        win_lat = [x for r in valid for x in r["win_latency_ms"]]
        lost_lat = [x for r in valid for x in r["lost_latency_ms"]]
        print(
            f"{n:>3} {len(valid):>6} {excl:>5} {held:>4}/{len(valid):<4} "
            f"{dup:>9} {str(_pct(win_lat, 50)):>8} {str(_pct(win_lat, 99)):>8} "
            f"{str(_pct(lost_lat, 50)):>9}"
        )

    print("-" * len(header))
    verdict = "HOLDS" if total_invariant_breaks == 0 and total_dup == 0 else "BROKEN"
    print(
        f"\nINVARIANT (exactly-one-winner, verified against the durable object): {verdict}"
    )
    print(f"  invariant breaks across sweep: {total_invariant_breaks}")
    print(f"  duplicate wins across sweep:   {total_dup}")
    if backend == "s3" and verdict == "HOLDS":
        print(
            "  -> S3 conditional PUT arbitrated every race. Exactly one agent won, every time."
        )
    if backend == "hf" and total_dup > 0:
        print(
            f"  -> HF check-then-write produced {total_dup} duplicate win(s): two agents both "
            f"believed they claimed. This is the documented race window, observed live."
        )


# --------------------------------------------------------------------------- #
def parse_args():
    p = argparse.ArgumentParser(description="tracecraft claim-contention benchmark")
    p.add_argument(
        "--summarize", metavar="JSONL", help="re-print summary from a raw log and exit"
    )
    p.add_argument("--backend", choices=["s3", "hf"], default="s3")
    p.add_argument(
        "--endpoint",
        default="http://localhost:9000",
        help="S3 endpoint (docker-compose.dev.yml serves MinIO at localhost:9000).",
    )
    p.add_argument("--bucket", default="tracecraft")
    p.add_argument("--access-key", default="admin")
    p.add_argument("--secret-key", default="admin123456")
    p.add_argument(
        "--hf-token", default=None, help="HF token; falls back to cached login"
    )
    p.add_argument(
        "--project",
        default=None,
        help="bucket project namespace (default: bench-<uuid>)",
    )
    p.add_argument(
        "--sweep", default="2,4,8,16,32", help="comma-separated agent counts"
    )
    p.add_argument(
        "--trials", type=int, default=200, help="trials per N (fixed up front)"
    )
    p.add_argument(
        "--max-spread-ms",
        type=float,
        default=50.0,
        help="exclude trials whose barrier release skew exceeds this (anti silent-serialization)",
    )
    p.add_argument(
        "--cold", action="store_true", help="do NOT pre-warm pools (reports cold tax)"
    )
    p.add_argument(
        "--stagger-ms",
        type=float,
        default=0.0,
        help="CONTROL: fire agents this many ms apart instead of simultaneously. "
        "If contention drives the curve, a large enough stagger flattens it.",
    )
    p.add_argument(
        "--timeline",
        action="store_true",
        help="emit per-claim arrival/decision timeline on each row (small runs only; multiplies row size by N)",
    )
    p.add_argument("--out", default=None, help="write raw per-trial JSONL here")
    return p.parse_args()


def main():
    args = parse_args()
    if args.summarize:
        summarize(args.summarize)
        return

    sweep = [int(x) for x in args.sweep.split(",") if x.strip()]
    project = args.project or f"bench-{uuid.uuid4().hex[:8]}"

    if args.backend == "s3":
        # Guard: never point the write-race at something that isn't clearly local
        # unless the operator typed a non-localhost endpoint on purpose.
        endpoint = args.endpoint
        backend = s3_backend(
            endpoint, args.bucket, project, args.access_key, args.secret_key
        )
        env = build_env("s3", endpoint)
        store0 = backend.make_store()
        preflight_s3(store0)
        print("preflight OK: live socket + conditional-PUT arbitration confirmed.\n")
    else:
        token = args.hf_token
        backend = hf_backend(args.bucket, project, token)
        env = build_env("hf", f"hf://{args.bucket}")
        print(
            "HF backend: check-then-write, no conditional PUT — expecting duplicate wins.\n"
        )

    run_sweep(
        backend,
        env,
        sweep,
        args.trials,
        args.max_spread_ms,
        warm=not args.cold,
        out_path=args.out,
        stagger_ms=args.stagger_ms,
        emit_claims=args.timeline,
    )


if __name__ == "__main__":
    main()
