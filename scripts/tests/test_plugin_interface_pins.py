"""The engine's Python packages (backend, eval worker, plugin-manager) ask for plugin interface 0.4.0 and their
locks take it from one wheel committed under each repo's vendor/, never from PyPI (whose latest, 0.3.0, has
no assesses, helpers or connections). The backend and the eval worker also take the plugin-manager and
aisc_identity from wheels under vendor/, so an image built from their Dockerfile alone holds this checkout's
code, not upstream's tag and not a compose mount.

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_plugin_interface_pins.py
"""

import hashlib
import re
import tomllib
import zipfile
from pathlib import Path

import pytest

from conftest import ROOT

INTERFACE = "aisc-plugin-interface"
INTERFACE_SRC = ROOT / "shared/plugin-interface"
WHEEL = "aisc_plugin_interface-0.4.0-py3-none-any.whl"
WHEEL_SOURCE = {"path": f"vendor/{WHEEL}"}

#: the three packages of the engine that name the interface
ENGINE_PACKAGES = ("apps/backend", "apps/eval", "shared/plugin-manager")
#: the two whose images are built from a Dockerfile
ENGINE_APPS = ("apps/backend", "apps/eval")

#: the other local packages the two apps take from vendor/: name, the folder its wheel is built from,
#: and the folder of its importable package inside that one
LOCAL_PACKAGES = {
    "aisc-plugin-manager": (ROOT / "shared/plugin-manager", "src/aisc_plugin_manager"),
    "aisc-identity": (ROOT / "shared/identity", "aisc_identity"),
}


def _toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def _name(requirement: str) -> str:
    return re.split(r"[\s<>=!~;\[(]", requirement, maxsplit=1)[0].strip().lower().replace("_", "-")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _local_wheel(name: str) -> str:
    """The wheel file name of a local package, from the version its own pyproject.toml gives."""
    folder, _ = LOCAL_PACKAGES[name]
    version = _toml(folder / "pyproject.toml")["project"]["version"]
    return f"{name.replace('-', '_')}-{version}-py3-none-any.whl"


def _source_files(package_dir: Path) -> dict[str, bytes]:
    """Every file of a package folder, by its path relative to the folder's parent, without bytecode."""
    return {
        p.relative_to(package_dir.parent).as_posix(): p.read_bytes()
        for p in package_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }


def _wheel_files(wheel: Path, top: str) -> dict[str, bytes]:
    with zipfile.ZipFile(wheel) as z:
        return {n: z.read(n) for n in z.namelist() if n.startswith(f"{top}/") and not n.endswith("/")}


def _wheel_metadata(wheel: Path) -> str:
    with zipfile.ZipFile(wheel) as z:
        (meta,) = [n for n in z.namelist() if n.endswith(".dist-info/METADATA")]
        return z.read(meta).decode()


def _lock_entries(repo: Path, name: str) -> list[dict]:
    return [p for p in _toml(repo / "uv.lock").get("package", []) if p.get("name") == name]


def _assert_lock_takes_vendored(repo: Path, name: str, version: str, wheel: str) -> None:
    entries = _lock_entries(repo, name)
    assert len(entries) == 1, f"{repo.name}/uv.lock has {len(entries)} packages named {name}: {entries}"
    (entry,) = entries
    assert entry.get("version") == version, f"{repo.name}/uv.lock resolves {name} {entry.get('version')}"
    assert entry.get("source") == {"path": f"vendor/{wheel}"}, \
        f"{repo.name}/uv.lock takes {name} from {entry.get('source')}"
    wheels = entry.get("wheels") or [{}]
    assert wheels[0].get("hash") == "sha256:" + _sha256(repo / "vendor" / wheel), \
        f"{repo.name}/uv.lock records a hash that is not vendor/{wheel}'s"
    for e in entries:
        assert "registry" not in e.get("source", {}), f"{repo.name}/uv.lock takes {name} from an index"
        assert "git" not in e.get("source", {}), f"{repo.name}/uv.lock takes {name} from git"


