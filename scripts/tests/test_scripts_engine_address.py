"""The checks reach the engine at the install's address (API_URL_EXTERNAL in env.runtime), which is not
http://localhost when aisc.py start moved a new install off a taken port 80."""
import re
import subprocess

from conftest import ROOT

#: the engine on port 80, written out: http://localhost followed by a path, a quote or the end of the line
ENGINE_ON_80 = re.compile(r"""http://localhost(?=[/"'\s]|$)""")
#: the two places that know the engine's default address: where start sets it, and where the checks read it
DEFINE_IT = {"scripts/aisc.py", "scripts/lib/engine-address.sh"}


def test_no_check_script_names_the_engine_on_port_80():
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "scripts"], capture_output=True, text=True,
                           check=True).stdout.split()
    found = [f"{f}:{n}" for f in files if not f.startswith("scripts/tests/") and f not in DEFINE_IT
             for n, line in enumerate((ROOT / f).read_text(errors="replace").splitlines(), 1)
             if ENGINE_ON_80.search(line)]
    assert found == []
