"""Static and scratch-copy checks of the per-project LLM keys feature (pipeline
2026-09-24-llm-keys, 01-specs.md S3.1, S4.1 to S4.8, S6.3 to S6.6).

Nothing is started and nothing in the repo is written: scripts/secrets.sh runs on a scratch
copy only (in the repo it would rewrite env.runtime, the live stack's env file). The platform
catalogue's ids are read through the platform's own venv (`uv run --project platform`).

Run from the repo root:

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_llm_keys.py
"""

import ast
import base64
import json
import re
import shutil
import subprocess
import sys
import tomllib

import pytest

from conftest import ROOT

A_COPY = ROOT / "apps/qualification/services/agents/fill/baf_llm.py"
B_COPY = ROOT / "apps/control-objectives/src/aisc_control_objectives/baf_llm.py"
PAGE = ROOT / "homepage/llm.html"
PROJECT_PAGE = ROOT / "homepage/project.html"
IDS = {"anthropic", "compatible", "deepseek", "google", "groq", "meta", "mistral",
       "ollama", "openai", "openrouter", "qwen", "together", "xai"}


def read(path):
    assert path.is_file(), f"missing feature: {path.relative_to(ROOT)} does not exist"
    return path.read_text()


def script_of(html):
    return "\n".join(re.findall(r"<script\b[^>]*>(.*?)</script>", html, re.S | re.I))


def markup_of(html):
    return re.sub(r"<script\b[^>]*>.*?</script>", "", html, flags=re.S | re.I)


# ── S3.1 one module, two identical copies ────────────────────────────────────


def test_s3_1_both_copies_exist_and_are_byte_identical():
    assert read(A_COPY).encode() == read(B_COPY).encode()


def test_s3_1_it_imports_only_the_standard_library_and_baf():
    tree = ast.parse(read(A_COPY))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "a package-relative import cannot work in both places"
            top = (node.module or "").split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in sys.stdlib_module_names or top == "baf", alias.name
            continue
        else:
            continue
        assert top in sys.stdlib_module_names or top in {"baf", "__future__"}, top


def _provider_keys(path):
    for node in ast.walk(ast.parse(read(path))):
        targets = []
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        if any(isinstance(t, ast.Name) and t.id == "PROVIDERS" for t in targets):
            assert isinstance(value, ast.Dict), "PROVIDERS is not a dict literal"
            return {k.value for k in value.keys}
    raise AssertionError(f"no PROVIDERS in {path}")