# the plugin interface

@pytest.mark.parametrize("package", ENGINE_PACKAGES)
def test_each_engine_package_pins_the_interface_at_0_4_0(package):
    deps = _toml(ROOT / package / "pyproject.toml")["project"]["dependencies"]
    assert [d for d in deps if _name(d) == INTERFACE] == ["aisc-plugin-interface>=0.4.0"]


@pytest.mark.parametrize("package", ENGINE_PACKAGES)
def test_each_engine_package_takes_the_interface_from_its_vendored_wheel(package):
    sources = _toml(ROOT / package / "pyproject.toml").get("tool", {}).get("uv", {}).get("sources", {})
    assert sources.get(INTERFACE) == WHEEL_SOURCE
    assert (ROOT / package / "vendor" / WHEEL).is_file(), f"{package}/vendor/{WHEEL} is missing"


@pytest.mark.parametrize("package", ENGINE_PACKAGES)
def test_each_lock_names_0_4_0_from_vendor_and_never_pypi(package):
    _assert_lock_takes_vendored(ROOT / package, INTERFACE, "0.4.0", WHEEL)


def test_the_three_vendored_wheels_are_one_file():
    paths = [ROOT / p / "vendor" / WHEEL for p in ENGINE_PACKAGES]
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    assert not missing, f"missing: {missing}"
    assert len({_sha256(p) for p in paths}) == 1


def test_the_vendored_wheel_is_the_submodule():
    wheel = ROOT / "apps/backend/vendor" / WHEEL
    assert wheel.is_file(), f"apps/backend/vendor/{WHEEL} is missing"
    source = _source_files(INTERFACE_SRC / "src/aisc_plugin_interface")
    packed = _wheel_files(wheel, "aisc_plugin_interface")
    assert set(packed) == set(source), \
        f"only in the wheel: {sorted(set(packed) - set(source))}; only in the submodule: {sorted(set(source) - set(packed))}"
    differ = sorted(n for n in source if source[n] != packed[n])
    assert not differ, f"the wheel's copy differs from the submodule's: {differ}"
    meta = _wheel_metadata(wheel)
    assert re.search(r"^Version: 0\.4\.0$", meta, re.M)
    requires = set(re.findall(r"^Requires-Dist: (.+)$", meta, re.M))
    expected = set(_toml(INTERFACE_SRC / "pyproject.toml")["project"]["dependencies"])
    assert expected == {"pydantic>=2.13.5", "rich>=15.0.0"}
    assert requires == expected


@pytest.mark.parametrize("app", ENGINE_APPS)
def test_each_engine_image_copies_the_vendored_wheel_before_the_frozen_sync(app):
    lines = (ROOT / app / "Dockerfile").read_text().splitlines()
    copies = [i for i, line in enumerate(lines) if re.match(r"^COPY vendor/ \./vendor/$", line)]
    assert copies, f"{app}/Dockerfile has no 'COPY vendor/ ./vendor/'"
    first_sync = next(i for i, line in enumerate(lines) if "uv sync --frozen" in line)
    assert copies[0] < first_sync, f"{app}/Dockerfile copies vendor/ after its first uv sync --frozen"
    assert "COPY pyproject.toml uv.lock ./" in lines[:copies[0]], \
        f"{app}/Dockerfile copies vendor/ before pyproject.toml and uv.lock"


# the plugin-manager and aisc_identity, in the two images

@pytest.mark.parametrize("name", sorted(LOCAL_PACKAGES))
@pytest.mark.parametrize("app", ENGINE_APPS)
def test_each_engine_app_takes_plugin_manager_and_identity_from_vendored_wheels(app, name):
    project = _toml(ROOT / app / "pyproject.toml")
    assert [d for d in project["project"]["dependencies"] if _name(d) == name], \
        f"{app}/pyproject.toml does not declare {name}"
    wheel = _local_wheel(name)
    assert project.get("tool", {}).get("uv", {}).get("sources", {}).get(name) == {"path": f"vendor/{wheel}"}
    assert (ROOT / app / "vendor" / wheel).is_file(), f"{app}/vendor/{wheel} is missing"


