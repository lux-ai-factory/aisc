"""The canonical document: OpenAPI 3.1 whose operations carry x-aisc-binding (spec D3)."""
from __future__ import annotations

import copy
from dataclasses import dataclass

HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
SAFE_METHODS = {"get", "head", "options"}


@dataclass(frozen=True)
class Operation:
    operation_id: str
    method: str
    path: str
    summary: str
    changes_data: bool
    binding: dict
    spec: dict


def operations(document: dict) -> list[Operation]:
    found = []
    for path, item in (document.get("paths") or {}).items():
        for method in HTTP_METHODS:
            op = (item or {}).get(method)
            if not isinstance(op, dict) or "operationId" not in op:
                continue
            found.append(Operation(op["operationId"], method, path, op.get("summary") or "",
                                   method not in SAFE_METHODS or op.get("x-aisc-binding", {}).get("protocol") == "soap",
                                   op.get("x-aisc-binding") or {}, op))
    return found


def find(document: dict, operation_id: str) -> Operation | None:
    return next((o for o in operations(document) if o.operation_id == operation_id), None)


def server_url(document: dict) -> str:
    return document["servers"][0]["url"].rstrip("/")


def strip_aisc(obj):
    if isinstance(obj, dict):
        return {k: strip_aisc(v) for k, v in obj.items() if not str(k).startswith("x-aisc")}
    if isinstance(obj, list):
        return [strip_aisc(v) for v in obj]
    return copy.deepcopy(obj)
