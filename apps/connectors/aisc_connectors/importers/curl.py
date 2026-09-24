"""A pasted cURL command into one operation."""
from __future__ import annotations

import base64
import shlex

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.build import one_operation, synth_id
from aisc_connectors.importers.errors import ImportFailed

_DATA = {"-d", "--data", "--data-raw", "--data-binary", "--data-ascii", "--data-urlencode"}


def import_curl(command: str) -> ImportResult:
    try:
        words = shlex.split(command.replace("\\\n", " "))
    except ValueError as exc:
        raise ImportFailed(f"the command does not parse: {exc}") from exc
    if not words or words[0] != "curl":
        raise ImportFailed("paste a command that starts with curl")
    method, url, headers, body, content_type = None, None, {}, None, None
    i = 1
    while i < len(words):
        word = words[i]
        value = words[i + 1] if i + 1 < len(words) else None
        if word in ("-X", "--request"):
            method, i = value, i + 2
        elif word in ("-H", "--header"):
            name, _, header_value = (value or "").partition(":")
            headers[name.strip()] = header_value.strip()
            i += 2
        elif word in _DATA:
            body, i = value, i + 2
            content_type = content_type or "application/x-www-form-urlencoded"
        elif word == "--json":
            body, content_type, i = value, "application/json", i + 2
        elif word in ("-u", "--user"):
            headers["Authorization"] = "Basic " + base64.b64encode((value or "").encode()).decode()
            i += 2
        elif word == "--url":
            url, i = value, i + 2
        elif word.startswith("-"):
            i += 1  # flags without meaning here: -s, -v, -L, -k, --compressed ...
        else:
            url, i = word, i + 1
    if not url:
        raise ImportFailed("the command has no URL")
    method = method or ("POST" if body is not None else "GET")
    content_type = next((v for k, v in headers.items() if k.lower() == "content-type"), content_type)
    return one_operation(method, url, headers, body, content_type, synth_id(method, url))
