"""Git as the publisher runs it. The rules come from the former plugin-downloader and stay as they
were: HTTP/1.1, the token only through a credential helper (none when no token is set), never a prompt."""

import os
import subprocess

GIT_TIMEOUT_S = 300

# HTTP/1.1: over HTTP/2, git 2.49 and later get a 401 from GitHub even on a public repo.
HTTP_1_1 = ["-c", "http.version=HTTP/1.1"]

# The token reaches git through a credential helper that reads it from the environment, so it is
# never in a URL, in git's arguments or in .git/config.
CREDENTIAL_HELPER = [
    "-c",
    'credential.helper=!f() { echo username=x-access-token; echo "password=${GITHUB_TOKEN}"; }; f',
]

# What a failed clone or ls-remote says without a token: GitHub answers a private or unknown repo
# alike, and git's own words for it ("Invalid username or token", "could not read Username") mislead.
NO_TOKEN_FAILURE = "no access, or no such repo (GITHUB_TOKEN is not set)"

# Values that must never reach a response or a log, even inside a tool's own output.
SECRET_VARS = ("GITHUB_TOKEN", "TWINE_PASSWORD", "PLUGIN_PUBLISHER_TOKEN")


def has_github_token() -> bool:
    return bool(os.environ.get("GITHUB_TOKEN"))


class StepFailed(Exception):
    """A tool (git, build, twine) failed; output is what it printed."""

    def __init__(self, output: str):
        super().__init__(output)
        self.output = output


def scrub(text: str) -> str:
    for var in SECRET_VARS:
        value = os.environ.get(var)
        if value:
            text = text.replace(value, "***")
    return text


def tail(text: str, lines: int = 20) -> str:
    return scrub("\n".join(text.strip().splitlines()[-lines:]))


def git(*args: str, url: str, cwd=None) -> subprocess.CompletedProcess:
    """Runs git with the rules above. url is the remote the call reaches: a local file:// base (the
    tests' bare repos) needs the file protocol allowed, nothing else does."""
    # without a token the helper would hand GitHub an empty password; public repos need none
    argv = ["git", *HTTP_1_1, *(CREDENTIAL_HELPER if has_github_token() else [])]
    if url.startswith("file://"):
        argv += ["-c", "protocol.file.allow=always"]
    # the GitHub token is the only secret git needs; devpi's password and the service token stay out
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("TWINE_") and k != "PLUGIN_PUBLISHER_TOKEN"}
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            [*argv, *args], cwd=cwd, env=env, capture_output=True, text=True,
            timeout=GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise StepFailed(f"git did not answer within {GIT_TIMEOUT_S} s") from None