def test_s3_1_s2_3_the_agents_providers_are_the_platform_catalogue():
    keys = _provider_keys(A_COPY)
    assert keys == IDS
    done = subprocess.run(
        ["uv", "run", "--project", str(ROOT / "platform"), "python", "-c",
         "import json; from platform_service import llm_catalogue as c; print(json.dumps(sorted(c.PROVIDERS)))"],
        cwd=ROOT / "platform", capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    assert set(json.loads(done.stdout.strip().splitlines()[-1])) == keys


# ── S4 the page ──────────────────────────────────────────────────────────────


def test_s4_1_the_page_has_the_launchers_look_and_one_inline_script():
    html, reference = read(PAGE), read(PROJECT_PAGE)
    root_vars = re.findall(r"(--[a-z0-9-]+)\s*:", re.search(r":root\s*\{(.*?)\}", reference, re.S).group(1))
    for var in root_vars:
        assert re.search(re.escape(var) + r"\s*:", html), f"CSS variable {var} of project.html missing"
    fonts = re.search(r'href="(https://fonts\.googleapis\.com/css2[^"]+)"', reference).group(1)
    assert fonts in html
    assert 'class="session"' in html and 'id="who"' in html
    scripts = re.findall(r"<script\b([^>]*)>", html, re.I)
    assert len(scripts) == 1, "exactly one inline <script>"
    assert "src" not in scripts[0].lower(), "no external script"


def test_s4_2_the_manage_menu_links_the_page_for_admins_only():
    html = read(PROJECT_PAGE)
    manage = re.search(r'<details[^>]*id="manage".*?</details>', html, re.S).group(0)
    link = re.search(r'<a\b[^>]*id="llm-settings"[^>]*>(.*?)</a>', manage, re.S)
    assert link, 'no <a id="llm-settings"> in the Manage menu'
    assert link.group(1).strip() == "Models and API keys"
    script = script_of(html)
    admin_gate = script.find("a.admin")
    wiring = re.search(r"getElementById\('llm-settings'\)\.href\s*=\s*'/llm\.html\?project='\s*\+\s*"
                       r"encodeURIComponent\(slug\)", script)
    assert wiring, "the link's href is not set to /llm.html?project=<slug>"
    assert admin_gate != -1 and wiring.start() > admin_gate, "the href is set outside the admin-only block"


def test_s4_3_non_admins_are_told_and_no_llm_call_is_made_first():
    html = read(PAGE)
    script = script_of(html)
    assert "Only a platform admin manages models and keys." in html
    assert "/api/projects/" in script and "/api/authz/projects/" in script
    assert re.search(r"\.admin\b", script)
    first_llm = script.find("/llm")
    assert first_llm == -1 or script.find("/api/authz/projects/") < first_llm


def test_s4_4_key_fields_are_write_only_password_inputs():
    html = read(PAGE)
    assert re.search(r"""type\s*=\s*["']password["']|\.type\s*=\s*["']password["']""", html)
    assert "new-password" in html
    for tag in re.findall(r"<input\b[^>]*password[^>]*>", markup_of(html), re.I):
        assert not re.search(r"\bvalue\s*=", tag), f"prefilled key field: {tag}"
    for text in ("key stored", "no key", "no key needed", "Save", "Remove"):
        assert text in html, text
    assert "base_url" in html


def test_s4_5_systems_offer_usable_providers_and_live_models():
    script = script_of(read(PAGE))
    assert "Service default (environment)" in script or "Service default (environment)" in read(PAGE)
    assert ".usable" in script
    assert "/models" in script and "/llm/systems/" in script
    assert re.search(r"[Ll]oading", read(PAGE))
    assert re.search(r"['\"]PUT['\"]", script) and re.search(r"['\"]DELETE['\"]", script)
    assert ".error" in script and ".choice" in script


def test_s4_6_errors_come_from_detail_or_error_and_a_dead_platform_is_said_plainly():
    script = script_of(read(PAGE))
    assert ".detail" in script and ".error" in script
    assert "The platform is not answering. Nothing was saved." in script


def test_s4_7_csp_and_injection_safe():
    html = read(PAGE)
    script = script_of(html)
    assert not re.search(r"<[a-z][^>]*\son[a-z]+\s*=", markup_of(html), re.I), "inline event handler attribute"
    assert "addEventListener" in script
    assert not re.search(r"\.on[a-z]+\s*=", script), "property event handler; use addEventListener"
    assert "innerHTML" not in html and "outerHTML" not in html and "insertAdjacentHTML" not in html
    assert "document.write" not in script and "eval(" not in script
    calls = re.findall(r"fetch\(\s*([^,)]+)", script)
    assert calls, "no fetch at all"
    for arg in calls:
        assert not re.search(r"https?:", arg), f"not same-origin: {arg}"
    assert script.count("credentials: 'same-origin'") + script.count('credentials: "same-origin"') + \
        script.count("credentials:'same-origin'") >= len(calls)
    assert re.search(r"""['"]Content-Type['"]\s*:\s*['"]application/json['"]""", script)
    for literal in re.findall(r"""fetch\(\s*['"]([^'"]*)""", script):
        assert literal.startswith("/api/"), literal


def test_s4_8_the_page_never_puts_anything_but_empty_into_a_key_field():
    script = script_of(read(PAGE))
    for target, value in re.findall(r"([\w.\[\]'\"]*[kK]ey[\w.\[\]'\"]*)\.value\s*=\s*([^;\n]+)", script):
        assert value.strip() in {"''", '""'}, f"{target}.value = {value}"
    assert not re.search(r"\.api_key\b", script), "the page reads a key field from a response"


# ── S6.3 secrets.sh, on a scratch copy only ──────────────────────────────────


@pytest.fixture
def scratch(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "keycloak").mkdir()
    shutil.copy(ROOT / "scripts/secrets.sh", tmp_path / "scripts/secrets.sh")
    shutil.copy(ROOT / "keycloak/aisc-realm.json", tmp_path / "keycloak/aisc-realm.json")
    shutil.copy(ROOT / "env.plugin_downloader", tmp_path / "env.plugin_downloader")
    return tmp_path


def secrets_of(d):
    return dict(line.split("=", 1) for line in (d / "env.secrets").read_text().splitlines()
                if line and not line.startswith("#"))


def run_secrets(d):
    r = subprocess.run(["bash", str(d / "scripts/secrets.sh")], cwd=d, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr[-2000:]
    return r


def check_shapes(values):
    assert re.fullmatch(r"[0-9a-f]{64}", values["PLATFORM_INTERNAL_TOKEN"])
    key = values["PLATFORM_SECRETS_KEY"]
    assert len(key) == 44
    assert len(base64.urlsafe_b64decode(key)) == 32


def test_s6_3_a_new_install_gets_both_secrets_and_a_second_run_keeps_them(scratch):
    runtime = ROOT / "env.runtime"
    before = runtime.stat().st_mtime if runtime.exists() else None
    run_secrets(scratch)
    first = secrets_of(scratch)
    check_shapes(first)
    run_secrets(scratch)
    again = secrets_of(scratch)
    assert again["PLATFORM_INTERNAL_TOKEN"] == first["PLATFORM_INTERNAL_TOKEN"]
    assert again["PLATFORM_SECRETS_KEY"] == first["PLATFORM_SECRETS_KEY"]
    assert (runtime.stat().st_mtime if runtime.exists() else None) == before, "the repo's env.runtime was touched"


def test_s6_3_an_existing_install_gets_them_appended_without_replacing_anything(scratch):
    old = {"GATEWAY_COOKIE_SECRET": "c" * 43, "GATEWAY_CLIENT_SECRET": "old-client", "INTERNAL_API_KEY": "old-api",
           "REPORT_SERVICE_TOKEN": "old-report", "REPORT_RO_PASSWORD": "a", "REPORT_COMPOSER_PASSWORD": "b",
           "INSPECTOR_PASSWORD": "c"}
    (scratch / "env.secrets").write_text("# made before\n" + "".join(f"{k}={v}\n" for k, v in old.items()))
    run_secrets(scratch)
    values = secrets_of(scratch)
    for k, v in old.items():
        assert values[k] == v, k
    check_shapes(values)
    first = dict(values)
    run_secrets(scratch)
    assert secrets_of(scratch) == first


# ── S6.4 Caddy blocks the internal route on the launcher ─────────────────────


def test_s6_4_the_launcher_answers_404_to_api_internal_before_proxying_api():
    text = read(ROOT / "Caddyfile")
    start = text.index("{$CADDY_DOMAIN}:{$HOMEPAGE_PORT} {")
    site = text[start:text.index("\n}\n", start)]
    block = re.search(r"handle\s+/api/internal/\*\s*\{\s*respond\s+404\s*\}", site)
    assert block, "no `handle /api/internal/* { respond 404 }` in the launcher site"
    route = site.index("route {")
    assert route < block.start() < site.index("handle_path /api/*")


# ── S6.5 and S6.6 dependencies and env comments ──────────────────────────────


def test_s6_5_the_platform_depends_on_httpx_and_cryptography_at_runtime():
    deps = tomllib.loads(read(ROOT / "platform/pyproject.toml"))["project"]["dependencies"]
    assert "httpx>=0.27" in deps
    assert "cryptography>=43" in deps
    lock = tomllib.loads(read(ROOT / "platform/uv.lock"))
    me = next(p for p in lock["package"] if p["name"] == "aisc-platform")
    runtime = {d["name"] for d in me.get("dependencies", [])}
    assert {"httpx", "cryptography"} <= runtime, "uv.lock not updated"


def test_s6_5_the_agents_need_nothing_new():
    reqs = read(ROOT / "apps/qualification/services/agents/requirements.txt")
    assert "httpx" not in reqs and "cryptography" not in reqs


@pytest.mark.parametrize("name", ["env.development", "env.staging"])
def test_s6_6_env_files_say_where_the_two_secrets_come_from(name):
    lines = [l for l in read(ROOT / name).splitlines() if l.startswith("#")]
    for secret in ("PLATFORM_SECRETS_KEY", "PLATFORM_INTERNAL_TOKEN"):
        assert any(secret in l and "env.secrets" in l for l in lines), f"{name}: no comment for {secret}"
    for secret in ("PLATFORM_SECRETS_KEY", "PLATFORM_INTERNAL_TOKEN"):
        assert not re.search(rf"^{secret}=", read(ROOT / name), re.M), f"{name} must not set {secret}"
