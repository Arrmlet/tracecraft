"""Tests for the HF onboarding + correctness-honesty fixes.

Covers three real, externally-reported issues:
  - #7: `init --backend hf` against a non-existent bucket must auto-create it
        (HF ensure_bucket() was a no-op; first write failed cryptically).
  - #8: HF buckets are public-by-default; init must create them PRIVATE by default,
        with an explicit --public opt-out.
  - correctness honesty: claims on HF are best-effort (no conditional-write), so both
        `init --backend hf` and `claim` must SAY SO rather than imply atomicity.

These mock the HuggingFace SDK (no network) — they verify the wiring (private flag
reaches create_bucket; the warnings are emitted), not HF's servers.
"""

from __future__ import annotations

import json
import sys
import types

import click
import pytest
from click.testing import CliRunner

from tracecraft.cli.init_cmd import init_cmd
from tracecraft.cli.steps import claim


class FakeBucketState:
    """Records create_bucket calls and stores written JSON in-memory."""

    def __init__(self):
        self.create_calls = []  # list of (bucket, private, exist_ok)
        self.objects = {}  # path -> data
        self.buckets = {}  # bucket_id -> private (bool); pre-seed to simulate existing


@pytest.fixture
def hf_stub(monkeypatch):
    """Stub huggingface_hub so init/claim run against an in-memory fake HF backend."""
    state = FakeBucketState()

    # --- fake huggingface_hub module surface used by tracecraft.hf ---
    class FakeApi:
        """Mimics HfApi: create_bucket(exist_ok=True) never changes an existing
        bucket's visibility; bucket_info returns the actual state."""

        def __init__(self, token=None):
            self.token = token

        def create_bucket(self, bucket_id, *, private=None, exist_ok=False, **kw):
            state.create_calls.append((bucket_id, private, exist_ok))
            if bucket_id in state.buckets:
                if not exist_ok:
                    raise ValueError(f"Bucket {bucket_id} already exists")
            else:
                state.buckets[bucket_id] = bool(private)
            return f"hf://buckets/{bucket_id}"

        def bucket_info(self, bucket_id, **kw):
            if bucket_id not in state.buckets:
                raise FileNotFoundError(bucket_id)
            return types.SimpleNamespace(private=state.buckets[bucket_id])

    class FakeFS:
        def __init__(self, *a, **k):
            pass

        def exists(self, path):
            return path in state.objects

        def open(self, path, mode="r"):
            store = state.objects

            class _F:
                def __enter__(self_):
                    if "r" in mode:
                        self_._buf = store.get(path, "")
                    return self_

                def __exit__(self_, *exc):
                    return False

                def write(self_, s):
                    store[path] = store.get(path, "") + s

                def read(self_):
                    return self_._buf

            return _F()

        def find(self, path, detail=False):
            return [p for p in state.objects if p.startswith(path)]

    fake_hf = types.ModuleType("huggingface_hub")
    fake_hf.HfFileSystem = FakeFS
    fake_hf.HfApi = FakeApi
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)
    return state


def _init(runner, tmp_path, monkeypatch, *extra):
    monkeypatch.chdir(tmp_path)
    args = [
        "--backend",
        "hf",
        "--bucket",
        "user/tc-test",
        "--project",
        "demo",
        "--agent",
        "tester",
        "--hf-token",
        "hf_faketoken",
        *extra,
    ]
    return runner.invoke(init_cmd, args)


# ---------- #7: auto-create ----------


def test_init_hf_creates_bucket(hf_stub, tmp_path, monkeypatch):
    r = _init(CliRunner(), tmp_path, monkeypatch)
    assert r.exit_code == 0, r.output
    # ensure_bucket() actually called create_bucket (was a no-op before)
    assert len(hf_stub.create_calls) == 1
    bucket, private, exist_ok = hf_stub.create_calls[0]
    assert bucket == "user/tc-test"
    assert exist_ok is True  # idempotent: don't fail if it already exists
    # the agent record was written (the first write that used to fail cryptically)
    assert any("agents/tester.json" in p for p in hf_stub.objects)


# ---------- #8: private by default, --public opt-out ----------


