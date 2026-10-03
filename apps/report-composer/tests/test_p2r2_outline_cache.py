"""The outline's block-types cache.

1. Single flight: while one fetch is in flight, other requests wait for it (or take the older list), they
   never start their own.
2. A renderer restart with new block types is seen at once: every uncached block-types call (the palette,
   validate, save, preview, generate, presets) puts its fresh answer into the outline cache.
3. The short limit of the outline's call is a deadline for the whole call, not for each read: a renderer that
   sends its answer byte by byte cannot hold the request past it.
"""
import copy
import socket
import threading
import time

import pytest

from conftest import IDS, need, new_layout
from v2_fakes import FakeRendererV2, unique, v2blk

PLACEHOLDER = "Write this section."


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def cache(fetch, clock=time.monotonic, **kw):
    Cache = need("report_composer.renderer_calls", "BlockTypesCache")
    return Cache(fetch, now=clock, **kw)


def run_all(fn, n):
    out, threads = [None] * n, []
    for i in range(n):
        def work(i=i):
            out[i] = fn()
        threads.append(threading.Thread(target=work))
    for t in threads:
        t.start()
    return threads, out


# 1. single flight


def test_p2r2_1_concurrent_requests_on_an_empty_cache_make_one_fetch():
    calls, release = [], threading.Event()

    def fetch():
        calls.append(1)
        release.wait(5)
        return [{"type_id": "x"}]

    c = cache(fetch, ttl=60, failure_ttl=10, wait=5)
    threads, out = run_all(c.get, 8)
    time.sleep(0.3)                      # every thread is inside get() by now
    release.set()
    for t in threads:
        t.join(5)
    assert len(calls) == 1
    assert out == [[{"type_id": "x"}]] * 8      # the others waited for the one fetch


def test_p2r2_1_while_a_refresh_is_in_flight_the_others_take_the_older_list_at_once():
    clock, calls, release = Clock(), [], threading.Event()
    answers = iter([[{"type_id": "old"}], [{"type_id": "new"}]])

    def fetch():
        calls.append(1)
        if len(calls) == 2:
            release.wait(5)
        return next(answers)

    c = cache(fetch, clock, ttl=60, failure_ttl=10, wait=5)
    assert c.get() == [{"type_id": "old"}]
    clock.t += 61                                     # expired: the next get refreshes
    refresher = threading.Thread(target=c.get)
    refresher.start()
    time.sleep(0.2)
    started = time.monotonic()
    assert c.get() == [{"type_id": "old"}]            # no second fetch, no wait
    assert time.monotonic() - started < 0.5
    release.set()
    refresher.join(5)
    assert len(calls) == 2
    assert c.get() == [{"type_id": "new"}]


def test_p2r2_1_waiters_give_up_after_their_wait_and_use_the_fallback():
    calls, release = [], threading.Event()

    def fetch():
        calls.append(1)
        release.wait(5)
        return [{"type_id": "x"}]

    c = cache(fetch, ttl=60, failure_ttl=10, wait=0.3)
    first = threading.Thread(target=c.get)
    first.start()
    time.sleep(0.1)
    started = time.monotonic()
    assert c.get() == []                              # the fixed prose list
    assert time.monotonic() - started < 1.5
    release.set()
    first.join(5)
    assert len(calls) == 1


class SlowCounting(FakeRendererV2):
    def __init__(self):
        super().__init__()
        self.type_calls = 0
        self.lock = threading.Lock()

    def block_types(self):
        with self.lock:
            self.type_calls += 1
        time.sleep(0.5)
        return super().block_types()


@pytest.mark.db
@pytest.mark.usefixtures("clean_layouts")
def test_p2r2_1_concurrent_outline_requests_make_one_block_types_call(make_client, auth):
    fake = SlowCounting()
    client = make_client(fake)
    blocks = [v2blk("chapter", title="One"), v2blk("ai_card")]
    lay = new_layout(client, auth, name=unique("Flight"), system_id=IDS["A_V2"], blocks=blocks)
    client.app.state.outline_block_types = None       # an empty cache, as after a start
    fake.type_calls = 0
    headers = auth("alice")

    def post():
        return client.post(f"/api/p/alpha/layouts/{lay['id']}/outline", json={"blocks": blocks}, headers=headers)

    threads, out = run_all(post, 6)
    for t in threads:
        t.join(10)
    assert [r.status_code for r in out] == [200] * 6
    assert fake.type_calls == 1


# 2. a renderer restart is seen at once


