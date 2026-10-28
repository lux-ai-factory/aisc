"""Adapter plugins: protocols an operator adds to their install without changing AISC's code.

An adapter is a folder in PLATFORM_ADAPTERS_DIR (the install's adapters/, mounted read-only; adapters/README.md)
with an adapter.py that defines PROTOCOL (its name, label, fields, capabilities) and call(connection, input,
history, params, open). Its name becomes a connection kind next to the built-in ones: the connection editor
offers it, and every call the platform makes to such a connection (the protocol doors, the Test button) goes
through call(). The folder is read once, when first needed; a change takes a restart. A folder that does not
load is logged and skipped, never fatal.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

#: the folder of adapters (the install's adapters/, mounted read-only)
ADAPTERS_DIR_DEFAULT = "/app/adapters"
BUILT_IN_KINDS = ("openai", "rest", "a2a", "oip")
ADAPTER_NAME = re.compile(r"^[a-z][a-z0-9-]{1,39}$")
FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
#: what an adapter may say it carries: text always, a history if it takes one
CAPABILITIES = ("text", "history")


@dataclass(frozen=True)
class Field:
    """One setting the connection editor asks for; a secret one is stored encrypted and never shown."""
    name: str
    label: str
    secret: bool = False
    required: bool = False
    help: str = ""


@dataclass(frozen=True)
class Adapter:
    name: str
    label: str
    fields: tuple[Field, ...]
    capabilities: tuple[str, ...]
    call: Callable
    base_url: str | None = None
    max_concurrent: int | None = None

    def public(self) -> dict:
        """What the protocols list shows: everything but the code."""
        return {"name": self.name, "label": self.label, "base_url": self.base_url,
                "fields": [{"name": f.name, "label": f.label, "secret": f.secret, "required": f.required,
                            "help": f.help} for f in self.fields],
                "capabilities": list(self.capabilities), "adapter": True}


class _Invalid(ValueError):
    """Why a folder is not an adapter."""


def _text(value, what: str, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise _Invalid(f"{what} must be a non-empty string")
    return value


def _field(i: int, raw) -> Field:
    if not isinstance(raw, dict):
        raise _Invalid(f"fields[{i}] must be an object")
    name = raw.get("name")
    if not isinstance(name, str) or not FIELD_NAME.fullmatch(name):
        raise _Invalid(f"fields[{i}] needs a name (letters, digits and _)")
    for flag in ("secret", "required"):
        if not isinstance(raw.get(flag, False), bool):
            raise _Invalid(f"fields[{i}].{flag} must be true or false")
    return Field(name=name, label=_text(raw.get("label"), f"fields[{i}].label"),
                 secret=raw.get("secret", False), required=raw.get("required", False),
                 help=_text(raw.get("help"), f"fields[{i}].help", required=False))


def _adapter_of(module) -> Adapter:
    protocol = getattr(module, "PROTOCOL", None)
    if not isinstance(protocol, dict):
        raise _Invalid("adapter.py defines no PROTOCOL dict")
    call = getattr(module, "call", None)
    if not callable(call):
        raise _Invalid("adapter.py defines no call(connection, input, history, params, open)")
    name = protocol.get("name")
    if not isinstance(name, str) or not ADAPTER_NAME.fullmatch(name):
        raise _Invalid(f"name {name!r} must match {ADAPTER_NAME.pattern}")
    if name in BUILT_IN_KINDS:
        raise _Invalid(f"name {name!r} is a built-in protocol")
    fields = tuple(_field(i, f) for i, f in enumerate(protocol.get("fields") or []))
    if len({f.name for f in fields}) != len(fields):
        raise _Invalid("two fields have the same name")
    capabilities = protocol.get("capabilities", ["text", "history"])
    if (not isinstance(capabilities, list) or "text" not in capabilities
            or any(c not in CAPABILITIES for c in capabilities)):
        raise _Invalid(f"capabilities must include text and may include history only, not {capabilities!r}")
    max_concurrent = protocol.get("max_concurrent")
    if max_concurrent is not None and (isinstance(max_concurrent, bool) or not isinstance(max_concurrent, int)
                                       or max_concurrent < 1):
        raise _Invalid("max_concurrent must be a whole number of at least 1")
    base_url = protocol.get("base_url")
    if base_url is not None and not isinstance(base_url, str):
        raise _Invalid("base_url must be a string")
    return Adapter(name=name, label=_text(protocol.get("label"), "label"), fields=fields,
                   capabilities=tuple(dict.fromkeys(capabilities)), call=call, base_url=base_url,
                   max_concurrent=max_concurrent)


def _own_modules(folder: Path) -> set[str]:
    """The names the modules beside adapter.py import under: its .py files and its packages."""
    names = {p.stem for p in folder.glob("*.py") if p.name != "adapter.py"}
    return names | {p.name for p in folder.iterdir() if p.is_dir() and (p / "__init__.py").is_file()}


def _import(folder: Path):
    """adapter.py of `folder` as a module of its own, the folder on sys.path while it loads (so it can import
    the modules beside it, at its top). A module beside it named like one already imported is refused (it would
    silently be that one); the modules it brought are taken out of sys.modules after the load, so another
    adapter's module of the same name, or a platform module imported later, is never this one."""
    own = _own_modules(folder)
    taken = sorted(own & set(sys.modules))
    if taken:
        raise _Invalid(f"its module {', '.join(taken)} has the name of a module already loaded; rename it")
    spec = importlib.util.spec_from_file_location(f"aisc_adapter_{folder.name.replace('-', '_')}",
                                                  folder / "adapter.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(folder))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(folder))
        for name in [n for n in sys.modules if n.split(".")[0] in own]:
            del sys.modules[name]
    return module


def load(directory: Path) -> dict[str, Adapter]:
    """Every adapter in `directory`, by name; a folder that does not load is logged and skipped. Folders are read
    in name order, and of two adapters with one name the first is kept."""
    found: dict[str, Adapter] = {}
    if not directory.is_dir():
        return found
    for folder in sorted(p for p in directory.iterdir() if p.is_dir() and (p / "adapter.py").is_file()):
        try:
            adapter = _adapter_of(_import(folder))
        except Exception as exc:                         # an operator's code: any failure skips it
            logger.warning("adapter folder %s skipped: %s", folder.name, f"{type(exc).__name__}: {exc}"[:300])
            continue
        if adapter.name in found:
            logger.warning("adapter folder %s skipped: the name %s is already taken", folder.name, adapter.name)
            continue
        found[adapter.name] = adapter
        logger.info("adapter %s loaded from %s", adapter.name, folder.name)
    return found


_REGISTRY: dict[str, Adapter] | None = None
_REGISTRY_LOCK = threading.Lock()


def registry() -> dict[str, Adapter]:
    """The installed adapters, read from PLATFORM_ADAPTERS_DIR the first time they are needed: once, even when
    calls arrive together (an adapter's module state, its own locks and pacing, must exist once)."""
    global _REGISTRY
    if _REGISTRY is None:
        with _REGISTRY_LOCK:
            if _REGISTRY is None:
                _REGISTRY = load(Path(os.environ.get("PLATFORM_ADAPTERS_DIR") or ADAPTERS_DIR_DEFAULT))
    return _REGISTRY


def get(kind: str) -> Adapter | None:
    """The adapter of a connection kind, or None (a built-in kind, or an adapter no longer installed)."""
    return registry().get(kind)


def reset() -> None:
    """Forget the loaded adapters: the next use reads the folder again."""
    global _REGISTRY
    _REGISTRY = None


# Calling an adapter

class _UntilDeadline:
    """A response that raises EndpointTimeout on a read once the deadline has passed (a stream that trickles
    resets the socket's own timeout on every chunk)."""

    def __init__(self, response, deadline: float, label: str):
        self._response, self._deadline, self._label = response, deadline, label

    def _check(self):
        if time.monotonic() > self._deadline:
            from aisc_plugin_interface import connections as client
            self._response.close()
            raise client.EndpointTimeout(f"{self._label}: the answer was still coming at the deadline")

    def read(self, *args):
        self._check()
        return self._response.read(*args)

    def readline(self, *args):
        self._check()
        return self._response.readline(*args)

    def __iter__(self):
        while True:
            line = self.readline()
            if not line:
                return
            yield line

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._response.close()
        return False

    def __getattr__(self, name):                         # status, headers, getheader, close, ...
        return getattr(self._response, name)


def guarded_open(allowed_hosts: list[str] | None, denied_addresses: list[str] | None,
                 deadline: float | None = None) -> Callable:
    """The `open(request, timeout=None)` an adapter reaches its system with: urllib's, under the same rules as
    the plugins' client (the project's allowed hosts, private and denied addresses refused on the URL and on
    the address actually connected), redirects not followed. `request` is a URL or a urllib Request; the
    response is returned unread, so a stream can be read as it comes. With a `deadline` (time.monotonic()), no
    connection or read goes past it, whatever timeout the adapter asks for (or none): EndpointTimeout."""
    import socket
    import urllib.error

    from aisc_plugin_interface import connections as client

    def open(request, timeout=None):
        url = request if isinstance(request, str) else request.full_url
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                raise client.EndpointTimeout("no time left before the caller's deadline; not sent")
            timeout = left if timeout is None else min(timeout, left)
        hosts = allowed_hosts if allowed_hosts is not None else client.allowed_hosts_from_env()
        client.guard_url(url, hosts, denied_addresses)
        try:
            with client._Policy(hosts, denied_addresses):
                response = client._OPENER.open(request, timeout=timeout)
        except client._Redirected as exc:
            raise client.EndpointBadResponse(f"the system answered with a redirect ({exc.code}),"
                                             " which is not followed") from None
        except (TimeoutError, socket.timeout):
            raise client.EndpointTimeout(f"no answer within {timeout:.0f}s" if timeout else "no answer") from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise client.EndpointTimeout(f"no answer within {timeout:.0f}s" if timeout else "no answer") from None
            raise
        return response if deadline is None else _UntilDeadline(response, deadline, urllib.parse.urlsplit(url).netloc)
    return open


def _error_classes() -> dict:
    from aisc_plugin_interface import connections as client
    return {"auth": client.EndpointAuthError, "not_found": client.EndpointNotFound,
            "timeout": client.EndpointTimeout, "bad_response": client.EndpointBadResponse}


_LIMITERS: dict[str, object] = {}
_LIMITERS_LOCK = threading.Lock()


def limiter(adapter: Adapter):
    """The adapter's limit on calls at once (an anyio CapacityLimiter, waited for without holding a thread),
    shared by every run and project; None when the adapter sets none."""
    if adapter.max_concurrent is None:
        return None
    import anyio

    with _LIMITERS_LOCK:
        key = f"{adapter.name}/{adapter.max_concurrent}"
        if key not in _LIMITERS:
            _LIMITERS[key] = anyio.CapacityLimiter(adapter.max_concurrent)
        return _LIMITERS[key]


def call(adapter: Adapter, connection: dict, input, history: list, params: dict, *, allowed_hosts=None,
         denied_addresses=None, deadline: float):
    """One question through `adapter`, as the interface's Answer. `connection` is {name, label, base_url,
    timeout_s, settings, secrets}; `deadline` (time.monotonic()) is when the caller stops waiting: the opener
    the adapter gets goes no further. An exception with `code` "refused" is a refusal; with auth, not_found,
    timeout or bad_response the matching interface error; anything else an EndpointError. Every secret value is
    taken out of the answer and of the message. The adapter's max_concurrent is the caller's to wait for
    (limiter), before a thread runs this."""
    from aisc_plugin_interface import connections as client
    from platform_service import connection_facade

    label = connection.get("label") or connection.get("name") or adapter.name
    secrets = [v for v in (connection.get("secrets") or {}).values() if v]
    started = time.monotonic()
    try:
        text = adapter.call(connection, input, history, params,
                            guarded_open(allowed_hosts, denied_addresses, deadline))
    except client.EndpointError as exc:                   # the opener's own: blocked, redirected, timed out
        raise type(exc)(connection_facade.scrub(f"{label}: {exc}", secrets), status=exc.status) from None
    except Exception as exc:                              # the adapter's: mapped by its code
        code = getattr(exc, "code", None)
        message = connection_facade.scrub(f"{label}: {exc}", secrets)
        if code == "refused":
            return client.Answer(text=None, refused=True, refusal_reason=connection_facade.scrub(str(exc), secrets),
                                 latency_ms=int((time.monotonic() - started) * 1000))
        status = getattr(exc, "status", None)
        status = status if isinstance(status, int) and not isinstance(status, bool) else None
        raise _error_classes().get(code, client.EndpointError)(message, status=status) from None
    answer = client.Answer(text=text, latency_ms=int((time.monotonic() - started) * 1000))
    return connection_facade.scrub_answer(answer, secrets)
