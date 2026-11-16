"""Makes the services' own RabbitMQ accounts through the management API, then exits. Run by the one-shot
rabbitmq-setup on every start, once RabbitMQ is healthy, as the administrator account (RABBITMQ_DEFAULT_USER),
which is kept for operators and held by no service.

    aisc-engine   the engine backend (and its migration): sends test runs
    aisc-worker   the run worker and the declarations worker: takes them
    aisc-flower   Flower, the task monitor (profile inspect)

None is tagged administrator (or monitoring, or management): each may use the default virtual host and nothing
else. Each password is written again on every start, from RABBITMQ_<SERVICE>_PASSWORD, so an install made before
the accounts existed gets them on its next start and a password renewed by `secrets --rotate` reaches RabbitMQ.
Queues and the messages in them belong to the virtual host, not to an account: none is touched here.

Standard library only (the one-shot runs a plain Python image). A password is never printed.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.request
from collections.abc import Callable
from urllib.parse import quote

#: the default virtual host, where Celery's queues are
VHOST = "/"

#: account name to the variable that holds its password
SERVICES = {
    "aisc-engine": "RABBITMQ_ENGINE_PASSWORD",
    "aisc-worker": "RABBITMQ_WORKER_PASSWORD",
    "aisc-flower": "RABBITMQ_FLOWER_PASSWORD",
}


def wanted_users() -> dict[str, dict]:
    """Every service account, with the variable of its password, no tag, and full rights on the default virtual
    host only (Celery declares its own queues and exchanges there)."""
    return {name: {"password_env": env, "tags": "", "configure": ".*", "write": ".*", "read": ".*"}
            for name, env in SERVICES.items()}


def sender(base_url: str, admin: tuple[str, str]) -> Callable[[str, dict], None]:
    """PUT of one JSON body to the management API, as the administrator; raises on any answer but 2xx."""
    token = base64.b64encode(f"{admin[0]}:{admin[1]}".encode()).decode()

    def put(path: str, body: dict) -> None:
        request = urllib.request.Request(base_url.rstrip("/") + path, data=json.dumps(body).encode(), method="PUT",
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Basic {token}"})
        with urllib.request.urlopen(request, timeout=10) as answer:
            if not 200 <= answer.status < 300:
                raise RuntimeError(f"RabbitMQ answered {answer.status} to PUT {path}")

    return put


def apply(base_url: str, admin: tuple[str, str], users: dict, put: Callable[[str, dict], None] | None = None
          ) -> list[str]:
    """Each account with its password from the environment, then its rights on the default virtual host; the
    names written. A password variable that is unset or empty stops it before anything is sent."""
    missing = [spec["password_env"] for spec in users.values() if not os.environ.get(spec["password_env"])]
    if missing:
        raise SystemExit(f"rabbitmq-setup: {', '.join(missing)} not set: run scripts/secrets.sh first")
    put = put or sender(base_url, admin)
    vhost = quote(VHOST, safe="")
    written = []
    for name, spec in users.items():
        put(f"/api/users/{quote(name, safe='')}", {"password": os.environ[spec["password_env"]], "tags": spec["tags"]})
        put(f"/api/permissions/{vhost}/{quote(name, safe='')}",
            {"configure": spec["configure"], "write": spec["write"], "read": spec["read"]})
        written.append(name)
    return written


def main() -> int:
    base_url = os.environ.get("RABBITMQ_MANAGEMENT_URL", "http://rabbitmq:15672")
    admin = (os.environ.get("RABBITMQ_ADMIN_USER", ""), os.environ.get("RABBITMQ_ADMIN_PASSWORD", ""))
    if not all(admin):
        print("rabbitmq-setup: RABBITMQ_ADMIN_USER and RABBITMQ_ADMIN_PASSWORD must be set", file=sys.stderr)
        return 1
    for name in apply(base_url, admin, wanted_users()):
        print(f"RabbitMQ account {name} ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
