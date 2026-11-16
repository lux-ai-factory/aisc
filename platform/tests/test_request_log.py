"""The platform writes one JSON object per log line, with the request id it was given (X-AISC-Request-Id),
so a line can be joined to the ledger event and the other services' lines of the same request."""
from __future__ import annotations

import json

from tests.conftest import needs_database


def _json_lines(text: str) -> list[dict]:
    lines = []
    for line in text.splitlines():
        if line.startswith("{"):
            try:
                lines.append(json.loads(line))
            except ValueError:
                pass
    return lines


@needs_database
def test_the_request_id_reaches_the_log_line(client, as_user, capfd):
    client.get("/projects", headers={**as_user("alice"), "X-AISC-Request-Id": "req-from-the-gateway"})
    out, err = capfd.readouterr()
    lines = _json_lines(out + "\n" + err)
    assert any(line.get("request_id") == "req-from-the-gateway" for line in lines), \
        "no JSON log line names the request id"
    line = next(line for line in lines if line.get("request_id") == "req-from-the-gateway")
    assert line.get("service") == "platform" and line.get("time", "").endswith("Z")
