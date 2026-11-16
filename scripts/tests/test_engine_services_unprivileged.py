"""The engine's services start without installing code, read every bind mount read-only, and the two images that
keep root (the eval worker's, which switches to a uid per run, and the plugin publisher's, which builds as another
user) hold only the capabilities they use. The eval worker's image runs two services, the run worker and the
declarations worker (manifests and form hooks, also run as a uid of their own): both keep the same capabilities.
The engine images install from their locks only.

Read-only: `docker compose config` on copies of the compose files, and the Dockerfiles as text.
"""

import compose_cfg
from conftest import ROOT

#: one-shots that must write to what they mount: the immudb signing key and the MinIO volume's owner
WRITES_ITS_MOUNT = ("immudb-key", "minio-data-owner")


def _command(service: dict) -> str:
    return " ".join(service.get("command") or []) + " " + " ".join(service.get("entrypoint") or [])


def test_no_service_installs_code_when_it_starts(tmp_path):
    s = compose_cfg.config(tmp_path, "inspect")["services"]
    installs = sorted(n for n, v in s.items() if "pip install" in _command(v))
    assert installs == [], f"these services install code each time they start: {installs}"


def test_every_bind_mount_is_read_only(tmp_path):
    s = compose_cfg.config(tmp_path, "inspect")["services"]
    writable = sorted((n, m["source"]) for n, v in s.items() for m in v.get("volumes", [])
                      if m["type"] == "bind" and not m.get("read_only") and n not in WRITES_ITS_MOUNT)
    assert writable == []


#: the services of the eval worker's image, each running plugin code as a run user
EVAL_WORKERS = ("aisc-eval-worker", "aisc-eval-declarations-worker")


def test_the_two_root_services_keep_only_the_capabilities_they_use(tmp_path):
    s = compose_cfg.config(tmp_path)["services"]
    publisher = s["plugin-publisher"]
    for name in EVAL_WORKERS:
        worker = s[name]
        assert worker.get("cap_drop") == ["ALL"], f"{name} keeps every default capability"
        assert set(worker.get("cap_add") or []) == {"SETUID", "SETGID", "KILL", "CHOWN", "FOWNER", "DAC_OVERRIDE",
                                                    "NET_ADMIN"}, name
    assert publisher.get("cap_drop") == ["ALL"], "the plugin publisher keeps every default capability"
    assert "FOWNER" not in (publisher.get("cap_add") or [])


def test_the_engine_images_build_only_from_their_locks():
    unlocked = [f for f in ("apps/backend/Dockerfile", "apps/eval/Dockerfile")
                if "--upgrade-package" in (ROOT / f).read_text()]
    assert unlocked == [], f"these images resolve a package past their lock at build: {unlocked}"
    assert "RUN npm ci" in (ROOT / "apps/webapp/Dockerfile").read_text(), "the webapp image installs with npm install"
