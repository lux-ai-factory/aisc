"""The proof files of checklist answers: one MinIO bucket per project, and the files in it.

A project's bucket is `proof-<pid without dashes>`, made when the project's database is made and removed
when the project is deleted, so its files are as separate from other projects' as its database is. The
controls app never holds credentials for these buckets: it sends the platform a file and is told what it stored
(POST /internal/projects/{pid}/proof-files), and reads it back the same way. The platform reaches them with its
own MinIO account (S3_USER/S3_PASSWORD, aisc-platform in the stack), which may use the proof-* buckets only, and
in the engine's buckets list and delete files but not read them (infra/minio/policies/platform.json). The engine
backend's account cannot reach the proof buckets.

A stored file is never replaced and never deleted while its project exists. Each one is stored under an id
the platform makes; there is no route that writes to an id that exists, and none that deletes one.
Removing a file from an answer only unlinks it in the controls app, so the audit trail keeps the original.

The store reads the stack's S3 settings (S3_URL, S3_USER, S3_PASSWORD); with no S3_URL it is not set up,
and project buckets are not made (a platform run without MinIO, such as the tests).
"""
from __future__ import annotations

import hashlib
import io
import logging
import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from platform_service.proof_types import clean_name, sniff

logger = logging.getLogger(__name__)

BUCKET_PREFIX = "proof-"
#: how much of a stored file is read from MinIO at a time when it is sent back
CHUNK_BYTES = 64 * 1024


class StorageUnavailable(Exception):
    """MinIO is not set up, or did not answer."""


@dataclass
class Opened:
    """A stored file being read: its bytes in chunks, and `close` once done with them."""
    chunks: Iterator[bytes]
    mime: str
    size: int
    meta: dict[str, str]
    close: Callable[[], None]


def bucket_name(pid) -> str:
    """The project's bucket; only a project id names one."""
    from platform_service.projectdb import database_name

    return BUCKET_PREFIX + database_name(pid).removeprefix("project_")


class MinioStore:
    """The proof buckets on a MinIO server (S3 API)."""

    def __init__(self, url: str, user: str, password: str):
        import urllib3
        from minio import Minio

        parts = urlsplit(url)
        http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=3, read=60),
                                   retries=urllib3.Retry(total=2, backoff_factor=0.2,
                                                         status_forcelist=(500, 502, 503, 504)))
        # the region is given, so the client does not ask MinIO for each bucket's location first
        self._client = Minio(parts.netloc, access_key=user, secret_key=password, secure=parts.scheme == "https",
                             region="us-east-1", http_client=http)

    def _call(self, what: str, fn, *args, **kwargs):
        """fn(*args), with MinIO not answering raised as StorageUnavailable; S3 errors pass through."""
        from minio.error import S3Error
        from urllib3.exceptions import HTTPError

        try:
            return fn(*args, **kwargs)
        except S3Error:
            raise
        except (HTTPError, OSError) as exc:
            raise StorageUnavailable(f"MinIO did not answer ({what}: {exc.__class__.__name__})") from None

    def make_bucket(self, bucket: str) -> None:
        from minio.error import S3Error

        if self._call("bucket_exists", self._client.bucket_exists, bucket):
            return
        try:
            self._call("make_bucket", self._client.make_bucket, bucket)
        except S3Error as exc:
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):    # made meanwhile
                raise

    def has_bucket(self, bucket: str) -> bool:
        return bool(self._call("bucket_exists", self._client.bucket_exists, bucket))

    def remove_bucket(self, bucket: str) -> None:
        """The bucket and every file in it; a bucket that is not there is left as it is."""
        from minio.deleteobjects import DeleteObject
        from minio.error import S3Error

        try:
            while True:
                names = [o.object_name for o in self._call(
                    "list_objects", lambda: list(self._client.list_objects(bucket, recursive=True)))]
                if not names:
                    break
                errors = self._call("remove_objects", lambda: list(self._client.remove_objects(
                    bucket, (DeleteObject(n) for n in names))))
                if errors:
                    raise StorageUnavailable(f"MinIO kept {len(errors)} files of bucket {bucket}")
            self._call("remove_bucket", self._client.remove_bucket, bucket)
        except S3Error as exc:
            if exc.code != "NoSuchBucket":
                raise

    def put(self, bucket: str, key: str, data: bytes, mime: str, meta: dict[str, str]) -> None:
        """Write a new object; FileExistsError if `key` is taken (an object is never replaced)."""
        from minio.error import S3Error

        try:
            self._call("stat_object", self._client.stat_object, bucket, key)
        except S3Error as exc:
            if exc.code not in ("NoSuchKey", "NoSuchObject"):
                raise
        else:
            raise FileExistsError(key)
        self._call("put_object", self._client.put_object, bucket, key, io.BytesIO(data), len(data),
                   content_type=mime, metadata=dict(meta))

    def open(self, bucket: str, key: str) -> Opened | None:
        from minio.error import S3Error

        try:
            response = self._call("get_object", self._client.get_object, bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchBucket", "NoSuchObject"):
                return None
            raise
        prefix = "x-amz-meta-"
        meta = {k.lower()[len(prefix):]: v for k, v in response.headers.items() if k.lower().startswith(prefix)}

        def close() -> None:
            response.close()
            response.release_conn()

        return Opened(chunks=response.stream(CHUNK_BYTES), mime=response.headers.get("content-type", ""),
                      size=int(response.headers.get("content-length", "0")), meta=meta, close=close)


def store() -> MinioStore | None:
    """The store the stack's S3 settings name, or None when S3_URL is not set."""
    url = os.environ.get("S3_URL", "").strip()
    if not url:
        return None
    return MinioStore(url, os.environ.get("S3_USER", ""), os.environ.get("S3_PASSWORD", ""))


def make_project_bucket(pid) -> None:
    """The project's bucket, made if it is missing. Not set up: nothing to make, said once in the log."""
    found = store()
    if found is None:
        logger.warning("proof files: S3_URL is not set, so project %s has no bucket for them", pid)
        return
    found.make_bucket(bucket_name(pid))


def remove_project_bucket(pid) -> None:
    found = store()
    if found is not None:
        found.remove_bucket(bucket_name(pid))


def save(pid, given_name: str, data: bytes) -> dict:
    """Check and store one file of the project; what was stored: {id, name, mime, size, sha256}.

    proof_types.Refused when the file is not taken. The bucket is made first if it is missing: a project
    made before proof files existed has none."""
    name = clean_name(given_name)
    mime = sniff(data, name)
    found = store()
    if found is None:
        raise StorageUnavailable("proof files are not set up here: S3_URL is not set")
    bucket = bucket_name(pid)
    found.make_bucket(bucket)
    file_id = str(uuid.uuid4())
    sha256 = hashlib.sha256(data).hexdigest()
    # S3 metadata is ASCII: the name is kept percent-encoded
    found.put(bucket, file_id, data, mime, {"name": quote(name, safe=""), "sha256": sha256})
    return {"id": file_id, "name": name, "mime": mime, "size": len(data), "sha256": sha256}


def open_file(pid, file_id: str) -> Opened | None:
    """The project's stored file, or None when it has no file with this id."""
    try:
        key = str(uuid.UUID(file_id))
    except ValueError:
        return None
    found = store()
    if found is None:
        raise StorageUnavailable("proof files are not set up here: S3_URL is not set")
    return found.open(bucket_name(pid), key)
