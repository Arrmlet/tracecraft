"""Unit tests for the contention benchmark's OWN counting + invariant logic.

This is the one place a mock is allowed: we are testing that the harness counts
honestly (a synthetic duplicate-win is detected, a clean race passes, an unexpected
exception invalidates a trial) — NOT measuring contention. No reported benchmark
number ever comes from a mock; those come only from the real-backend sweep.

Run: pytest benchmarks/test_contention_bench.py -v
"""

from __future__ import annotations

import json

import pytest

import contention_bench as cb


class FakeStore:
    """In-memory stand-in for the shipped S3/HF backend.

    `mode` controls the arbitration we want to simulate:
      - "atomic": exactly one put_json(if_none_match=True) succeeds; the rest raise
        PreconditionFailed. Models S3/MinIO.
      - "racy": every put succeeds and the LAST writer's value is what's stored.
        Models HF check-then-write (everyone "wins", the object keeps one).
    """

    _shared: dict = {}

    def __init__(self, mode, registry):
        self.mode = mode
        self.registry = registry  # shared dict: key -> stored doc

    def get_json(self, key):
        return self.registry.get(key)

    def put_json(self, key, data, if_none_match=False):
        if if_none_match and self.mode == "atomic":
            # First writer wins; everyone after raises.
            if key in self.registry:
                raise cb.PreconditionFailed(key)
            self.registry[key] = data
            return
        # racy (or unconditional): always write, last writer's value persists
        self.registry[key] = data

    def delete(self, key):
        self.registry.pop(key, None)

    def ensure_bucket(self):
        pass


def _backend(mode):
    registry: dict = {}
    return cb.Backend(
        make_store=lambda: FakeStore(mode, registry),
        project="test",
        backend_name="fake",
    )


def test_atomic_race_holds_invariant():
    """One winner, stored owner matches, no duplicate wins."""
    tr = cb.run_trial(_backend("atomic"), n=8, warm=False)
    assert tr.valid
    assert tr.outcomes.count(cb.WIN) == 1
    assert tr.outcomes.count(cb.LOST) == 7
    assert tr.declared_winner is not None
    assert tr.stored_owner == tr.declared_winner
    assert tr.duplicate_wins == 0
    assert tr.invariant_held is True


def test_claims_timeline_matches_headline_latency():
    """The per-claim timeline must not silently disagree with the proven latency:
    decision_ms - arrival_ms == latency_ms for every claim, and the WIN claim's
    latency is the one reported in win_latency_ms. This guards the new --timeline
    field against drifting from the number the rest of the report trusts."""
    tr = cb.run_trial(_backend("atomic"), n=8, warm=False)
    assert len(tr.claims) == 8
    for c in tr.claims:
        # service time reconstructed from the timeline equals the recorded latency
        assert abs((c["decision_ms"] - c["arrival_ms"]) - c["latency_ms"]) < 0.01
    win_claims = [c for c in tr.claims if c["outcome"] == cb.WIN]
    assert len(win_claims) == 1
    assert abs(win_claims[0]["latency_ms"] - tr.win_latency_ms[0]) < 0.01


def test_racy_backend_produces_duplicate_wins():
    """Check-then-write: everyone 'wins', the object keeps one -> duplicate_wins>0,
    invariant broken. This is the HF failure mode the benchmark must catch."""
    tr = cb.run_trial(_backend("racy"), n=4, warm=False)
    assert tr.valid  # not an error — a real (broken) outcome
    assert tr.outcomes.count(cb.WIN) == 4  # all four believed they won
    assert tr.duplicate_wins == 3
    assert tr.invariant_held is False
    # the stored owner is exactly one of the four claimants
    assert tr.stored_owner in {f"agent-{i}" for i in range(4)}


def test_precondition_failed_is_loss_not_error():
    """A LOST outcome never invalidates a trial and is never a duplicate."""
    tr = cb.run_trial(_backend("atomic"), n=2, warm=False)
    assert tr.valid
    assert tr.invalid_reason is None
    assert cb.INVALID not in tr.outcomes


def test_unexpected_exception_invalidates_trial():
    """Anything outside {WIN, PreconditionFailed} marks the trial INVALID and is
    reported separately — never laundered into a win or a loss."""

    class BoomStore(FakeStore):
        def put_json(self, key, data, if_none_match=False):
            raise RuntimeError("503 from the object store")

    registry: dict = {}
    backend = cb.Backend(
        make_store=lambda: BoomStore("atomic", registry),
        project="test",
        backend_name="fake",
    )
    tr = cb.run_trial(backend, n=3, warm=False)
    assert tr.valid is False
    assert tr.invalid_reason is not None
    assert "RuntimeError" in tr.invalid_reason


def test_summary_is_pure_function_of_jsonl(tmp_path):
    """The printed summary must be regenerable from the raw log alone."""
    log = tmp_path / "raw.jsonl"
    rows = [
        {
            "backend": "s3",
            "endpoint": "http://x",
            "tracecraft_commit": "abc",
            "boto3": "1.42.73",
            "host": "h",
            "n": 2,
            "trial": i,
            "outcomes": {"WIN": 1, "LOST": 1},
            "win_latency_ms": [5.0],
            "lost_latency_ms": [10.0],
            "barrier_fire_spread_ms": 1.0,
            "excluded_low_concurrency": False,
            "stored_owner": "agent-0",
            "declared_winner": "agent-0",
            "invariant_held": True,
            "duplicate_wins": 0,
            "valid": True,
            "invalid_reason": None,
            "warm": True,
        }
        for i in range(5)
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    # Should not raise and should treat all 5 as valid, invariant-holding.
    cb.summarize(str(log))  # smoke: pure function, no state needed


def test_percentile_helper():
    assert cb._pct([], 50) is None
    assert cb._pct([10], 50) == 10
    xs = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert cb._pct(xs, 50) == pytest.approx(5.5, abs=0.6)
    assert cb._pct(xs, 99) == pytest.approx(10, abs=0.5)