def test_p2r2_2_a_fresh_list_put_into_the_cache_is_used_without_a_fetch():
    clock, calls = Clock(), []
    c = cache(lambda: calls.append(1) or [{"type_id": "old"}], clock, ttl=60, failure_ttl=10)
    c.get()
    c.put([{"type_id": "new"}])
    assert c.get() == [{"type_id": "new"}]
    assert len(calls) == 1
    clock.t += 59
    assert c.get() == [{"type_id": "new"}]            # a put starts a new TTL
    assert len(calls) == 1


PLUGIN_TYPE = {
    "type_id": "auditor_notes", "title": "Auditor notes", "contract_version": 1, "description": "A plugin block.",
    "new_instance_options": {},
    "options_schema": {"type": "object", "additionalProperties": False, "properties": {
        "title": {"type": "string", "maxLength": 200, "title": "Section title", "description": "Heading."},
        "notes": {"type": "string", "title": "Notes", "description": "The auditor's notes."}}},
    "default_options": {"title": "", "notes": ""}}


class Restartable(FakeRendererV2):
    """Gains a plugin block type when `restarted` is set, as a renderer restarted with a new plugin."""

    def __init__(self):
        super().__init__()
        self.restarted = False

    def block_types(self):
        extra = [copy.deepcopy(PLUGIN_TYPE)] if self.restarted else []
        return super().block_types() + extra


def _outline_unwritten(client, auth, lay, blocks):
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/outline", json={"blocks": blocks}, headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    return [item["unwritten"] for item in r.json()["outline"]]


@pytest.mark.db
@pytest.mark.usefixtures("clean_layouts")
@pytest.mark.parametrize("call", ["palette", "validate"])
def test_p2r2_2_after_a_restart_the_next_block_types_call_refreshes_the_outline(make_client, auth, call):
    fake = Restartable()
    client = make_client(fake)
    lay = new_layout(client, auth, name=unique("Restart"), system_id=IDS["A_V2"], blocks=[v2blk("cover")])
    notes = [v2blk("auditor_notes", notes=PLACEHOLDER)]
    assert _outline_unwritten(client, auth, lay, notes) == [[]]      # unknown type: the fixed list
    fake.restarted = True
    if call == "palette":
        r = client.get("/api/block-types", headers=auth("alice"))
    else:
        r = client.post(f"/api/p/alpha/layouts/{lay['id']}/validate", headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert _outline_unwritten(client, auth, lay, notes) == [["notes"]]


# 3. a deadline for the whole call


def _drip_server(whole: bytes, drip: bytes, gap: float):
    """A server that answers each connection with `whole` at once, then `drip` one byte every `gap` seconds."""
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(4)
    server.settimeout(0.2)
    stop = threading.Event()

    def serve():
        while not stop.is_set():
            try:
                conn, _ = server.accept()
            except OSError:
                continue
            with conn:
                try:
                    conn.recv(65536)
                    conn.sendall(whole)
                    for byte in drip:
                        if stop.is_set():
                            break
                        conn.sendall(bytes([byte]))
                        time.sleep(gap)
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    return server, stop


BODY = b'[{"type_id": "x"}]' + b" " * 300
HEAD = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n" % len(BODY)


@pytest.mark.parametrize("what", ["body", "headers"])
def test_p2r2_3_a_renderer_dripping_its_answer_cannot_hold_the_call_past_the_deadline(what):
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    Timeout = need("report_composer.renderer_client", "RendererTimeout")
    if what == "body":
        server, stop = _drip_server(HEAD + b"\r\n", BODY, 0.05)
    else:
        server, stop = _drip_server(b"", HEAD + b"X-Pad: " + b"a" * 300 + b"\r\n\r\n" + BODY, 0.05)
    try:
        client = Http(f"http://127.0.0.1:{server.getsockname()[1]}", token="t" * 32, quick_timeout=0.5)
        started = time.monotonic()
        with pytest.raises(Timeout):
            client.block_types_quick()
        assert time.monotonic() - started < 1.5          # the whole answer would take over 15 s
    finally:
        stop.set()
        server.close()


def test_p2r2_3_a_prompt_answer_within_the_deadline_still_comes_through():
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    body = b'[{"type_id": "x"}]'
    payload = (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n" % len(body)) + body
    server, stop = _drip_server(payload, b"", 0.0)
    try:
        client = Http(f"http://127.0.0.1:{server.getsockname()[1]}", token="t" * 32, quick_timeout=2.0)
        assert client.block_types_quick() == [{"type_id": "x"}]
    finally:
        stop.set()
        server.close()
