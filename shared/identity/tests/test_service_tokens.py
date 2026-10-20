"""identify(): which caller a service token belongs to, or why it is refused.

The sidecars carry a copy of this module (scripts/tests/test_service_tokens.py
keeps the copies identical), so every service-to-service door in the stack
refuses and admits by these same rules.
"""
import pytest

from aisc_identity.service_tokens import ServiceRefused, identify

CALLERS = {"card_agent": "PLATFORM_CARD_AGENT_TOKEN", "risk_mapper": "PLATFORM_RISK_MAPPER_TOKEN"}
ENV = {"PLATFORM_CARD_AGENT_TOKEN": "card-token", "PLATFORM_RISK_MAPPER_TOKEN": "mapper-token"}


def refused(given, callers=CALLERS, env=ENV):
    with pytest.raises(ServiceRefused) as caught:
        identify(given, callers, env)
    return caught.value.status, caught.value.detail


def test_each_token_names_its_own_caller():
    assert identify("card-token", CALLERS, ENV) == "card_agent"
    assert identify("mapper-token", CALLERS, ENV) == "risk_mapper"


@pytest.mark.parametrize("given", [None, "", "card-token ", "CARD-TOKEN", "card-tokenx", "other"])
def test_anything_else_is_401(given):
    assert refused(given) == (401, "a service token is needed")


@pytest.mark.parametrize("unset,other", [("card_agent", "risk_mapper"), ("risk_mapper", "card_agent")])
def test_an_unset_token_lets_nobody_in_under_it_and_tells_nobody(unset, other):
    for env in ({**ENV, CALLERS[unset]: ""}, {k: v for k, v in ENV.items() if k != CALLERS[unset]}):
        assert identify(ENV[CALLERS[other]], CALLERS, env) == other
        assert refused(ENV[CALLERS[unset]], env=env) == (401, "a service token is needed")
        assert refused("", env=env) == (401, "a service token is needed")


def test_no_token_set_at_all_closes_the_door():
    closed = (503, "this service is closed: its service tokens are not set")
    assert refused("card-token", env={}) == closed
    assert refused("card-token", callers={}) == closed


def test_two_callers_with_one_value_close_the_door():
    env = {**ENV, "PLATFORM_RISK_MAPPER_TOKEN": "card-token"}
    assert refused("card-token", env=env) == (503, "this service is closed: its service tokens must differ")


def test_every_token_is_compared_whatever_the_first_answer(monkeypatch):
    import aisc_identity.service_tokens as module

    compared = []
    real = module.hmac.compare_digest

    def counting(a, b):
        compared.append(b)
        return real(a, b)

    monkeypatch.setattr(module.hmac, "compare_digest", counting)
    identify("card-token", CALLERS, ENV)
    assert len(compared) == len(CALLERS)
