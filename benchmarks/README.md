# Contention benchmark — how many agents can race one bucket for a claim?

tracecraft's whole premise is one primitive: an **atomic task claim**. When N agents
reach for the same step at the same instant, exactly one must win, with no server in
the middle. This benchmark stress-tests that primitive against **real backends** and
answers two questions honestly:

1. **Does the invariant hold?** Under contention, does *exactly one* agent win — verified
   against the durable object, not a thread's own belief?
2. **What does claim latency do as agents pile on, and why?** Specifically: does latency
   track the number of agents *because they are simultaneous*, or just because there are
   more of them?

The headline result, in plain words:

- **On S3/MinIO the invariant never breaks** — exactly one winner across every valid
  trial from 2 to 50 simultaneous agents, zero duplicate wins.
- **Claim latency rises with N only when the agents fire simultaneously.** A *staggered*
  control with the identical agent counts stays flat at the base round-trip. So the
  driver is **simultaneity, not request count** — which is exactly why "number of
  *simultaneously*-working agents" is the right framing.
- **On HuggingFace the invariant breaks on every trial** — no conditional write means
  check-then-write, so everyone "wins" and the Hub keeps the last. Same harness, opposite
  result, which proves the harness can detect a broken coordinator.

## The report

The visual writeup is a single self-contained HTML file —
[`contention_report.html`](contention_report.html) — that opens offline by double-click
(no CDN, no network, hand-drawn inline SVG). Every number in it is computed in Python from
the raw per-trial logs by [`build_report.py`](build_report.py), reusing the benchmark's
own percentile function so the report can never disagree with `--summarize`. Nothing is
hardcoded; regenerate it any time with:

```bash
python benchmarks/build_report.py
```

It has six figures: the latency-vs-N elbow, the **simultaneous-vs-staggered falsification
test** (the causal proof), a per-claim timeline showing the arbitration queue forming, a
chart of the confound stated *against ourselves*, loser-vs-winner latency, and the S3-vs-HF
correctness control.

## Reproduce the data

```bash
# 1. The latency curve + invariant (the headline sweep)
python benchmarks/contention_bench.py --backend s3 \
    --endpoint http://localhost:9000 --bucket tracecraft \
    --access-key admin --secret-key admin123456 \
    --sweep 2,4,8,16,32,50 --trials 200 --out benchmarks/results_s3.jsonl

# 2. The falsification control — fire agents 25ms apart instead of together.
#    If contention drives the curve, this flattens it. (It does.)
python benchmarks/contention_bench.py --backend s3 \
    --endpoint http://localhost:9000 --bucket tracecraft \
    --access-key admin --secret-key admin123456 \
    --sweep 2,4,8,16,32,50 --trials 50 --stagger-ms 25 \
    --out benchmarks/results_stagger.jsonl

# 3. The per-claim timeline — captures arrival + decision time per agent so you can
#    SEE the queue form. Small run only (multiplies row size by N).
python benchmarks/contention_bench.py --backend s3 \
    --endpoint http://localhost:9000 --bucket tracecraft \
    --access-key admin --secret-key admin123456 \
    --sweep 2,4,32,50 --trials 30 --timeline \
    --out benchmarks/results_timeline.jsonl

# 4. The correctness control — HuggingFace check-then-write (rate-limited, small)
HF_HUB_DISABLE_PROGRESS_BARS=1 python benchmarks/contention_bench.py --backend hf \
    --bucket <user>/<repo> --sweep 2,4,8 --trials 10 \
    --out benchmarks/results_hf.jsonl

# Then build the report:
python benchmarks/build_report.py

# Re-print any sweep summary from its raw log, no re-run:
python benchmarks/contention_bench.py --summarize benchmarks/results_s3.jsonl
```

(`docker compose -f docker-compose.dev.yml up -d` brings up the local MinIO at
`http://localhost:9000`, console on `:9001`.)

## Why latency correlates to *simultaneous* agents

Per-claim latency decomposes as `base_RTT + excess(N, simultaneity)`. The base round-trip
is the N=2 floor (one PUT to one object over loopback). The excess above that floor grows
with N — **but only under simultaneity**:

- **The falsification test settles it.** Same agent counts, same key, but fired 25ms apart
  (verified larger than the staggered service time, so no two requests ever overlap):
  latency collapses to the base floor and stays flat across all N. The simultaneous run
  rises; the staggered run does not. Same request *count* in both — the only difference is
  whether the requests are in flight at the same instant.
- **The timeline shows the mechanism.** With agents fired from a `threading.Barrier(N)`,
  arrival times stay tightly clustered while *decision* times fan out, and the decision
  fan-out exceeds the arrival skew by a growing margin (tens of ms at high N). That excess
  is the contended object being resolved one PUT at a time.
- **Losers cost more than winners** at every N — a rejected claim can only return after the
  winning PUT is durable.

## Honest limits (stated against ourselves)

These are in the report too, prominently — but to be upfront here:

- **It's the worst case.** The benchmark measures N agents contending for the *same* key at
  the *same* instant — a claim stampede on one hot step. Real agents usually claim
  *different* steps (different keys), which don't contend at all and stay at the base RTT
  regardless of N. The elbow applies to stampedes, not to all parallel coordination.
- **At N≥16 the attribution isn't clean.** Our own simultaneity metric (how tightly the
  barrier released the threads) itself grows with N and correlates with latency strongly
  (Pearson r ≥ 0.8 at high N). So at the top of the curve we cannot perfectly separate
  "the store queued" from "our threads didn't fire together." We say so on the chart and
  rely on the staggered control to carry the causal claim. The excess is labeled
  "simultaneity-coupled," not "server contention," for this reason.
- **Absolute ms are a lower bound.** This is localhost MinIO over loopback, which removes
  WAN latency. Real S3 over a network widens the in-flight window (which would only make
  HF's race easier to hit). The *shape* of the response and the invariant result are the
  claim — not portable absolute latency, and not a prediction of distributed-S3 behavior.
- **HF is not an apples-to-apples latency comparison.** It's a WAN git-commit (~1.4s), 10
  trials/N, with no rejection path. It's there only to show the harness detects breakage.

## Run the harness's own tests

```bash
pytest benchmarks/test_contention_bench.py -v
```

Seven tests prove the harness counts honestly: a synthetic atomic race holds the invariant,
a synthetic check-then-write backend produces duplicate wins, a `PreconditionFailed` is a
loss not an error, an unexpected exception invalidates a trial, the per-claim timeline is
consistent with the headline latency, and the summary is a pure function of the raw log.
```
