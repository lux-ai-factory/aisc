"""Part 2, fix round 1, finding 1 of 14-verify-part2.md: the outline route asked the renderer for its block types
on every request, with the client's 120 s timeout. Now the block types are cached for a short time, and the
outline's own call uses a short timeout; a slow or failing renderer gives the fixed prose list (DV12-6)."""
import socket
import time

import pytest

from conftest import IDS, need, new_layout
from v2_fakes import FakeRendererV2, unique, v2blk


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def cache(fetch, clock, **kw):
    Cache = need("report_composer.renderer_calls", "BlockTypesCache")
    return Cache(fetch, now=clock, **kw)


def test_p2r1_1_block_types_are_fetched_once_within_the_ttl():
    calls, clock = [], Clock()
    c = cache(lambda: calls.append(1) or [{"type_id": "x"}], clock, ttl=60, failure_ttl=10)
    assert c.get() == [{"type_id": "x"}]
    clock.t += 59
    assert c.get() == [{"type_id": "x"}]
    assert len(calls) == 1


def test_p2r1_1_block_types_are_fetched_again_after_the_ttl():
    calls, clock = [], Clock()
    c = cache(lambda: calls.append(1) or [{"type_id": "x"}], clock, ttl=60, failure_ttl=10)
    c.get()
    clock.t += 61
    c.get()
    assert len(calls) == 2


def test_p2r1_1_a_failure_gives_the_empty_list_and_is_not_asked_again_at_once():
    Timeout = need("report_composer.renderer_client", "RendererTimeout")
    calls, clock = [], Clock()

    def fetch():
        calls.append(1)
        raise Timeout("no answer")

    c = cache(fetch, clock, ttl=60, failure_ttl=10)
    assert c.get() == []
    clock.t += 9
    assert c.get() == []
    assert len(calls) == 1          # a hung renderer is not asked again on every edit
    clock.t += 2
    c.get()
    assert len(calls) == 2          # but it is asked again soon, so a restarted renderer is picked up


def test_p2r1_1_any_renderer_error_falls_back():
    Unavailable = need("report_composer.renderer_client", "RendererUnavailable")
    Rejected = need("report_composer.renderer_client", "RendererRejected")
    for exc in (Unavailable("down"), Rejected(422)):
        def fetch(exc=exc):
            raise exc
        assert cache(fetch, Clock(), ttl=60, failure_ttl=10).get() == []


def test_p2r1_1_the_client_gives_up_quickly_on_a_hung_renderer():
    """A socket that accepts the connection but never answers: the outline's call ends after the short timeout."""
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    Timeout = need("report_composer.renderer_client", "RendererTimeout")
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(4)
        port = server.getsockname()[1]
        client = Http(f"http://127.0.0.1:{port}", token="t" * 32, quick_timeout=0.5)
        assert client.timeout == 120.0          # the other calls keep the long timeout
        started = time.monotonic()
        with pytest.raises(Timeout):
            client.block_types_quick()
        assert time.monotonic() - started < 5


def test_p2r1_1_the_quick_timeout_defaults_to_a_few_seconds():
    Http = need("report_composer.renderer_client", "HttpRendererClient")
    assert 0 < Http("http://renderer:8001", token="t" * 32).quick_timeout <= 5


# ── the route ────────────────────────────────────────────────────────────────


class Counting(FakeRendererV2):
    def __init__(self):
        super().__init__()
        self.type_calls = 0

    def block_types(self):
        self.type_calls += 1
        return super().block_types()


class Hung(FakeRendererV2):
    """The quick call times out; a call with the long timeout would hang, so it fails the test."""

    def __init__(self):
        super().__init__()
        self.quick_calls = 0
        self.slow = False

    def block_types_quick(self):
        from report_composer.renderer_client import RendererTimeout

        self.quick_calls += 1
        raise RendererTimeout("no answer within 2 s")

    def block_types(self):
        self.slow = True
        return super().block_types()


BLOCKS = [v2blk("chapter", title="One"), v2blk("ai_card")]


def outline(client, auth, lay):
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/outline", json={"blocks": BLOCKS}, headers=auth("alice"))
    assert r.status_code == 200, r.text
    return r.json()["outline"]


@pytest.mark.db
@pytest.mark.usefixtures("clean_layouts")
def test_p2r1_1_the_outline_route_asks_the_renderer_once_for_many_edits(make_client, auth):
    fake = Counting()
    client = make_client(fake)
    lay = new_layout(client, auth, name=unique("Cache"), system_id=IDS["A_V2"], blocks=BLOCKS)
    fake.type_calls = 0
    first = outline(client, auth, lay)
    for _ in range(4):
        assert outline(client, auth, lay) == first
    assert fake.type_calls == 1


@pytest.mark.db
@pytest.mark.usefixtures("clean_layouts")
def test_p2r1_1_a_hung_renderer_gives_the_fallback_outline_with_the_quick_call(make_client, auth):
    fake = Hung()
    client = make_client(fake)
    lay = new_layout(client, auth, name=unique("Hung"), system_id=IDS["A_V2"], blocks=BLOCKS)
    fake.slow = False
    got = outline(client, auth, lay)
    outline(client, auth, lay)
    assert [item.get("depth") for item in got] == [0, 1]      # indentation still works (DV12-6 fallback)
    assert fake.slow is False, "the outline used the call with the long timeout"
    assert fake.quick_calls == 1                               # the failure is remembered for a short time
