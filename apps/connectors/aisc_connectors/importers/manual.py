"""A guided form: method, URL, an example request and an example answer."""
from __future__ import annotations

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.build import one_operation


def import_manual(method: str, url: str, example_request: str | None, example_response: str | None,
                  content_type: str | None = "application/json", operation_id: str = "call") -> ImportResult:
    return one_operation(method, url, {}, example_request, content_type if example_request else None,
                         operation_id, example_response=example_response)
