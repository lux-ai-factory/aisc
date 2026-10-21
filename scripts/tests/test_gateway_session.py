"""scripts/lib/gateway-session.sh: gateway_session says yes only when the sign-in landed back on the launcher.
A refused password shows Keycloak's form again, also with 200, so a status code alone is not a sign-in."""
import http.server
import subprocess
import threading

import pytest

from conftest import ROOT


class FakeSignIn(http.server.BaseHTTPRequestHandler):
    """/ is the launcher: without the cookie it serves Keycloak's form, posting to /realms/aisc/login. The
    password "right" sets the cookie and goes back to /; any other gets the form again."""

    def log_message(self, *a):
        pass

    def _form(self):
        page = (f'<form action="http://127.0.0.1:{self.server.server_port}/realms/aisc/login?x=1&amp;y=2" '
                'method="post"><input name="username"><input name="password"></form>').encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(page)

    def do_GET(self):
        if "signed=yes" in (self.headers.get("Cookie") or ""):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h1>Projects</h1>")
        else:
            self._form()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        if "password=right" in body:
            self.send_response(302)
            self.send_header("Set-Cookie", "signed=yes; Path=/")
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._form()


@pytest.fixture
def launcher():
    server = http.server.HTTPServer(("127.0.0.1", 0), FakeSignIn)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/"
    server.shutdown()


def sign_in(launcher, password, tmp_path):
    jar = tmp_path / "jar"
    return subprocess.run(["bash", "-c", f'. "{ROOT}/scripts/lib/gateway-session.sh"; gateway_session admin "$1" "$2"',
                           "_", password, str(jar)],
                          env={"PATH": "/usr/bin:/bin", "GATEWAY_LAUNCHER_URL": launcher}).returncode


def test_the_right_password_signs_in(launcher, tmp_path):
    assert sign_in(launcher, "right", tmp_path) == 0


def test_a_refused_password_is_not_a_sign_in(launcher, tmp_path):
    assert sign_in(launcher, "wrong", tmp_path) != 0
