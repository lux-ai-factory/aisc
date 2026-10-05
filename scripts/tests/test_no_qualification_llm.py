"""qualification-llm is gone (code review 2026-10-05): a LiteLLM relay holding provider keys and
relaying any model a caller named, with no caller. Nothing in qualification read LLM_SERVICE_URL,
and the card agent talks to its model through BAF. Reads the files only."""
import yaml

from conftest import ROOT

COMPOSE = ROOT / "docker-compose.development.yml"


def test_no_service_and_nothing_points_at_it():
    services = yaml.safe_load(COMPOSE.read_text())["services"]
    assert "qualification-llm" not in services
    text = COMPOSE.read_text()
    assert "qualification-llm" not in text and "LLM_SERVICE_URL" not in text


def test_no_token_or_model_for_it():
    assert "QUALIFICATION_WEB_TO_LLM_TOKEN" not in (ROOT / "scripts/secrets.sh").read_text()
    assert "QUALIFICATION_LLM_MODEL" not in (ROOT / "env.development").read_text()


def test_its_code_is_gone():
    assert not (ROOT / "apps/qualification/services/llm").exists()
