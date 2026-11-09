"""The chart assistant service. One caller, the results dashboard, by its token; it asks on behalf of a person the
dashboard has already admitted to the project. Behind it: the model the project chose for the chart assistant (from
the platform, as the other agents get theirs) and the project's mock database. No project database credential is held
here (R1): Settings has none, and a mock database URL naming a project database is refused."""
from __future__ import annotations

import hmac
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Callable

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from chart_assistant.description import READERS, for_model
from chart_assistant.loop import BudgetSpent, Change, Conversation, Proposal, Removal

HEADER = "x-aisc-service-token"
#: conversations live in memory: the least recently used go beyond this many, and any idle longer than this
MAX_CONVERSATIONS = 500
MAX_IDLE_SECONDS = 6 * 3600
PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class Settings:
    dashboard_token: str
    platform_url: str
    platform_token: str
    mock_database_url: str

    @classmethod
    def from_env(cls, env=os.environ) -> "Settings":
        url = env.get("MOCK_DATABASE_URL", "")
        if re.search(r"/project_[0-9a-f]{32}\b", url):
            raise ValueError("MOCK_DATABASE_URL names a project database: the assistant may only reach mock databases")
        return cls(dashboard_token=env.get("ASSISTANT_DASHBOARD_TOKEN", ""),
                   platform_url=env.get("PLATFORM_URL", "http://platform:8000"),
                   platform_token=env.get("PLATFORM_CHART_ASSISTANT_TOKEN", ""), mock_database_url=url)


@dataclass
class _Held:
    """A conversation, its project, and the lock that lets one message at a time change it (FastAPI runs the
    endpoints in a thread pool)."""
    pid: str
    conversation: Conversation
    used: float
    lock: threading.Lock = field(default_factory=threading.Lock)


class ModelUnavailable(RuntimeError):
    pass


#: a platform or model that cannot be reached, or whose reply is not the JSON it should be
_UNREADABLE = (httpx.HTTPError, KeyError, IndexError, TypeError, AttributeError, ValueError)


def platform_model(settings: Settings) -> Callable[[str], Callable]:
    """The project's choice for the chart assistant, resolved on the platform's internal route, as an OpenAI-style chat
    call: (messages, tools) -> the assistant message."""
    def model_for(pid: str):
        try:
            r = httpx.get(f"{settings.platform_url}/internal/projects/{pid}/llm/chart_assistant",
                          headers={HEADER: settings.platform_token}, timeout=10)
            choice = r.json() if r.status_code == 200 else {}
            configured = choice.get("configured")
        except _UNREADABLE as exc:
            raise ModelUnavailable(f"the platform could not say which model to use: {type(exc).__name__}") from exc
        if not configured:
            raise ModelUnavailable("no model is chosen for the chart assistant in this project (Manage > Connectivity)")
        base = (choice.get("base_url") or choice.get("chat_base_url") or "").rstrip("/")
        if not base:
            raise ModelUnavailable(f"{choice.get('provider')} has no chat address the assistant can use")
        if choice.get("provider") == "ollama" and not base.endswith("/v1"):
            base += "/v1"
        headers = {"Authorization": f"Bearer {choice['api_key']}"} if choice.get("api_key") else {}

        def call(messages, tools):
            try:
                reply = httpx.post(f"{base}/chat/completions", headers=headers, timeout=120,
                                   json={"model": choice["model"], "messages": messages, "tools": tools,
                                         "tool_choice": "required"})
                if reply.status_code != 200:
                    raise ModelUnavailable(f"the model answered {reply.status_code}")
                message = reply.json()["choices"][0]["message"]
                return {k: message[k] for k in ("role", "content", "tool_calls")
                        if message.get(k) is not None} | {"role": "assistant"}
            except _UNREADABLE as exc:
                raise ModelUnavailable(f"the model could not be reached or gave no answer: {type(exc).__name__}") from exc
        return call
    return model_for