def test_init_hf_private_by_default(hf_stub, tmp_path, monkeypatch):
    r = _init(CliRunner(), tmp_path, monkeypatch)
    assert r.exit_code == 0, r.output
    _, private, _ = hf_stub.create_calls[0]
    assert private is True
    assert "(private)" in r.output


def test_init_hf_public_when_asked(hf_stub, tmp_path, monkeypatch):
    r = _init(CliRunner(), tmp_path, monkeypatch, "--public")
    assert r.exit_code == 0, r.output
    _, private, _ = hf_stub.create_calls[0]
    assert private is False
    assert "(PUBLIC)" in r.output


# ---------- correctness honesty ----------


def test_init_hf_warns_claims_are_best_effort(hf_stub, tmp_path, monkeypatch):
    r = _init(CliRunner(), tmp_path, monkeypatch)
    assert r.exit_code == 0, r.output
    # the racy-claim caveat must be surfaced at init (output includes stderr via CliRunner)
    assert "best-effort" in r.output.lower()
    assert "S3-compatible" in r.output


def test_claim_on_hf_warns_best_effort(hf_stub, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # write an hf config the CWD-first loader will pick up
    cfg = {
        "backend": "hf",
        "bucket": "user/tc-test",
        "project": "demo",
        "agent_id": "tester",
        "hf_token": "hf_faketoken",
    }
    (tmp_path / ".tracecraft.json").write_text(json.dumps(cfg))
    r = CliRunner().invoke(claim, ["build"])
    assert r.exit_code == 0, r.output
    assert "Claimed step build" in r.output
    assert "best-effort" in r.output.lower()


# ---------- #8: pre-existing PUBLIC bucket triggers a prominent warning ----------


def test_init_hf_existing_public_bucket_warns(hf_stub, tmp_path, monkeypatch):
    """Bucket pre-exists as public; user asked for private (default) — init must
    say the data will be publicly visible and that delete+recreate is the only fix."""
    hf_stub.buckets["user/tc-test"] = False  # exists, public
    r = _init(CliRunner(), tmp_path, monkeypatch)
    assert r.exit_code == 0, r.output
    assert "(PUBLIC)" in r.output  # real state, not the requested flag
    assert "WARNING" in r.output
    assert "publicly visible" in r.output
    assert "delete" in r.output.lower()


def test_init_hf_existing_public_bucket_no_warning_with_public_flag(hf_stub, tmp_path, monkeypatch):
    hf_stub.buckets["user/tc-test"] = False
    r = _init(CliRunner(), tmp_path, monkeypatch, "--public")
    assert r.exit_code == 0, r.output
    assert "WARNING" not in r.output


# ---------- write errors name the bucket and point at init ----------


def test_put_against_missing_bucket_is_actionable(hf_stub, monkeypatch):
    from tracecraft.hf import HF

    store = HF(bucket="user/tc-test", project="demo", token="hf_faketoken")

    def boom(*a, **k):
        raise OSError("unable to resolve path: invalid repository and revision")

    monkeypatch.setattr(store.fs, "open", boom)
    with pytest.raises(click.ClickException) as ei:
        store.put_json("memory/x.json", {"v": 1})
    msg = str(ei.value)
    assert "user/tc-test" in msg
    assert "tracecraft init" in msg
    assert "repository and revision" not in msg  # raw error replaced, not echoed


# ---------- exists(): not-found is False, unauthorized raises ----------


def test_exists_not_found_is_false(hf_stub, monkeypatch):
    from tracecraft.hf import HF

    store = HF(bucket="user/tc-test", project="demo", token="hf_faketoken")
    monkeypatch.setattr(store.fs, "exists", lambda p: (_ for _ in ()).throw(FileNotFoundError(p)))
    assert store.exists("memory/x.json") is False


def test_exists_surfaces_auth_errors(hf_stub, monkeypatch):
    from tracecraft.hf import HF

    store = HF(bucket="user/tc-test", project="demo", token="hf_badtoken")

    def boom(path):
        e = Exception("401 Client Error: Unauthorized for url")
        e.response = types.SimpleNamespace(status_code=401)
        raise e

    monkeypatch.setattr(store.fs, "exists", boom)
    with pytest.raises(click.ClickException) as ei:
        store.exists("memory/x.json")
    msg = str(ei.value)
    assert "auth" in msg.lower()
    assert "HF_TOKEN" in msg
