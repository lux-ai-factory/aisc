"""WP2 (pipeline-2026-09-23): the engine no longer calls the platform for
versions, so aisc-backend loses the PLATFORM_URL that c0f460e gave it. A text
check of docker-compose.development.yml; nothing is started."""
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


def test_wp2_aisc_backend_has_no_platform_url():
    block = _service_block(COMPOSE.read_text(), "aisc-backend")
    assert block, "aisc-backend service found"
    assert not [l for l in block if l.strip().startswith("PLATFORM_URL:")]
