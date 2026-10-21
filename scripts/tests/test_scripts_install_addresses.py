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


def addresses(tmp_path, runtime, **already):
    """The four addresses scripts/lib/install-addresses.sh exports, sourced in a scratch tree beside an env.runtime
    holding `runtime`, with `already` set before; read from a child process, so only exported ones count."""
    lib = tmp_path / "scripts/lib"
    lib.mkdir(parents=True)
    (lib / "install-addresses.sh").write_text((ROOT / "scripts/lib/install-addresses.sh").read_text())
    (tmp_path / "env.runtime").write_text(runtime)
    names = ("VERIFY_APPS_URL", "VERIFY_BASE_URL", "VERIFY_DASHBOARD_URL", "KEYCLOAK_URL")
    script = ("unset " + " ".join(n for n in names if n not in already) + "\n"
              + "".join(f"{k}={v}\n" for k, v in already.items())
              + f". {lib}/install-addresses.sh\n"
              + "env | grep -E '^(" + "|".join(names) + ")=' | sort")
    r = subprocess.run(["bash", "-c", script], cwd="/", capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return dict(line.split("=", 1) for line in r.stdout.splitlines())


def test_the_last_line_of_each_setting_wins_and_its_quotes_go(tmp_path):
    got = addresses(tmp_path, 'API_URL_EXTERNAL="http://localhost"\nLAUNCHER_EXTERNAL_URL=http://h:8110/\n'
                              "API_URL_EXTERNAL='http://h:8090'\nDASHBOARD_EXTERNAL_URL=\"http://h:8198\"\n"
                              "KEYCLOAK_URL_EXTERNAL=http://h:8091\n")
    assert got == {"VERIFY_APPS_URL": "http://h:8090", "VERIFY_BASE_URL": "http://h:8110",
                   "VERIFY_DASHBOARD_URL": "http://h:8198", "KEYCLOAK_URL": "http://h:8091"}


def test_the_launcher_has_no_trailing_slash_whether_it_was_set_with_one_or_not(tmp_path):
    assert addresses(tmp_path, "LAUNCHER_EXTERNAL_URL=https://a.example.org\n")["VERIFY_BASE_URL"] == \
        "https://a.example.org"


def test_a_variable_already_set_wins_and_a_missing_setting_takes_the_default_port(tmp_path):
    got = addresses(tmp_path, "DASHBOARD_EXTERNAL_URL=http://h:8198\n", VERIFY_DASHBOARD_URL="http://mine:9000")
    assert got["VERIFY_DASHBOARD_URL"] == "http://mine:9000"
    assert got["KEYCLOAK_URL"] == "http://localhost:8081" and got["VERIFY_APPS_URL"] == "http://localhost"
    assert got["VERIFY_BASE_URL"] == "http://localhost:8100"
