"""Each install has its own run-uid pools: the kernel counts a uid's processes across every container on the
host, so two installs whose workers leased the same uid would share one test's process cap, and one install's
plugin could stop the other's from starting a process. start writes the install's pools into env.local once (an
install that has none gets them on its next start, nothing else changes) and compose reads them from there."""
import pytest
import yaml

from conftest import ROOT, aisc_py

FILES = ["docker-compose.development.yml", "docker-compose.engine-standalone.yml", "docker-compose.staging.yml"]
RUN_WORKER, DECLARATIONS_WORKER = "aisc-eval-worker", "aisc-eval-declarations-worker"
NAMES = ("PLUGIN_RUN_UIDS", "PLUGIN_DECLARATIONS_RUN_UIDS")


def pool(value: str) -> range:
    first, _, last = value.partition("-")
    return range(int(first), int(last) + 1)


def uids(settings: dict) -> set[int]:
    return {uid for name in NAMES for uid in pool(settings[name])}


def test_an_install_without_an_id_keeps_the_pools_it_always_had():
    m = aisc_py()
    assert m.run_uid_settings({}, "", []) == {"PLUGIN_RUN_UIDS": "10100-10199",
                                               "PLUGIN_DECLARATIONS_RUN_UIDS": "10200-10209"}


def test_an_installs_pools_follow_its_id_and_stay_above_the_images_users():
    m = aisc_py()
    first = m.run_uid_settings({}, "063319", [])
    assert first == m.run_uid_settings({}, "063319", []), "the same install gets the same pools"
    assert min(uids(first)) > 10003 and max(uids(first)) < 65534
    # the run worker's pool keeps its hundred uids, the declarations worker's its ten, never overlapping
    assert len(pool(first["PLUGIN_RUN_UIDS"])) == 100 and len(pool(first["PLUGIN_DECLARATIONS_RUN_UIDS"])) == 10
    assert not set(pool(first["PLUGIN_RUN_UIDS"])) & set(pool(first["PLUGIN_DECLARATIONS_RUN_UIDS"]))


@pytest.mark.parametrize("ids", [("063319", "a1b2c3"), ("000001", "000001"), ("", "000000")])
def test_two_installs_on_one_host_never_share_a_uid(ids):
    """The second start sees the first install's worker (Docker's listing) and moves off its pools, even when
    both ids point at the same place."""
    m = aisc_py()
    first = m.run_uid_settings({}, ids[0], [])
    second = m.run_uid_settings({}, ids[1], [first["PLUGIN_RUN_UIDS"]])
    assert not uids(first) & uids(second)


def test_pools_already_in_env_local_are_kept():
    m = aisc_py()
    kept = {"PLUGIN_RUN_UIDS": "20000-20099", "PLUGIN_DECLARATIONS_RUN_UIDS": "20100-20109"}
    assert m.run_uid_settings(kept, "063319", []) == {}


def test_other_installs_pools_come_from_their_workers_labels():
    """A worker made before installs had pools of their own carries no label: it leases the old default pool."""
    m = aisc_py()
    listing = "aisc-aaaaaa\t20096-20195\naisc-063319\t30000-30099\naisc\t\n"
    assert m.other_installs_run_uids(listing, "aisc-063319") == ["20096-20195", "10100-10199"]


@pytest.mark.parametrize("name", FILES)
def test_compose_reads_each_workers_pool_from_the_install_settings(name):
    services = yaml.safe_load((ROOT / name).read_text())["services"]
    run, declarations = services[RUN_WORKER], services[DECLARATIONS_WORKER]
    assert run["environment"]["PLUGIN_RUN_UIDS"] == "${PLUGIN_RUN_UIDS:-10100-10199}"
    assert declarations["environment"]["PLUGIN_RUN_UIDS"] == "${PLUGIN_DECLARATIONS_RUN_UIDS:-10200-10209}"
    # how another install's start sees which pool this one's worker leases from
    assert run["labels"]["aisc.run-uids"] == "${PLUGIN_RUN_UIDS:-10100-10199}"


def test_start_writes_the_pools_with_the_ports_it_keeps_in_env_local():
    source = (ROOT / "scripts/aisc/stack.py").read_text()
    step = source[source.index("def start_steps"):source.index("write_beside(LOCAL")]
    assert "run_uid_settings(" in step and "other_installs_run_uids(" in step
