#!/usr/bin/env python3
"""Build the self-contained HTML contention report from the raw JSONL logs.

Every number in the report is computed HERE, in Python, from the raw per-trial
logs — reusing the benchmark's own ``_pct`` so the report can never disagree with
``contention_bench.py --summarize``. The browser only maps precomputed arrays to
hand-drawn SVG; it recomputes nothing. There is zero hardcoded aggregate: if the
logs change, re-running this regenerates every figure.

Inputs (read from benchmarks/ next to this file; missing files degrade gracefully):
  results_s3.jsonl        simultaneous sweep — the latency curve + invariant
  results_stagger.jsonl   staggered control — the falsification arm
  results_timeline.jsonl  per-claim timeline (--timeline) — the queue picture
  results_hf.jsonl        HuggingFace — the correctness/breakage control

Output: benchmarks/contention_report.html (opens offline by double-click).

Run: python benchmarks/build_report.py
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

from contention_bench import _pct  # reuse the EXACT percentile the summary uses

HERE = Path(__file__).resolve().parent
PCTS = [5, 25, 50, 75, 95, 99]


def load(name):
    p = HERE / name
    if not p.exists() or p.stat().st_size == 0:
        return []
    return [json.loads(ln) for ln in p.read_text().splitlines() if ln.strip()]


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return round(num / (dx * dy), 3) if dx and dy else None


def percentile_block(xs):
    return {f"p{p}": _pct(xs, p) for p in PCTS}


def by_n(rows):
    out: dict[int, list] = {}
    for r in rows:
        out.setdefault(r["n"], []).append(r)
    return out


def cdf(xs, max_points=120):
    """Empirical CDF as (value, fraction) points, thinned for SVG."""
    if not xs:
        return []
    xs = sorted(xs)
    n = len(xs)
    if n <= max_points:
        return [[round(x, 3), (i + 1) / n] for i, x in enumerate(xs)]
    step = n / max_points
    pts = []
    for k in range(max_points):
        i = min(int((k + 1) * step) - 1, n - 1)
        pts.append([round(xs[i], 3), (i + 1) / n])
    return pts


def summarize_sweep(rows, simultaneous=True):
    """Per-N aggregates for a sweep. Reads exclusions/validity from the data."""
    grp = by_n(rows)
    out = []
    for n in sorted(grp):
        rs = grp[n]
        excluded = sum(1 for r in rs if r.get("excluded_low_concurrency"))
        counted = [r for r in rs if not r.get("excluded_low_concurrency")]
        valid = [r for r in counted if r.get("valid", True)]
        win = [x for r in valid for x in r["win_latency_ms"]]
        lost = [x for r in valid for x in r["lost_latency_ms"]]
        spreads = [r["barrier_fire_spread_ms"] for r in valid]
        held = sum(1 for r in valid if r["invariant_held"])
        dup = sum(r["duplicate_wins"] for r in valid)
        # within-N confound: per-trial spread vs that trial's mean win latency
        pair = [
            (r["barrier_fire_spread_ms"], statistics.mean(r["win_latency_ms"]))
            for r in valid
            if r["win_latency_ms"]
        ]
        r_spread_lat = pearson([p[0] for p in pair], [p[1] for p in pair])
        out.append(
            {
                "n": n,
                "trials": len(rs),
                "valid": len(valid),
                "excluded": excluded,
                "invariant_held": held,
                "duplicate_wins": dup,
                "win": percentile_block(win),
                "lost": percentile_block(lost),
                "spread_p50": _pct(spreads, 50),
                "spread_max": round(max(spreads), 2) if spreads else None,
                "r_spread_latency": r_spread_lat,
                "win_cdf": cdf(win),
                # per-trial mean win latency vs spread (for the confound scatter)
                "scatter": [[round(s, 3), round(m, 3)] for s, m in pair],
            }
        )
    return out


def pick_timeline_exemplars(rows):
    """One median-spread exemplar trial per N, with its raw claims[]."""
    grp = by_n(rows)
    out = {}
    for n in sorted(grp):
        valid = [
            r
            for r in grp[n]
            if r.get("valid", True)
            and not r.get("excluded_low_concurrency")
            and r.get("claims")
        ]
        if not valid:
            continue
        valid.sort(key=lambda r: r["barrier_fire_spread_ms"])
        exemplar = valid[len(valid) // 2]  # median spread
        claims = sorted(exemplar["claims"], key=lambda c: c["arrival_ms"])
        arrivals = [c["arrival_ms"] for c in claims]
        decisions = [c["decision_ms"] for c in claims]
        out[n] = {
            "n": n,
            "sid": exemplar["sid"],
            "spread_ms": round(exemplar["barrier_fire_spread_ms"], 3),
            "claims": claims,
            # the discriminating quantity the adversary asked for:
            # does the decision fan-out EXCEED the arrival fan-out?
            "arrival_spread_ms": round(max(arrivals) - min(arrivals), 3),
            "decision_spread_ms": round(max(decisions) - min(decisions), 3),
        }
    return out


def provenance(rows):
    if not rows:
        return {}
    r = rows[0]
    return {
        "backend": r.get("backend"),
        "endpoint": r.get("endpoint"),
        "commit": r.get("tracecraft_commit"),
        "boto3": r.get("boto3"),
        "host": r.get("host"),
        "platform": r.get("platform"),
        "python": r.get("python"),
    }


def messaging_block(rows):
    """Old-vs-new message delivery under a concurrent burst (no aggregation needed —
    the harness already counted delivered-vs-sent against the durable bucket)."""
    out = {}
    for r in rows:
        out[r["scheme"]] = {
            "sent": r["sent"],
            "delivered": r["distinct_messages"],
            "lost": r["lost"],
            "senders": r["senders"],
            "per_sender": r["per_sender"],
        }
    return out


def build_data():
    s3 = load("results_s3.jsonl")
    stagger = load("results_stagger.jsonl")
    timeline = load("results_timeline.jsonl")
    hf = load("results_hf.jsonl")
    messaging = load("results_messaging.jsonl")

    s3_sweep = summarize_sweep(s3)
    stagger_sweep = summarize_sweep(stagger)
    hf_sweep = summarize_sweep(hf)

    total_valid = sum(s["valid"] for s in s3_sweep)
    total_breaks = sum(s["valid"] - s["invariant_held"] for s in s3_sweep)
    total_dup = sum(s["duplicate_wins"] for s in s3_sweep)
    base_rtt = s3_sweep[0]["win"]["p50"] if s3_sweep else None

    return {
        "s3": s3_sweep,
        "stagger": stagger_sweep,
        "stagger_gap_ms": (stagger[0].get("stagger_ms") if stagger else None),
        "hf": hf_sweep,
        "timeline": pick_timeline_exemplars(timeline),
        "messaging": messaging_block(messaging),
        "totals": {
            "s3_valid": total_valid,
            "s3_invariant_breaks": total_breaks,
            "s3_duplicate_wins": total_dup,
            "base_rtt_ms": base_rtt,
            "hf_valid": sum(s["valid"] for s in hf_sweep),
            "hf_breaks": sum(s["valid"] - s["invariant_held"] for s in hf_sweep),
            "hf_dup": sum(s["duplicate_wins"] for s in hf_sweep),
        },
        "provenance": provenance(s3),
        "hf_provenance": provenance(hf),
    }


def main():
    data = build_data()
    html = HTML_TEMPLATE.replace(
        "/*__DATA__*/", json.dumps(data, separators=(",", ":"))
    )
    out = HERE / "contention_report.html"
    out.write_text(html)
    t = data["totals"]
    print(f"wrote {out}")
    print(
        f"  S3: {t['s3_valid']} valid trials, {t['s3_invariant_breaks']} invariant "
        f"breaks, {t['s3_duplicate_wins']} duplicate wins, base RTT ~{t['base_rtt_ms']}ms"
    )
    print(
        f"  HF: {t['hf_valid']} valid trials, {t['hf_breaks']} breaks, "
        f"{t['hf_dup']} duplicate wins"
    )
    print(f"  timeline exemplars: N={sorted(data['timeline'].keys())}")
    msg = data.get("messaging") or {}
    if msg:
        for scheme, m in msg.items():
            print(
                f"  messaging[{scheme}]: {m['delivered']}/{m['sent']} delivered, "
                f"{m['lost']} lost"
            )


# The HTML template lives in a separate module-level string so build logic stays
# readable. It is pure markup + inline SVG-drawing JS; all numbers arrive via the
# spliced JSON blob (no hardcoded aggregates, no network at view time).
from report_template import HTML_TEMPLATE  # noqa: E402


if __name__ == "__main__":
    main()
