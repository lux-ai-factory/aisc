"""The checks reach every address of the install (env.runtime), not the default ports: aisc.py start moves a
new install off any browser port that is taken (80, 8100, 8188, 8081)."""
import re
import subprocess

from conftest import ROOT

#: the engine on port 80, written out: http://localhost followed by a path, a quote, a shell variable ($path)
#: or the end of the line; or the launcher, the dashboard or the sign-in on their default ports
BROWSER_PORT = re.compile(r"""http://localhost(?=[/"'\s$]|$)|localhost:(8100|8188|8081)\b""")
#: the two places that know the default addresses: where start sets them, and where the checks read them
DEFINE_IT = {"scripts/aisc.py", "scripts/lib/install-addresses.sh"}


def test_no_check_script_names_a_browser_port():
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "scripts"], capture_output=True, text=True,
                           check=True).stdout.split()
    found = [f"{f}:{n}" for f in files if not f.startswith("scripts/tests/") and f not in DEFINE_IT
             for n, line in enumerate((ROOT / f).read_text(errors="replace").splitlines(), 1)
             if BROWSER_PORT.search(line)]
    assert found == []
