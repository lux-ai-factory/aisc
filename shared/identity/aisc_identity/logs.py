"""One JSON object per log line, the same in every service.

Each line has the time in UTC, the level, the service, the logger, the message, and the ids of the request
(`request_id`) and of the run (`evaluation_pid`) being served, so the lines of one request or one run can be
found across services. A line logged with an exception also has `error`, the traceback, in the same line.
"""
from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

#: the request being served (X-AISC-Request-Id), or None
request_id: ContextVar[str | None] = ContextVar("aisc_request_id", default=None)
#: the run (evaluation pid) being served, or None
evaluation_pid: ContextVar[str | None] = ContextVar("aisc_evaluation_pid", default=None)


class JsonFormatter(logging.Formatter):
    # held by the class, because a line logged while Python shuts down finds this module's globals set to None
    _from_timestamp = staticmethod(datetime.fromtimestamp)
    _utc = timezone.utc
    _dumps = staticmethod(json.dumps)
    _request_id = request_id
    _evaluation_pid = evaluation_pid

    def __init__(self, service: str = "") -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        line = {
            "time": self._from_timestamp(record.created, self._utc).isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", self._request_id.get()),
            "evaluation_pid": getattr(record, "evaluation_pid", self._evaluation_pid.get()),
        }
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return self._dumps(line, default=str)


class KeepIds(logging.Filter):
    """Copies the ids onto the record where it is logged, for a handler that formats it in another thread
    (a queue's listener), where the ids of the request or run are not set."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get()
        record.evaluation_pid = evaluation_pid.get()
        return True


class _Stdout(logging.StreamHandler):
    """Writes to whatever sys.stdout is when the line is written."""
    _sys = sys    # held by the class, as in JsonFormatter

    def __init__(self) -> None:
        super().__init__()

    @property
    def stream(self):
        return self._sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure(service: str, level: str = "INFO") -> None:
    """The root logger writes JSON lines to stdout through one handler, and Python warnings become log lines.
    Calling it again replaces the handler, never adds a second."""
    handler = _Stdout()
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.captureWarnings(True)