def create_app(settings: Settings | None = None, *, model_for=None, mocks=None) -> FastAPI:
    settings = settings or Settings.from_env()
    if mocks is None:
        from chart_assistant.mock_store import MockStore
        mocks = MockStore(settings.mock_database_url)
    model_for = model_for or platform_model(settings)
    conversations: OrderedDict[str, _Held] = OrderedDict()
    conversations_lock = threading.Lock()
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def caller(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if not settings.dashboard_token:
            return JSONResponse({"detail": "the assistant has no caller token set"}, status_code=503)
        given = request.headers.get(HEADER) or ""
        if not hmac.compare_digest(given.encode(), settings.dashboard_token.encode()):
            return JSONResponse({"detail": "not the dashboard"}, status_code=401)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"ok": True}

    def known(cid: str) -> _Held:
        """The conversation of that id, or 404. It does not check whose it is: the dashboard, the only caller, keeps
        each conversation id in the person's session with its dashboard and checks the project validate returns."""
        with conversations_lock:
            held = conversations.get(cid)
            if held is None or time.monotonic() - held.used > MAX_IDLE_SECONDS:
                conversations.pop(cid, None)
                raise HTTPException(404, "no such conversation")
            held.used = time.monotonic()
            conversations.move_to_end(cid)
            return held

    def keep(cid: str, held: _Held) -> None:
        with conversations_lock:
            now = time.monotonic()
            for old in [c for c, h in conversations.items() if now - h.used > MAX_IDLE_SECONDS]:
                del conversations[old]
            while len(conversations) >= MAX_CONVERSATIONS:
                conversations.popitem(last=False)
            conversations[cid] = held

    @app.post("/v1/projects/{pid}/conversations", status_code=201)
    def start(pid: str, body: dict):
        if not PID.match(pid):
            raise HTTPException(422, "not a project id")
        description = body.get("description") or {}
        try:
            model = model_for(pid)
        except ModelUnavailable as exc:
            raise HTTPException(409, str(exc)) from exc
        run = mocks.runner(pid, description)
        cid = secrets.token_urlsafe(18)
        keep(cid, _Held(pid=pid, used=time.monotonic(),
                        conversation=Conversation(description=for_model(description), readers=READERS, model=model,
                                                  run_on_mock=run)))
        return {"conversation": cid}

    def shown(p: Proposal) -> dict:
        out = {"id": p.number, "sql": p.sql, "chart": p.chart, "description": p.description, "fingerprint": p.fingerprint,
               "mock": {"columns": p.mock["columns"], "rows": p.mock["rows"][:200]}, "mock_data": True}
        if p.replaces is not None:
            out["replaces"] = {"chart": p.replaces, "title": p.replaces_title}
        return out

    @app.post("/v1/conversations/{cid}/messages")
    def message(cid: str, body: dict):
        held = known(cid)
        text = str(body.get("text") or "").strip()[:4000]
        if not text:
            raise HTTPException(422, "say what chart you want")
        try:
            charts = body.get("charts") if isinstance(body.get("charts"), list) else []
            with held.lock:
                answer = held.conversation.ask(text, charts=charts[:50])
        except BudgetSpent as exc:
            raise HTTPException(429, str(exc)) from exc
        except ModelUnavailable as exc:
            raise HTTPException(502, str(exc)) from exc
        if isinstance(answer, Proposal):
            return {"proposal": shown(answer)}
        if isinstance(answer, Change):
            return {"change": {"chart": answer.chart, "title": answer.title, "changes": answer.changes}}
        if isinstance(answer, Removal):
            return {"remove": [{"chart": number, "title": title} for number, title in answer.charts]}
        return {"question": answer}

    @app.post("/v1/conversations/{cid}/validate")
    def validate(cid: str, body: dict):
        held = known(cid)
        pid = held.pid
        with held.lock:
            same = [p for p in held.conversation.proposals if p.fingerprint == body.get("fingerprint")]
        # the proposal the person clicked; without its number, the latest with that query
        chosen = next((p for p in same if p.number == body.get("proposal")), None) if "proposal" in body else \
            (same[-1] if same else None)
        if chosen is None:
            raise HTTPException(409, "no proposal of this conversation has that fingerprint")
        return {"project": pid, "sql": chosen.sql, "chart": chosen.chart, "description": chosen.description,
                "fingerprint": chosen.fingerprint, "replaces": chosen.replaces}

    return app


def __getattr__(name):
    if name == "app":
        return create_app()
    raise AttributeError(name)
