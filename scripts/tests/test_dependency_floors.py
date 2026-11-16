"""No lock or pinned requirement of the stack, in this repository or a submodule, holds a version inside a published
advisory's range: each package named below is at or above the first fixed version. The qualification agents
install besser-agentic-framework, which pins its own dependencies with ==: their image raises those pins through
overrides.txt. streamlit stays, at the first version past its advisories: the framework imports it when its Agent
class is imported.

Read-only: lock and requirement files as text. packaging comes with pytest.
"""

import json
import re
import subprocess
import tomllib

from packaging.version import Version

from conftest import ROOT

FLOORS = {"aiohttp": "3.14.4", "requests": "2.33.0", "nltk": "3.10.4", "pillow": "13.0.0", "pypdf": "6.21.4",
          "python-multipart": "0.0.31", "brotli": "1.2.1", "pyasn1": "0.6.5", "filelock": "4.2.1"}
NPM_FLOORS = {"zod": "4.6.6", "follow-redirects": "1.16.2", "fast-uri": "3.1.9"}


def _files(pattern: str):
    out = subprocess.run(["git", "ls-files", "--recurse-submodules"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return [ROOT / p for p in out.splitlines() if re.search(pattern, p) and (ROOT / p).is_file()]


def _rel(path) -> str:
    return str(path.relative_to(ROOT))


def test_no_python_lock_or_pin_holds_a_vulnerable_version():
    low = []
    for lock in _files(r"(^|/)uv\.lock$"):
        for p in tomllib.loads(lock.read_text()).get("package", []):
            floor = FLOORS.get(p["name"].lower())
            if floor and "version" in p and Version(p["version"]) < Version(floor):
                low.append((_rel(lock), p["name"], p["version"]))
    for req in _files(r"(^|/)requirements[^/]*\.txt$"):
        for name, ver in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)", req.read_text(), re.M):
            floor = FLOORS.get(name.lower())
            if floor and Version(ver) < Version(floor):
                low.append((_rel(req), name, ver))
    assert sorted(low) == []


def test_no_node_lock_holds_a_vulnerable_version():
    low = []
    for lock in _files(r"(^|/)package-lock\.json$"):
        for path, p in json.loads(lock.read_text()).get("packages", {}).items():
            name = path.rsplit("node_modules/", 1)[-1]
            floor = NPM_FLOORS.get(name)
            if floor and not p.get("dev") and "version" in p and Version(p["version"]) < Version(floor):
                low.append((_rel(lock), name, p["version"]))
    assert sorted(set(low)) == []


def test_the_agents_raise_the_frameworks_pins_past_their_advisories():
    agents = ROOT / "apps/qualification/services/agents"
    overrides = agents / "overrides.txt"
    assert overrides.is_file(), "the agents install BAF's pins as they are, streamlit included"
    pinned = {n.lower(): v for n, v in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;#]+)", overrides.read_text(), re.M)}
    wanted = {"aiohttp": FLOORS["aiohttp"], "nltk": FLOORS["nltk"], "pillow": FLOORS["pillow"],
              "requests": FLOORS["requests"], "streamlit": "1.54.0"}
    low = {n: pinned.get(n) for n, f in wanted.items() if n not in pinned or Version(pinned[n]) < Version(f)}
    assert low == {}
    assert "--override overrides.txt" in (agents / "Dockerfile.stack").read_text()
