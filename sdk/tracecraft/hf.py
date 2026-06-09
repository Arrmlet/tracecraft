"""HuggingFace Buckets backend — same interface as s3.py, uses HfFileSystem."""

import json

import click

from tracecraft.config import load_config


class HF:
    def __init__(self, bucket, project, token=None, private=True):
        from huggingface_hub import HfFileSystem

        self.fs = HfFileSystem(token=token)
        self.bucket = bucket  # e.g. "username/my-bucket"
        self.project = project
        self.token = token
        self.private = private  # safe default: private (these hold internal traces)
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

    def _raise_write_error(self, e):
        """Translate raw HfFileSystem write errors into actionable ones.

        A put against a bucket that doesn't exist surfaces as a cryptic
        'repository and revision' / 404 resolution error from HfFileSystem —
        name the bucket and say what to do instead.
        """
        msg = str(e)
        if isinstance(e, FileNotFoundError) or (
            "Repository Not Found" in msg or "repository and revision" in msg or "404" in msg
        ):
            raise click.ClickException(
                f"HF write failed: bucket '{self.bucket}' was not found.\n"
                f"Run `tracecraft init --backend hf --bucket {self.bucket} ...` to create it, "
                f"and check the bucket handle is 'username/bucket-name'."
            )
        raise click.ClickException(f"HF write failed: {e}")

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
            self._raise_write_error(e)

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
            self._raise_write_error(e)

    def get_file(self, key, local_path):
        try:
            self.fs.get(self._path(key), local_path)
        except Exception as e:
            raise click.ClickException(f"HF download failed: {e}")

    def ensure_bucket(self):
        """Create the HF bucket if it doesn't exist (private by default).

        Previously a no-op, which made `init` against a brand-new bucket fail with a
        cryptic error on the first write (issue #7). HF buckets default to *public*
        on creation, which is a privacy footgun for a tool that stores internal
        memory/transcripts (issue #8) — so we create them private unless the caller
        opts out via `private=False`.
        """
        try:
            from huggingface_hub import HfApi

            HfApi(token=self.token).create_bucket(self.bucket, private=self.private, exist_ok=True)
        except Exception as e:
            # Fall back to the old behavior: let the first write validate access,
            # but surface a useful hint instead of a cryptic one.
            raise click.ClickException(
                f"Could not ensure HF bucket '{self.bucket}' exists: {e}\n"
                f"Create it first at https://huggingface.co/new-bucket (set it Private), "
                f"or check your --hf-token has write access."
            )

    def bucket_privacy(self):
        """Return the bucket's *actual* visibility: True=private, False=public,
        None if it can't be determined (network error, no permission).

        Read back from bucket_info() rather than assumed from the flag we passed —
        create_bucket(exist_ok=True) silently keeps a pre-existing bucket's
        visibility, so the flag and reality can disagree.
        """
        try:
            from huggingface_hub import HfApi

            return bool(HfApi(token=self.token).bucket_info(self.bucket).private)
        except Exception:
            return None
