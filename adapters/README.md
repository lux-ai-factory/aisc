# Adapter plugins: protocols you add to your install

An **adapter plugin** lets AISC reach a system that speaks none of its built-in protocols. It is a few lines of
Python that translate one question into what the system expects, and its answer back. You put it in this folder;
the platform (service `platform`) loads it and offers it as one more protocol under **Manage > Components and
connections**.

## How it works

A test never calls the system it assesses directly. It calls one of the platform's doors, and the platform
forwards the call to the project's **connection** for that system, adding the secrets and holding it to the
project's allowed hosts and timeout. A connection speaks a protocol: REST API, OpenAI-compatible, A2A agent or
Open Inference Protocol, or one an adapter plugin adds. For a connection of an adapter's protocol, the platform
hands every call to the adapter's `call()`. Tests keep calling the platform as always and need no change.
[docs/architecture.md](../docs/architecture.md#4-running-tests) shows where this sits in AISC.

This folder holds your adapter plugins, one subfolder each. Only this README is part of AISC: everything else here
is ignored by git, so your adapters are never committed with AISC.

## Run it

1. Copy the adapter's folder here (`cp -r /path/to/my-adapter adapters/`). A symbolic link to a folder outside
   the install does not work: the platform's container sees only what is inside `adapters/`.
2. Restart the platform: `docker restart platform` (put your install's container prefix in front of `platform`
   if it has one; `docker ps` shows the name). The platform reads the folder once, the first time it needs it,
   so adding, changing or removing an adapter takes a restart. An adapter that does not load is skipped, and the
   platform's log says why.
3. **Manage > Components and connections**, a component's row, **Connect**: the Protocol menu offers your
   adapter. Fill in its fields and the base URL, and **Try** it.
4. Tests that assess that component reach the system through the adapter.

A connection whose adapter is removed stays listed: its calls fail ("the example-chat adapter is not installed")
until the adapter is back, and it can still be deleted.

## What an adapter is

`adapters/<folder>/adapter.py`, which may import modules beside it in the same folder (a module named like one
the platform has already loaded is refused: rename it). It uses the standard library and what the platform already
has installed; anything else goes inside its folder.

```python
import json
import urllib.error
import urllib.request

PROTOCOL = {
    "name": "example-chat",               # the protocol's name: [a-z][a-z0-9-]{1,39}, not a built-in one
    "label": "Example chat site",         # what the Protocol menu shows
    "base_url": "https://chat.example.org",   # optional: filled in for a new connection
    "fields": [                           # what the connection editor asks for, in this order
        {"name": "token", "label": "Access token", "secret": True, "required": True,
         "help": "Stored encrypted, never shown again."},
        {"name": "assistant", "label": "Assistant id"},
    ],
    "capabilities": ["text", "history"],  # "text", and "history" if it takes earlier turns
    "max_concurrent": 1,                  # optional: calls at once, across every run
}


class Failure(Exception):
    def __init__(self, code, message, status=None):
        super().__init__(message)
        self.code, self.status = code, status


def call(connection, input, history, params, open):
    """One question to the system; returns its answer (text, or JSON for a structured system)."""
    body = {"token": connection["secrets"]["token"], "assistant": connection["settings"].get("assistant"),
            "messages": history + [{"role": "user", "content": input}]}
    request = urllib.request.Request(connection["base_url"] + "/api/chat", data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with open(request, timeout=connection["timeout_s"]) as resp:
            return json.loads(resp.read())["reply"]
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise Failure("auth", "the site refused the token", exc.code) from None
        raise Failure("bad_response", f"the site answered {exc.code}", exc.code) from None
```

### `PROTOCOL`

| Key | Meaning | Default |
|---|---|---|
| `name` | the protocol's name, `[a-z][a-z0-9-]{1,39}`; not `openai`, `rest`, `a2a` or `oip`. Of two adapters with one name, the first folder (by name) wins | required |
| `label` | what the Protocol menu shows | required |
| `fields` | what the connection editor asks for: `name` (letters, digits, `_`), `label`, `secret`, `required`, `help`. A secret field is stored encrypted and never shown again | none |
| `capabilities` | `"text"`, plus `"history"` if the adapter takes earlier turns | `["text", "history"]` |
| `base_url` | filled in for a new connection | none |
| `max_concurrent` | calls at once, across every run and project | no limit |

### `call(connection, input, history, params, open)`

- `connection`: `name`, `label`, `base_url`, `timeout_s`, `settings` (the plain fields) and `secrets` (the secret
  fields), each `{field name: value}`.
- `input`: the question, text; or a JSON object for a structured system (a scorer taking a record).
- `history`: earlier turns as OpenAI chat messages (`{"role", "content"}`), possibly empty. An adapter without
  `"history"` in its capabilities never gets one: the platform refuses it before calling.
- `params`: the test's parameters, possibly empty.
- `open(request, timeout=None)`: the only way to reach the network. It is `urllib.request.urlopen` under the
  project's rules (its allowed hosts; private and internal addresses refused, also after DNS resolution), with
  no redirects followed. It returns the response unread, so a stream can be read as it arrives. It never waits
  past the moment the test stops waiting for the answer, whatever `timeout` you give it.

Return the answer. To refuse or to fail, raise an exception with a `code` attribute:

| `code` | means |
|---|---|
| `refused` | the system declined to answer: a result, recorded with the message as its reason |
| `auth` | the credentials were refused |
| `not_found` | nothing at that address |
| `timeout` | no answer in time |
| `bad_response` | the system answered something the adapter cannot read |

Any other exception is a failure with code `error`. Every secret value is taken out of answers and messages
before anyone sees them. Set `status` on the exception to pass on the system's HTTP status.

The adapter retries and paces its calls itself (a retry or a burst may be visible to the system's owner); how
many run at once is the platform's, from `max_concurrent`. A call that would wait longer than the test waits for
its answer is not sent.

### Settings and files

| What | Value in the stack |
|---|---|
| `PLATFORM_ADAPTERS_DIR` (service `platform`) | `/app/adapters`, this folder mounted read-only |
| Loader | `platform/platform_service/adapters.py` |
| Tests | `platform/tests/test_adapters_loading.py`, `test_connection_adapters.py`, `test_connection_adapter_calls.py` |
