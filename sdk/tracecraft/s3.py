"""Minimal boto3 wrapper with project-scoped keys."""

import json

import boto3
import click
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from tracecraft.config import load_config


class PreconditionFailed(Exception):
    """Raised when an atomic put with If-None-Match=* finds an existing object."""

    def __init__(self, key):
        super().__init__(f"object exists: {key}")
        self.key = key


class S3:
    def __init__(self, endpoint, bucket, project, access_key, secret_key):
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=BotoConfig(s3={"addressing_style": "path"}),
        )
        self.bucket = bucket
        self.project = project

    @classmethod
    def from_config(cls):
        cfg = load_config()
        return cls(
            endpoint=cfg["endpoint"],
            bucket=cfg["bucket"],
            project=cfg["project"],
            access_key=cfg["access_key"],
            secret_key=cfg["secret_key"],
        )

    def _key(self, key):
        return f"{self.project}/{key}"

    def put_json(self, key, data, if_none_match=False):
        kwargs = dict(
            Bucket=self.bucket,
            Key=self._key(key),
            Body=json.dumps(data, indent=2),
            ContentType="application/json",
        )
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        try:
            self.client.put_object(**kwargs)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if if_none_match and code in ("PreconditionFailed", "ConditionalRequestConflict"):
                raise PreconditionFailed(key) from e
            raise click.ClickException(f"S3 put failed: {e}")

    def get_json(self, key):
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            return json.loads(resp["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise click.ClickException(f"S3 get failed: {e}")

    def list_keys(self, prefix="", detail=False, start_after=None):
        """List keys under prefix, in lexicographic order (S3 native order).

        detail=True returns dicts {key, size, last_modified} instead of strings.
        start_after skips everything <= that key server-side (ListObjectsV2
        StartAfter) — the cheap primitive behind incremental reads like
        `inbox --new`. Both take project-relative keys.
        """
        try:
            full_prefix = self._key(prefix)
            kwargs = {"Bucket": self.bucket, "Prefix": full_prefix}
            if start_after:
                kwargs["StartAfter"] = self._key(start_after)
            results = []
            paginator = self.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(**kwargs):
                for obj in page.get("Contents", []):
                    stripped = obj["Key"][len(self.project) + 1 :]
                    if detail:
                        lm = obj.get("LastModified")
                        results.append(
                            {
                                "key": stripped,
                                "size": obj.get("Size", 0),
                                "last_modified": lm.isoformat() if lm else None,
                            }
                        )
                    else:
                        results.append(stripped)
            return results
        except ClientError as e:
            raise click.ClickException(f"S3 list failed: {e}")

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError as e:
            # "Not found" is a legitimate False; "access denied" is not —
            # swallowing it makes bad credentials look like an empty bucket.
            # (head_object reports errors by HTTP status, often without a
            # descriptive Code, so check both.)
            code = e.response.get("Error", {}).get("Code", "")
            status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status in (401, 403) or code in (
                "401",
                "403",
                "AccessDenied",
                "InvalidAccessKeyId",
                "SignatureDoesNotMatch",
            ):
                raise click.ClickException(
                    f"S3 auth error while checking '{key}': {e}\n"
                    "Check your credentials (access key / secret key) and bucket "
                    "permissions — this is a permissions failure, not a missing object."
                )
            return False

    def delete(self, key):
        try:
            self.client.delete_object(Bucket=self.bucket, Key=self._key(key))
        except ClientError as e:
            raise click.ClickException(f"S3 delete failed: {e}")

    def put_file(self, key, local_path):
        try:
            self.client.upload_file(local_path, self.bucket, self._key(key))
        except ClientError as e:
            raise click.ClickException(f"S3 upload failed: {e}")

    def get_file(self, key, local_path):
        try:
            self.client.download_file(self.bucket, self._key(key), local_path)
        except ClientError as e:
            raise click.ClickException(f"S3 download failed: {e}")

    def ensure_bucket(self):
        try:
            self.client.create_bucket(Bucket=self.bucket)
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code not in ("BucketAlreadyExists", "BucketAlreadyOwnedByYou"):
                raise click.ClickException(f"S3 bucket creation failed: {e}")