@pytest.mark.parametrize("name", sorted(LOCAL_PACKAGES))
@pytest.mark.parametrize("app", ENGINE_APPS)
def test_each_engine_app_lock_takes_plugin_manager_and_identity_from_vendor(app, name):
    folder, _ = LOCAL_PACKAGES[name]
    version = _toml(folder / "pyproject.toml")["project"]["version"]
    _assert_lock_takes_vendored(ROOT / app, name, version, _local_wheel(name))


@pytest.mark.parametrize("name", sorted(LOCAL_PACKAGES))
def test_the_two_apps_vendor_one_wheel_of_each_local_package(name):
    paths = [ROOT / app / "vendor" / _local_wheel(name) for app in ENGINE_APPS]
    missing = [str(p.relative_to(ROOT)) for p in paths if not p.is_file()]
    assert not missing, f"missing: {missing}"
    assert len({_sha256(p) for p in paths}) == 1


@pytest.mark.parametrize("name", sorted(LOCAL_PACKAGES))
def test_the_vendored_local_wheel_is_this_checkouts_code(name):
    """Guards against a wheel left over from an earlier commit, and against upstream's tag v0.3.0."""
    folder, package = LOCAL_PACKAGES[name]
    wheel = ROOT / "apps/backend/vendor" / _local_wheel(name)
    assert wheel.is_file(), f"apps/backend/vendor/{wheel.name} is missing"
    top = Path(package).name
    source = _source_files(folder / package)
    packed = _wheel_files(wheel, top)
    assert set(packed) == set(source), \
        f"only in the wheel: {sorted(set(packed) - set(source))}; only in the source: {sorted(set(source) - set(packed))}"
    differ = sorted(n for n in source if source[n] != packed[n])
    assert not differ, f"the wheel's copy differs from {folder.relative_to(ROOT)}: {differ}"


def test_the_vendored_plugin_manager_asks_for_interface_0_4_0():
    wheel = ROOT / "apps/backend/vendor" / _local_wheel("aisc-plugin-manager")
    assert wheel.is_file(), f"apps/backend/vendor/{wheel.name} is missing"
    requires = re.findall(r"^Requires-Dist: (.+)$", _wheel_metadata(wheel), re.M)
    assert [r for r in requires if _name(r) == INTERFACE] == ["aisc-plugin-interface>=0.4.0"]


def test_the_plugin_manager_has_a_version_of_its_own():
    """Upstream's 0.3.0 plus this checkout's commits: a PEP 440 local version, never upstream's own file."""
    folder, _ = LOCAL_PACKAGES["aisc-plugin-manager"]
    assert _toml(folder / "pyproject.toml")["project"]["version"] == "0.3.0+aisc.1"
    for app in ENGINE_APPS:
        vendor = ROOT / app / "vendor"
        assert (vendor / "aisc_plugin_manager-0.3.0+aisc.1-py3-none-any.whl").is_file(), \
            f"{app}/vendor holds no aisc_plugin_manager-0.3.0+aisc.1-py3-none-any.whl"
        assert not (vendor / "aisc_plugin_manager-0.3.0-py3-none-any.whl").exists(), \
            f"{app}/vendor still holds aisc_plugin_manager-0.3.0-py3-none-any.whl"
    wheel = ROOT / "apps/backend/vendor/aisc_plugin_manager-0.3.0+aisc.1-py3-none-any.whl"
    assert re.findall(r"^Version: (.+)$", _wheel_metadata(wheel), re.M) == ["0.3.0+aisc.1"]
