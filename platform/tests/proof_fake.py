"""An in-memory stand-in for the proof-file store, with the same methods as proof_store.MinioStore.

tests/test_proof_store.py runs the same contract against both, so a route test on this one says what
the real one would do."""
from __future__ import annotations

from platform_service.proof_store import Opened, StorageUnavailable


class FakeStore:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, tuple[bytes, str, dict]]] = {}
        #: set to make every call fail as an unreachable MinIO would
        self.down = False

    def _check(self) -> None:
        if self.down:
            raise StorageUnavailable("the fake store is down")

    def make_bucket(self, bucket: str) -> None:
        self._check()
        self.buckets.setdefault(bucket, {})

    def remove_bucket(self, bucket: str) -> None:
        self._check()
        self.buckets.pop(bucket, None)

    def remove_objects(self, bucket: str, names: list[str]) -> list[str]:
        self._check()
        for name in names:
            self.buckets.get(bucket, {}).pop(name, None)
        return []

    def has_bucket(self, bucket: str) -> bool:
        self._check()
        return bucket in self.buckets

    def put(self, bucket: str, key: str, data: bytes, mime: str, meta: dict[str, str]) -> None:
        self._check()
        objects = self.buckets.setdefault(bucket, {})
        if key in objects:
            raise FileExistsError(key)
        objects[key] = (bytes(data), mime, dict(meta))

    def open(self, bucket: str, key: str) -> Opened | None:
        self._check()
        found = self.buckets.get(bucket, {}).get(key)
        if found is None:
            return None
        data, mime, meta = found
        return Opened(chunks=iter([data]), mime=mime, size=len(data), meta=dict(meta), close=lambda: None)
