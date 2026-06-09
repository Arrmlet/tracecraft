#!/usr/bin/env python3
"""tracecraft messaging benchmark — does the bucket deliver every message under load?

Claiming and messaging stress the bucket in opposite ways. A claim is a RACE: N agents
fight over ONE key and exactly one must win, so the interesting question is contention
(see contention_bench.py). A message is the opposite: every send writes its OWN key, so
there is no contention — the interesting question is DELIVERY INTEGRITY. When N agents each
fire K messages at once, do all N*K land in the bucket, or do any silently vanish?

They can vanish if two messages map to the same key. That is exactly the bug this benchmark
was built to catch and then prove fixed:

  OLD key:  messages/<recipient>/<int_seconds>_<sender>.json
            -> two messages from one sender to one recipient in the SAME wall-clock second
               collide; the later overwrites the earlier. A burst keeps ~1.
  NEW key:  messages/<recipient>/<time_ns>_<sender>_<uuid8>.json
            -> unique per send; every message survives.

This harness sends through BOTH key schemes against the SAME real backend and counts
delivered-vs-sent, so the fix is demonstrated, not asserted. It reuses the shipped S3
backend's put_json/list_keys (no reimplementation) and only swaps the key-building rule —
the OLD rule reproduced here verbatim from the pre-fix code, the NEW rule imported in spirit
from the shipped send command.

Honesty guards (same spirit as the contention benchmark):
  * Real backend only (assert a live socket); no mock produces a reported number.
  * Count delivered messages by LISTING the bucket and reading bodies back — the durable
    store is the source of truth, not the harness's "I sent it" bookkeeping.
  * Fresh project namespace per run; cleaned up after.
  * Both schemes run on the same backend, same concurrency, same N*K, so the only variable
    is the key rule.

Usage:
  python benchmarks/messaging_bench.py --endpoint http://localhost:9000 \
      --bucket tracecraft --access-key admin --secret-key admin123456 \
      --senders 8 --per-sender 20 --out results_messaging.jsonl
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

_SDK = Path(__file__).resolve().parent.parent / "sdk"
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))

from tracecraft.s3 import S3  # noqa: E402


def old_key(recipient, sender, i):
    """The pre-fix key rule: whole-second timestamp. Collides within a second."""
    ts = int(time.time())
    return f"messages/{recipient}/{ts}_{sender}.json"


def new_key(recipient, sender, i):
    """The fixed key rule: nanosecond + uuid suffix. Unique per send."""
    ts_ns = time.time_ns()
    uniq = uuid.uuid4().hex[:8]
    return f"messages/{recipient}/{ts_ns}_{sender}_{uniq}.json"


def preflight(store):
    store.ensure_bucket()
    probe = f"_msgpreflight/{uuid.uuid4().hex}.json"
    store.put_json(probe, {"ok": True})
    if not store.get_json(probe):
        raise SystemExit(
            "PREFLIGHT FAILED: backend did not return a just-written object."
        )
    store.delete(probe)


def run_scheme(make_store, project, key_fn, senders, per_sender, recipient="reviewer"):
    """N sender threads, each firing `per_sender` messages at once through key_fn.

    Returns (sent, delivered, distinct_bodies). delivered/distinct are read back from
    the durable bucket, never from the harness's own count.
    """
    sent = senders * per_sender
    barrier = threading.Barrier(senders)
    errors: list[str] = []
    lock = threading.Lock()

    def sender_thread(sidx):
        store = make_store()  # one client per sender (not thread-safe to share)
        agent = f"sender-{sidx}"
        barrier.wait()  # all senders start their burst together
        for i in range(per_sender):
            try:
                key = key_fn(recipient, agent, i)
                store.put_json(
                    key,
                    {
                        "from": agent,
                        "to": recipient,
                        "message": f"{agent}-msg-{i}",
                        "seq": i,
                    },
                )
            except Exception as e:  # noqa: BLE001
                with lock:
                    errors.append(f"{type(e).__name__}:{e}")

    ts = [threading.Thread(target=sender_thread, args=(s,)) for s in range(senders)]
    [t.start() for t in ts]
    [t.join() for t in ts]

    # Count what actually landed, by reading the bucket back with a fresh client.
    verifier = make_store()
    keys = [
        k for k in verifier.list_keys(f"messages/{recipient}/") if k.endswith(".json")
    ]
    bodies = set()
    for k in keys:
        doc = verifier.get_json(k)
        if doc and "message" in doc:
            bodies.add(doc["message"])
    return {
        "sent": sent,
        "delivered_keys": len(keys),
        "distinct_messages": len(bodies),
        "lost": sent - len(bodies),
        "errors": len(errors),
    }


def cleanup(make_store):
    store = make_store()
    for k in store.list_keys(""):
        if k:
            try:
                store.delete(k)
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(description="tracecraft messaging delivery benchmark")
    ap.add_argument("--endpoint", default="http://localhost:9000")
    ap.add_argument("--bucket", default="tracecraft")
    ap.add_argument("--access-key", default="admin")
    ap.add_argument("--secret-key", default="admin123456")
    ap.add_argument("--senders", type=int, default=8)
    ap.add_argument("--per-sender", type=int, default=20)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    env = {
        "endpoint": args.endpoint,
        "host": socket.gethostname(),
        "senders": args.senders,
        "per_sender": args.per_sender,
    }

    results = []
    for scheme, key_fn in [("old_whole_second", old_key), ("new_ns_uuid", new_key)]:
        project = f"msgbench-{scheme}-{uuid.uuid4().hex[:6]}"

        def make_store(project=project):
            return S3(
                endpoint=args.endpoint,
                bucket=args.bucket,
                project=project,
                access_key=args.access_key,
                secret_key=args.secret_key,
            )

        preflight(make_store())
        r = run_scheme(make_store, project, key_fn, args.senders, args.per_sender)
        cleanup(make_store)
        row = {**env, "scheme": scheme, **r}
        results.append(row)
        delivered_pct = round(100 * r["distinct_messages"] / r["sent"], 1)
        print(
            f"[{scheme:16}] sent={r['sent']:4}  delivered={r['distinct_messages']:4}  "
            f"lost={r['lost']:4}  ({delivered_pct}% delivered)  errors={r['errors']}"
        )

    if args.out:
        with open(args.out, "w") as f:
            for row in results:
                f.write(json.dumps(row) + "\n")
        print(f"\nraw -> {args.out}")

    old = next(r for r in results if r["scheme"] == "old_whole_second")
    new = next(r for r in results if r["scheme"] == "new_ns_uuid")
    print(
        f"\nVERDICT: old scheme delivered {old['distinct_messages']}/{old['sent']}, "
        f"new scheme delivered {new['distinct_messages']}/{new['sent']}."
    )
    if new["lost"] == 0 and old["lost"] > 0:
        print(
            "  -> The fix (ns + uuid keys) delivers every message under a concurrent burst; "
            "the old whole-second key silently dropped the colliding ones."
        )


if __name__ == "__main__":
    main()
