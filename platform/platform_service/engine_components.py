"""The engine's components, as the platform makes and renames them (targets plan v2).

Every call goes through the engine's own API with the caller's own token, so the engine checks and
records that person as if they had used the engine. The engine keeps its own project row per
platform project, with its own pid: `for-platform` finds it (and makes it on first use).
"""
from __future__ import annotations

import os

from aisc_service_client import Response, ServiceClient, ServiceTimeout, ServiceUnreachable

PROJECT_HEADER = "X-AISC-Project"
REQUEST_HEADER = "X-AISC-Request-Id"
TIMEOUT_S = 20
#: an install has the eval worker install the test and read its manifest (the engine never imports plugin code):
#: a minute longer than the engine waits for the worker (its PLUGIN_MANIFEST_TIMEOUT_S, 900 by default), so the
#: engine's named reason reaches the person when the worker does not answer
INSTALL_TIMEOUT_S = 960


class EngineUnavailable(RuntimeError):
    """The engine did not accept the call. `status` is its answer's status, None when it did not answer;
    `detail` the reason it gave, when it gave one. `unconfirmed`: the call was sent and the engine did not answer
    in time, so what it did is not known (it may still finish)."""

    def __init__(self, message: str, status: int | None = None, detail: str | None = None,
                 unconfirmed: bool = False):
        super().__init__(message)
        self.status = status
        self.detail = detail
        self.unconfirmed = unconfirmed


def _detail_of(r: Response) -> str | None:
    """The `detail` of an engine refusal, when its body is JSON that has one."""
    try:
        detail = r.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) else None


def _base() -> str:
    return (os.environ.get("ENGINE_URL") or "http://aisc-backend:8000").rstrip("/")


def _engine(timeout_s: float) -> ServiceClient:
    return ServiceClient(_base(), timeout=timeout_s, service="the engine")


def _headers(pid, token: str, cite_request: bool) -> dict:
    """The person's token and the project. With `cite_request`, inside a witnessed request also its id, so
    the engine's event for this call cites the request the person made (the ledger registry names the
    platform's route as a cause of that event)."""
    from platform_service.ledger import outbox

    # the request id only of a witnessed request, and only when asked: never the log's id of the call
    request_id = outbox.current_request.get() if cite_request else None
    return {"Authorization": f"Bearer {token}", PROJECT_HEADER: str(pid), REQUEST_HEADER: request_id or None}


def _call(method: str, path: str, pid, token: str, body: dict | None = None, cite_request: bool = False,
          timeout_s: float = TIMEOUT_S, doing: str | None = None) -> dict:
    """`doing` names a write the engine may finish after the wait (an install): a timeout then says it is not
    confirmed rather than not reached."""
    try:
        r = _engine(timeout_s).request(method, path, json=body, headers=_headers(pid, token, cite_request))
    except ServiceTimeout as exc:
        if doing is None or exc.cause != "ReadTimeout":
            raise EngineUnavailable(f"the engine could not be reached ({exc.cause})") from None
        # sent, and not answered in time: the engine may still be doing it
        raise EngineUnavailable(f"the engine did not confirm {doing} within {timeout_s:g} s",
                                unconfirmed=True) from None
    except ServiceUnreachable as exc:
        raise EngineUnavailable(f"the engine could not be reached ({exc.cause})") from None
    if r.status_code >= 300:
        raise EngineUnavailable(f"the engine answered {r.status_code}", r.status_code, _detail_of(r))
    try:
        return r.json()
    except ValueError:
        raise EngineUnavailable(f"the engine answered {r.status_code} with something that is not JSON",
                                r.status_code) from None


def available_plugins(pid, token: str) -> list[dict]:
    """The packages the engine can install, `{package_name, version, source}` each ("local": the
    local_plugins/ folder, "registry": the stack's package index): its own GET /api/v1/plugins."""
    return list(_call("GET", "/api/v1/plugins", pid, token) or [])


def plugin_declarations(pid, token: str) -> list[dict]:
    """What each test installed in this project declares about what it assesses (`target_kinds`,
    `card_protocols`, `card_needs_connection`, with its `name` and `display_name`): the engine's own
    GET /api/v1/plugins/declarations."""
    return list(_call("GET", "/api/v1/plugins/declarations", pid, token) or [])


def engine_project(pid, token: str) -> str:
    """The engine's pid of this platform project."""
    return str(_call("POST", f"/api/v1/projects/for-platform/{pid}", pid, token)["pid"])


def install_plugin(pid, token: str, package: str, version: str, slug: str,
                   wheel_sha256: str | None = None) -> None:
    """Install a test into this platform project's engine side, at this version, recording the catalogue
    entry it came from: the engine's own POST /api/v1/plugins, which takes the admin role. `wheel_sha256`, the
    hash of the wheel the publisher published, makes the engine install that wheel and no other."""
    engine_pid = engine_project(pid, token)
    body = {"package_name": package, "version": version, "project_uuid": engine_pid, "catalogue_slug": slug}
    if wheel_sha256:
        body["wheel_sha256"] = wheel_sha256
    _call("POST", "/api/v1/plugins", pid, token, body, cite_request=True, timeout_s=INSTALL_TIMEOUT_S,
          doing="the install")


def components(pid, token: str, engine_pid: str | None = None) -> list[dict]:
    engine_pid = engine_pid or engine_project(pid, token)
    return list(_call("GET", f"/api/v1/projects/{engine_pid}/aisystem", pid, token).get("components") or [])


def create(pid, token: str, name: str, value: str, engine_pid: str | None = None) -> str:
    """A new `resource` component whose value is `value`; its pid."""
    engine_pid = engine_pid or engine_project(pid, token)
    made = _call("POST", f"/api/v1/projects/{engine_pid}/components", pid, token,
                 {"name": name, "component_type": "resource", "json_value": {"value": value}})
    return str(made["pid"])


def create_file_component(pid, token: str, component_type: str, name: str, card_target: str) -> str:
    """A new `model` or `dataset` component holding the uploaded file of the card target `card_target`
    (json_value.card_target, so the engine's test data panel can leave it out); its pid."""
    made = _call("POST", f"/api/v1/projects/{engine_project(pid, token)}/components", pid, token,
                 {"name": name, "component_type": component_type, "json_value": {"card_target": card_target}})
    return str(made["pid"])


#: an upload may be large: the engine stores it before it answers
UPLOAD_TIMEOUT_S = 900


def upload(pid, token: str, component: str, file_name: str, stream) -> None:
    """The bytes of `stream` as the file of `component`, through the engine's own upload route."""
    try:
        r = _engine(UPLOAD_TIMEOUT_S).put(f"/api/v1/components/{component}/data",
                                          files={"file": (file_name, stream, "application/octet-stream")},
                                          headers={"Authorization": f"Bearer {token}", PROJECT_HEADER: str(pid),
                                                   REQUEST_HEADER: None})
    except (ServiceUnreachable, ServiceTimeout) as exc:
        raise EngineUnavailable(f"the engine could not be reached ({exc.cause})") from None
    if r.status_code >= 300:
        raise EngineUnavailable(f"the engine answered {r.status_code}", r.status_code, _detail_of(r))


def rename(pid, token: str, component: str, name: str) -> None:
    _call("PATCH", f"/api/v1/components/{component}", pid, token, {"name": name})


def value_of(component: dict) -> str | None:
    json_value = component.get("json_value")
    return json_value.get("value") if isinstance(json_value, dict) else None
