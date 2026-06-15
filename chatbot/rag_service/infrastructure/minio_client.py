"""
minio_client.py
---------------
Thin wrapper around the MinIO Python SDK for local PDF storage.

Responsibilities:
  - Connect to local MinIO server
  - Ensure the bucket exists
  - Upload a PDF file
  - Download a PDF file to a local temp path
  - List all PDF objects in the bucket

All data stays on your local machine (127.0.0.1:9000).
Nothing goes to the internet.

Usage in other files:
    from minio_client import download_pdf, list_pdfs, upload_pdf
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

from minio import Minio
from minio.error import S3Error

from config import settings


def _get_client() -> Minio:
    """Create and return a MinIO client using settings from .env"""
    return Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,       # False for local HTTP
    )


def ensure_bucket_exists() -> None:
    """
    Create the bucket if it doesn't exist yet.
    Safe to call multiple times — does nothing if bucket already exists.
    """
    client = _get_client()
    bucket = settings.minio_bucket
    try:
        if not client.bucket_exists(bucket):
            client.make_bucket(bucket)
            print(f"[MinIO] Created bucket: '{bucket}'")
        else:
            print(f"[MinIO] Bucket '{bucket}' already exists.")
    except S3Error as e:
        print(f"[MinIO] Error checking/creating bucket: {e}")
        raise


def upload_pdf(local_path: str | Path, object_name: str | None = None) -> str:
    """
    Upload a PDF from disk to MinIO.

    Parameters
    ----------
    local_path  : Path to the PDF file on your local disk.
    object_name : Name to store it as in MinIO.
                  Defaults to the filename (e.g. "rawinfosmart.pdf").

    Returns the object name used.

    Example:
        upload_pdf("/Users/me/rawinfosmart.pdf")
        upload_pdf("/Users/me/rawinfosmart_v2.pdf", "rawinfosmart.pdf")
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"File not found: {local_path}")

    if object_name is None:
        object_name = local_path.name

    client = _get_client()
    ensure_bucket_exists()

    client.fput_object(
        bucket_name=settings.minio_bucket,
        object_name=object_name,
        file_path=str(local_path),
        content_type="application/pdf",
    )
    print(f"[MinIO] Uploaded '{local_path.name}' → bucket '{settings.minio_bucket}' as '{object_name}'")
    return object_name


def download_pdf(object_name: str, destination: str | Path | None = None) -> Path:
    """
    Download a PDF from MinIO to a local temp file (or a specific path).

    Parameters
    ----------
    object_name : The name of the object in MinIO (e.g. "rawinfosmart.pdf").
    destination : Where to save it locally.
                  If None, saves to a temp file that you should delete after use.

    Returns the local Path where the file was saved.

    Example:
        local_path = download_pdf("rawinfosmart.pdf")
        # use local_path ...
        local_path.unlink()  # clean up temp file when done
    """
    client = _get_client()

    if destination is None:
        # Save to a named temp file so we can pass the path to pypdf
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".pdf", prefix="smartbot_"
        )
        tmp.close()
        destination = Path(tmp.name)
    else:
        destination = Path(destination)

    try:
        client.fget_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            file_path=str(destination),
        )
        print(f"[MinIO] Downloaded '{object_name}' → {destination}")
    except S3Error as e:
        raise RuntimeError(
            f"Could not download '{object_name}' from MinIO bucket '{settings.minio_bucket}'.\n"
            f"Make sure MinIO is running and you have uploaded the file.\n"
            f"Original error: {e}"
        )

    return destination


def download_pdf_bytes(object_name: str) -> bytes:
    """
    Download a PDF from MinIO and return the raw bytes (no temp file needed).
    Useful when you want to pass bytes directly to a text extractor.
    """
    client = _get_client()
    try:
        response = client.get_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
        )
        data = response.read()
        response.close()
        response.release_conn()
        return data
    except S3Error as e:
        raise RuntimeError(
            f"Could not read '{object_name}' from MinIO: {e}"
        )


def list_pdfs() -> list[str]:
    """
    List all PDF object names in the bucket.

    Returns a list of strings like:
        ["rawinfosmart.pdf", "rawinfosmart_v2.pdf", "new_policy_2025.pdf"]

    Useful for building a multi-document index (future feature).
    """
    client = _get_client()
    try:
        objects = client.list_objects(settings.minio_bucket)
        names = [obj.object_name for obj in objects if obj.object_name.endswith(".pdf")]
        return names
    except S3Error as e:
        print(f"[MinIO] Could not list objects: {e}")
        return []


def is_minio_available() -> bool:
    """
    Quick health check — returns True if MinIO is reachable.
    Used by build_sinarmas_index.py to decide whether to use MinIO or local file.
    """
    try:
        client = _get_client()
        client.list_buckets()
        return True
    except Exception:
        return False