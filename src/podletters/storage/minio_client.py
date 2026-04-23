"""MinIO (S3-compatible) storage client for episode files and metadata.

Implements FR-05.1 through FR-05.3: each episode is stored as a ``.mp3``
and a ``.json`` metadata sidecar, keyed under ``YYYY/MM/`` prefixes.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from podletters.config import Settings, get_settings
from podletters.models import EpisodeMetadata

logger = logging.getLogger(__name__)


class MinIOClient:
    """Wrapper around ``boto3`` S3 operations scoped to a single bucket."""

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or get_settings()
        self._bucket = settings.minio_bucket
        self._base_url = settings.minio_endpoint
        self._s3 = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=BotoConfig(signature_version="s3v4"),
            region_name="us-east-1",  # MinIO default
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        try:
            self._s3.head_bucket(Bucket=self._bucket)
        except ClientError:
            logger.info("Creating bucket: %s", self._bucket)
            self._s3.create_bucket(Bucket=self._bucket)

    def _key_prefix(self, dt: datetime) -> str:
        return f"{dt.year}/{dt.month:02d}"

    def upload_episode(
        self,
        mp3_path: Path,
        metadata: EpisodeMetadata,
    ) -> str:
        """Upload the MP3 and a JSON metadata sidecar. Returns the MP3 S3 key."""
        prefix = self._key_prefix(metadata.created_at)
        mp3_key = f"{prefix}/{mp3_path.name}"
        json_key = f"{prefix}/{mp3_path.stem}.json"

        logger.info("[minio] Uploading MP3: %s → %s", mp3_path, mp3_key)
        self._s3.upload_file(
            str(mp3_path),
            self._bucket,
            mp3_key,
            ExtraArgs={"ContentType": "audio/mpeg"},
        )

        meta_json = json.dumps(
            metadata.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        logger.info("[minio] Uploading metadata: %s", json_key)
        self._s3.put_object(
            Bucket=self._bucket,
            Key=json_key,
            Body=meta_json,
            ContentType="application/json",
        )

        return mp3_key

    def list_episode_metadata(self) -> list[EpisodeMetadata]:
        """List all episode metadata JSONs in the bucket, newest first."""
        paginator = self._s3.get_paginator("list_objects_v2")
        metas: list[EpisodeMetadata] = []

        for page in paginator.paginate(Bucket=self._bucket):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if not key.endswith(".json"):
                    continue
                try:
                    resp = self._s3.get_object(Bucket=self._bucket, Key=key)
                    data = json.loads(resp["Body"].read())
                    metas.append(EpisodeMetadata(**data))
                except Exception as exc:
                    logger.warning("[minio] Skipping %s: %s", key, exc)

        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas

    def delete_episode(self, metadata: EpisodeMetadata) -> None:
        """Delete both the MP3 and JSON sidecar for an episode."""
        prefix = self._key_prefix(metadata.created_at)
        slug = metadata.episode_id
        # Scan for objects matching this episode in the expected prefix.
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if slug in key:
                    self._s3.delete_object(Bucket=self._bucket, Key=key)
                    logger.info("[minio] Deleted: %s", key)

    def get_public_url(self, key: str) -> str:
        """Construct a direct-access URL for a stored object."""
        return f"{self._base_url}/{self._bucket}/{key}"


__all__ = ["MinIOClient"]
