"""Storage backend factory — returns S3 or HF based on config."""

from tracecraft.config import load_config


def get_store():
    """Load config and return the right storage backend."""
    cfg = load_config()
    backend = cfg.get("backend", "s3")

    if backend == "hf":
        from tracecraft.hf import HF
        return HF(bucket=cfg["bucket"], project=cfg["project"], token=cfg.get("hf_token")), cfg
    else:
        from tracecraft.s3 import S3
        return S3(
            endpoint=cfg["endpoint"],
            bucket=cfg["bucket"],
            project=cfg["project"],
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
        ), cfg
