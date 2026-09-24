"""What can go wrong, in words a person can act on (spec D8)."""
from __future__ import annotations

#: Target-side kinds: the target answered, and this is what its answer means.
TARGET_KINDS = {"ok", "auth", "not_found", "rate_limited", "target_rejected", "target_error"}
#: Gateway-side kinds and the status the gateway answers with.
GATEWAY_STATUS = {
    "not_allowed": 403, "invalid_input": 422, "rate_limited": 429, "timeout": 504,
    "tls": 502, "dns": 502, "connection": 502, "bad_mapping": 502, "target_too_large": 502,
}


class GatewayFailure(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message

    @property
    def status(self) -> int:
        return GATEWAY_STATUS.get(self.kind, 502)

    def body(self) -> dict:
        return {"error": {"kind": self.kind, "message": self.message}}


def kind_for_status(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "target_rejected"
    if status >= 500:
        return "target_error"
    return "ok"
