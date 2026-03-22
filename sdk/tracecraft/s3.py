"""Minimal boto3 wrapper with project-scoped keys."""

import json

import boto3
import click
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from tracecraft.config import load_config


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

    def put_json(self, key, data):
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=self._key(key),
                Body=json.dumps(data, indent=2),
                ContentType="application/json",
            )
        except ClientError as e:
            raise click.ClickException(f"S3 put failed: {e}")

    def get_json(self, key):
        try:
            resp = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
            return json.loads(resp["Body"].read())
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            raise click.ClickException(f"S3 get failed: {e}")

    def list_keys(self, prefix=""):
        try:
            full_prefix = self._key(prefix)
            resp = self.client.list_objects_v2(Bucket=self.bucket, Prefix=full_prefix)
            keys = []
            for obj in resp.get("Contents", []):
                stripped = obj["Key"][len(self.project) + 1 :]
                keys.append(stripped)
            return keys
        except ClientError as e:
            raise click.ClickException(f"S3 list failed: {e}")

    def exists(self, key):
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except ClientError:
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
