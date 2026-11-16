"""Every service logs one JSON object per line, with the time in UTC, the level, the service, the logger, the message
and the ids of the request and of the run being served, so the lines of one request or one run can be found across
services. Python warnings become log lines too, and configuring twice adds no second handler."""

import importlib
import importlib.util
import json
import logging
import warnings

import pytest


def _logs():
    assert importlib.util.find_spec("aisc_identity.logs") is not None, \
        "no aisc_identity.logs: each service logs plain text in its own format"
    return importlib.import_module("aisc_identity.logs")


@pytest.fixture(autouse=True)
def _clean_root_logger():
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    root.handlers[:] = before
    logging.captureWarnings(False)


def _last_json(text: str) -> dict:
    return json.loads([line for line in text.splitlines() if line.startswith("{")][-1])


def test_a_line_is_one_json_object_with_the_ids(capsys):
    logs = _logs()
    logs.configure("platform")
    t1, t2 = logs.request_id.set("req-1"), logs.evaluation_pid.set("ev-1")
    try:
        logging.getLogger("x").warning("hello")
    finally:
        logs.request_id.reset(t1)
        logs.evaluation_pid.reset(t2)
    line = _last_json(capsys.readouterr().out)
    assert line["service"] == "platform" and line["level"] == "WARNING" and line["message"] == "hello"
    assert line["logger"] == "x" and line["request_id"] == "req-1" and line["evaluation_pid"] == "ev-1"
    assert line["time"].endswith("Z")


def test_an_exception_is_one_line_with_its_error(capsys):
    logs = _logs()
    logs.configure("platform")
    try:
        raise ValueError("broken")
    except ValueError:
        logging.getLogger("x").exception("failed")
    out = capsys.readouterr().out
    line = _last_json(out)
    assert "ValueError" in line["error"] and len([x for x in out.splitlines() if x.strip()]) == 1


def test_configure_twice_adds_no_second_handler():
    logs = _logs()
    logs.configure("x")
    logs.configure("x")
    assert len(logging.getLogger().handlers) == 1


def test_a_python_warning_becomes_a_log_line(capsys):
    logs = _logs()
    logs.configure("x")
    warnings.warn("careful")
    assert _last_json(capsys.readouterr().out)["logger"] == "py.warnings"


def test_a_line_formatted_in_a_queues_thread_keeps_the_ids(capsys):
    import logging.handlers
    import queue

    logs = _logs()
    q = queue.Queue()
    out = logging.StreamHandler()
    out.setFormatter(logs.JsonFormatter("eval"))
    listener = logging.handlers.QueueListener(q, out)
    handler = logging.handlers.QueueHandler(q)
    handler.addFilter(logs.KeepIds())
    logger = logging.getLogger("queued")
    logger.propagate = False
    logger.addHandler(handler)
    listener.start()
    token = logs.evaluation_pid.set("ev-2")
    try:
        logger.warning("from a task")
    finally:
        logs.evaluation_pid.reset(token)
        listener.stop()
        logger.removeHandler(handler)
        logger.propagate = True
    assert _last_json(capsys.readouterr().err)["evaluation_pid"] == "ev-2"
