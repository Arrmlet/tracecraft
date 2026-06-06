"""HuggingFace Buckets backend — same interface as s3.py, uses HfFileSystem."""

import json

import click

from tracecraft.config import load_config


class HF:
    def __init__(self, bucket, project, token=None):
        from huggingface_hub import HfFileSystem

        self.fs = HfFileSystem(token=token)
        self.bucket = bucket  # e.g. "username/my-bucket"
        self.project = project
        self.base = f"hf://buckets/{bucket}"

    @classmethod
    def from_config(cls):
        cfg = load_config()
        return cls(
            bucket=cfg["bucket"],
            project=cfg["project"],
            token=cfg.get("hf_token"),
        )

    def _path(self, key):
        return f"{self.base}/{self.project}/{key}"

    def put_json(self, key, data, if_none_match=False):
        try:
            path = self._path(key)
            if if_none_match:
                # HfFileSystem has no native conditional PUT — best-effort check-then-write.
                # This is racy, but documented; S3-compatible backends use IfNoneMatch=* for safety.
                if self.fs.exists(path):
                    from tracecraft.s3 import PreconditionFailed

                    raise PreconditionFailed(key)
            with self.fs.open(path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            from tracecraft.s3 import PreconditionFailed

            if isinstance(e, PreconditionFailed):
                raise
            raise click.ClickException(f"HF put failed: {e}")

    def get_json(self, key):
        try:
            path = self._path(key)
            if not self.fs.exists(path):
                return None
            with self.fs.open(path, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as e:
            raise click.ClickException(f"HF get failed: {e}")

    def list_keys(self, prefix=""):
        try:
            path = self._path(prefix)
            # find() is recursive and matches S3 list semantics
            entries = self.fs.find(path, detail=False) if self.fs.exists(path) else []
            base_prefix = f"buckets/{self.bucket}/{self.project}/"
            keys = []
            for entry in entries:
                if entry.startswith(base_prefix):
                    keys.append(entry[len(base_prefix) :])
                else:
                    keys.append(entry)
            return keys
        except FileNotFoundError:
            return []
        except Exception as e:
            raise click.ClickException(f"HF list failed: {e}")

    def exists(self, key):
        try:
            return self.fs.exists(self._path(key))
        except Exception:
            return False

    def delete(self, key):
        try:
            self.fs.rm(self._path(key))
        except FileNotFoundError:
            pass
        except Exception as e:
            raise click.ClickException(f"HF delete failed: {e}")

    def put_file(self, key, local_path):
        try:
            self.fs.put(local_path, self._path(key))
        except Exception as e:
            raise click.ClickException(f"HF upload failed: {e}")

    def get_file(self, key, local_path):
        try:
            self.fs.get(self._path(key), local_path)
        except Exception as e:
            raise click.ClickException(f"HF download failed: {e}")

    def ensure_bucket(self):
        # HF buckets are created via CLI or web — verify by checking exists or listing
        # Empty buckets fail on ls(), so we just pass and let first write validate access
        pass
