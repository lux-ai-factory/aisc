"""What aisc-backend may ask the platform: only whether a card target has a connection, with its own
engine token (never versions, ledger or connections). A text check of docker-compose.development.yml;
nothing is started."""
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.development.yml"


def _service_block(text: str, service: str) -> list[str]:
    lines, inside, block = text.splitlines(), False, []
    for line in lines:
        if line.startswith(f"  {service}:"):
            inside = True
            continue
        if inside:
            if line.startswith("  ") and not line.startswith("   ") and line.strip() and not line.lstrip().startswith("#"):
                break  # the next service
            block.append(line)
    return block


def test_aisc_backend_reaches_the_platform_only_to_ask_whether_a_target_is_connected():
    """aisc-backend has the platform's URL for one route, the card target's reachability, with its own
    engine token; it holds no ledger or connections token (it imports plugin code)."""
    block = _service_block(COMPOSE.read_text(), "aisc-backend")
    assert block, "aisc-backend service found"
    assert [line for line in block if line.strip() == "PLATFORM_URL: http://platform:8000"]
    tokens = {line.split(":")[0].strip() for line in block
              if line.strip().startswith("PLATFORM_") and line.split(":")[0].strip().endswith("_TOKEN")}
    assert tokens == {"PLATFORM_ENGINE_TOKEN"}
