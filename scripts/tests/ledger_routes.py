"""Route discovery for the ledger coverage test. Python routes are read with `ast` (any quote style,
api_route, add_api_route, Flask-AppBuilder ModelViews); Next.js route handlers and server actions with
patterns. Each route is keyed (app, METHOD, file, function), so two
routers declaring the same relative path never collapse into one."""
import ast
import re
from pathlib import Path

#: Every directory whose code serves requests, and the app it is (the ledger registry's KNOWN_APPS).
PY_DIRS = {
    "platform/platform_service": "platform",
    "apps/control-objectives/src": "control_objectives",
    "apps/report-composer/report_composer": "report_composer",
    "apps/report-generator": "report_renderer",
    "apps/backend": "engine",
    "apps/eval": "engine_worker",
    "apps/connectors": "connectors",
    "apps/qualification/services/agents": "qualification_agents",
    "apps/qualification/services/prefill": "qualification_prefill",
    "apps/qualification/services/ontology": "qualification_ontology",
    "apps/qualification/services/llm": "qualification_llm",
    "apps/qualification/services/system_card_renderer": "qualification_pdf",
    "apps/controls": "controls",
    "apps/results-dashboard": "dashboard",
}
NEXT_DIRS = {"apps/qualification/src": "qualification", "apps/controls/src": "controls"}
#: Not in scope, and why.
SCOPED_OUT = {"apps/catalogue": "the catalogue is hosted elsewhere and never passes this gateway",
              "apps/webapp": "the engine's browser app: no server routes"}
IGNORE = re.compile(r"/(tests?|\.venv|node_modules|migrations|alembic|site-packages|__pycache__|\.next)/|/test_[^/]*$|/conftest\.py$")
HTTP = {"get", "post", "put", "patch", "delete"}
WRITES = {"POST", "PUT", "PATCH", "DELETE", "ACTION", "MODELVIEW"}


def _methods(call):
    for kw in call.keywords:
        if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple, ast.Set)):
            return [e.value.upper() for e in kw.value.elts if isinstance(e, ast.Constant)]
    return None


def python_routes(root: Path):
    found = set()
    for base, app in PY_DIRS.items():
        for path in sorted((root / base).rglob("*.py")):
            rel = str(path.relative_to(root))
            if IGNORE.search("/" + rel) or any(rel.startswith(s) for s in SCOPED_OUT):
                continue
            try:
                tree = ast.parse(path.read_text(errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for dec in node.decorator_list:
                        if not isinstance(dec, ast.Call):
                            continue
                        f = dec.func
                        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                        if name in HTTP:
                            found.add((app, name.upper(), rel, node.name))
                        elif name in ("api_route", "route", "expose"):
                            for m in _methods(dec) or ["GET"]:
                                found.add((app, m, rel, node.name))
                elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add_api_route":
                    endpoint = node.args[1] if len(node.args) > 1 else next(
                        (k.value for k in node.keywords if k.arg == "endpoint"), None)
                    fn = getattr(endpoint, "id", None) or getattr(endpoint, "attr", None)
                    for m in _methods(node) or ["GET"]:
                        found.add((app, m, rel, fn or "?"))
                elif isinstance(node, ast.ClassDef):
                    bases = [getattr(b, "id", None) or getattr(b, "attr", "") for b in node.bases]
                    if any(b.endswith("ModelView") for b in bases):
                        found.add((app, "MODELVIEW", rel, node.name))
    return found


HANDLER = re.compile(r"export\s+(?:async\s+)?(?:function|const|let)\s+(GET|POST|PUT|PATCH|DELETE)\b")
REEXPORT = re.compile(r"export\s*\{([^}]*)\}")
ACTION_FN = re.compile(r"export\s+(?:default\s+)?async\s+function\s+(\w+)|export\s+const\s+(\w+)\s*=\s*async\b")


def next_routes(root: Path):
    found = set()
    for base, app in NEXT_DIRS.items():
        for path in sorted(list((root / base).rglob("*.ts")) + list((root / base).rglob("*.tsx"))):
            rel = str(path.relative_to(root))
            if IGNORE.search("/" + rel):
                continue
            text = path.read_text(errors="replace")
            if path.name in ("route.ts", "route.tsx"):
                methods = set(HANDLER.findall(text))
                for group in REEXPORT.findall(text):
                    methods |= set(re.findall(r"\bas\s+(GET|POST|PUT|PATCH|DELETE)\b", group))
                    methods |= {m for m in re.findall(r"\b(GET|POST|PUT|PATCH|DELETE)\b", group)}
                for m in methods:
                    found.add((app, m, rel, m))
            if re.match(r"\s*(?://[^\n]*\n\s*)*['\"]use server['\"]", text):
                for a, b in ACTION_FN.findall(text):
                    found.add((app, "ACTION", rel, a or b))
    return found


def discovered(root: Path):
    return python_routes(root) | next_routes(root)
