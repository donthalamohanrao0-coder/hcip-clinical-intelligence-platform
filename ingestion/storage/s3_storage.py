from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from ingestion.config import Settings, get_settings
from ingestion.exceptions import S3Error


class S3Storage:
    """
    Thin boto3 wrapper for all S3 document storage operations.

    Key layout:
        raw/{org_id}/{doc_id}/{filename}          ← original uploaded file
        parsed/{org_id}/{doc_id}/{filename}        ← extracted text/tables/images
        versions/{org_id}/{doc_id}/v{n}/{filename} ← immutable version archive
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        cfg = settings or get_settings()
        self._client = boto3.client(
            "s3",
            aws_access_key_id=cfg.aws_access_key_id,
            aws_secret_access_key=cfg.aws_secret_access_key,
            region_name=cfg.aws_region,
        )
        self._bucket          = cfg.s3_bucket
        self._raw_prefix      = cfg.s3_raw_prefix
        self._parsed_prefix   = cfg.s3_parsed_prefix
        self._versions_prefix = cfg.s3_versions_prefix

    # ── Key builders ──────────────────────────────────────────────────────────

    def raw_key(self, org_id: str, doc_id: str, filename: str) -> str:
        return f"{self._raw_prefix}/{org_id}/{doc_id}/{filename}"

    def parsed_key(self, org_id: str, doc_id: str, filename: str) -> str:
        return f"{self._parsed_prefix}/{org_id}/{doc_id}/{filename}"

    def version_key(self, org_id: str, doc_id: str, version: int, filename: str) -> str:
        return f"{self._versions_prefix}/{org_id}/{doc_id}/v{version}/{filename}"

    # ── Write ─────────────────────────────────────────────────────────────────

    def upload_bytes(
        self,
        data: bytes,
        s3_key: str,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Upload raw bytes to S3. Returns the s3_key on success."""
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=s3_key,
                Body=data,
                ContentType=content_type,
            )
            return s3_key
        except ClientError as exc:
            raise S3Error(f"Upload failed [{s3_key}]: {exc}") from exc

    def upload_file(self, file_path: Path, s3_key: str) -> str:
        """Upload a local file to S3 using multipart for large files. Returns s3_key."""
        try:
            self._client.upload_file(str(file_path), self._bucket, s3_key)
            return s3_key
        except ClientError as exc:
            raise S3Error(f"Upload failed [{file_path} → {s3_key}]: {exc}") from exc

    # ── Read ──────────────────────────────────────────────────────────────────

    def download_bytes(self, s3_key: str) -> bytes:
        """Download an S3 object and return its content as bytes."""
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=s3_key)
            return response["Body"].read()
        except ClientError as exc:
            raise S3Error(f"Download failed [{s3_key}]: {exc}") from exc

    def download_to_file(self, s3_key: str, dest_path: Path) -> Path:
        """Download an S3 object to a local file. Returns the destination path."""
        try:
            self._client.download_file(self._bucket, s3_key, str(dest_path))
            return dest_path
        except ClientError as exc:
            raise S3Error(f"Download failed [{s3_key} → {dest_path}]: {exc}") from exc

    # ── Presigned URLs ────────────────────────────────────────────────────────

    def presigned_upload_url(self, s3_key: str, expires_in: int = 3_600) -> str:
        """Generate a presigned PUT URL for direct browser uploads."""
        return self._client.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    def presigned_download_url(self, s3_key: str, expires_in: int = 3_600) -> str:
        """Generate a presigned GET URL for secure file downloads."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    # ── Utility ───────────────────────────────────────────────────────────────

    def exists(self, s3_key: str) -> bool:
        """Return True if the key exists in the bucket."""
        try:
            self._client.head_object(Bucket=self._bucket, Key=s3_key)
            return True
        except ClientError:
            return False

    def delete(self, s3_key: str) -> None:
        """Delete a single object. No-ops if the key does not exist."""
        try:
            self._client.delete_object(Bucket=self._bucket, Key=s3_key)
        except ClientError as exc:
            raise S3Error(f"Delete failed [{s3_key}]: {exc}") from exc

    def get_object_size(self, s3_key: str) -> int:
        """Return the file size in bytes without downloading the content."""
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=s3_key)
            return response["ContentLength"]
        except ClientError as exc:
            raise S3Error(f"Head failed [{s3_key}]: {exc}") from exc
