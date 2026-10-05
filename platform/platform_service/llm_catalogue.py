"""The LLM providers a project can use, and the live listing of each one's models.

No database and no FastAPI here: `app.py` checks the caller and the project, reads the
stored key through `llm_store`, then calls `list_models`.

Rules:
- A hosted provider is only ever called at its constant URL in `MODELS_URL`; only
  `ollama` and `compatible` use a base URL the admin stored.
- Redirects are never followed, so a key cannot travel to another host.
- Errors are fixed sentences. The provider's answer body, the key and the exception
  text never reach a message or a log record.
- Bounds: a timeout per request, at most `MAX_PAGES` pages, `MAX_BYTES` per page,
  `MAX_IDS` ids kept.

Other modules must read `PROVIDERS` and `MODELS_URL` as attributes of this module at
call time (tests patch and even reload it).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Provider:
    label: str
    key_required: bool
    base_url_editable: bool
    lister: str  # how its model list is fetched, see `_fetch_ids`


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider("Anthropic", True, False, "anthropic"),
    "compatible": Provider("OpenAI-compatible endpoint", False, True, "compatible"),
    "deepseek": Provider("DeepSeek", True, False, "openai"),
    "google": Provider("Google Gemini", True, False, "google"),
    "groq": Provider("Groq", True, False, "openai"),
    "meta": Provider("Meta Llama", True, False, "openai"),
    "mistral": Provider("Mistral AI", True, False, "mistral"),
    "ollama": Provider("Ollama", False, True, "ollama"),
    "openai": Provider("OpenAI", True, False, "openai"),
    "openrouter": Provider("OpenRouter", True, False, "openai"),
    "qwen": Provider("Qwen (Alibaba Cloud)", True, False, "openai"),
    "together": Provider("Together AI", True, False, "together"),
    "xai": Provider("xAI", True, False, "openai"),
}

#: Where each hosted provider lists its models. Constants on purpose: no environment
#: variable can send a stored key somewhere else.
MODELS_URL: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "mistral": "https://api.mistral.ai/v1/models",
    "deepseek": "https://api.deepseek.com/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "meta": "https://api.llama.com/compat/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/models",
    "together": "https://api.together.xyz/v1/models",
    "xai": "https://api.x.ai/v1/models",
}

ANTHROPIC_VERSION = "2023-06-01"
MAX_PAGES = 10
MAX_BYTES = 5 * 1024 * 1024
MAX_IDS = 5000
MAX_ID_LEN = 200
CONNECT_TIMEOUT = 5.0
DEFAULT_TIMEOUT = 10.0


class ListingFailed(Exception):
    """A listing went wrong; `str()` is the fixed message the page shows."""


def list_timeout() -> float:
    """Seconds per request, from PLATFORM_LLM_LIST_TIMEOUT (read on every call)."""
    try:
        value = float(os.environ.get("PLATFORM_LLM_LIST_TIMEOUT") or DEFAULT_TIMEOUT)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def list_models(provider: str, api_key: str | None = None, base_url: str | None = None) -> dict:
    """The provider's model ids, live: {"models": [...], "error": None} or {"models": [], "error": msg}.

    Never raises because of the provider. An unknown provider is a KeyError (the API
    checks the id before calling)."""
    entry = PROVIDERS[provider]
    label = entry.label
    timeout = list_timeout()
    if entry.base_url_editable and not base_url:
        return {"models": [], "error": f"{label} has no base URL"}
    client = httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(timeout, connect=min(CONNECT_TIMEOUT, timeout)),
        trust_env=False,  # no proxy variable may carry the key elsewhere
    )
    try:
        with client:
            ids = _fetch_ids(client, provider, entry, api_key, base_url)
    except ListingFailed as failure:
        logger.info("listing models for %s failed", provider)
        return {"models": [], "error": str(failure)}
    except httpx.TimeoutException:
        logger.info("listing models for %s failed: timeout", provider)
        shown = int(timeout) if float(timeout).is_integer() else timeout
        return {"models": [], "error": f"{label} did not answer within {shown} s"}
    except (httpx.HTTPError, OSError):
        logger.info("listing models for %s failed: unreachable", provider)
        return {"models": [], "error": f"could not reach {label}"}
    return {"models": _clean(ids), "error": None}


# one lister per kind
def _fetch_ids(client, provider, entry, api_key, base_url) -> list:
    kind = entry.lister
    if kind == "openai":
        body = _get_json(client, entry.label, MODELS_URL[provider], _bearer(api_key))
        return _ids_from(_data_list(body, entry.label), "id")
    if kind == "mistral":
        body = _get_json(client, entry.label, MODELS_URL[provider], _bearer(api_key))
        items = [i for i in _data_list(body, entry.label) if _is_mistral_chat(i)]
        return _ids_from(items, "id")
    if kind == "anthropic":
        return _anthropic(client, entry.label, MODELS_URL[provider], api_key)
    if kind == "google":
        return _google(client, entry.label, MODELS_URL[provider], api_key)
    if kind == "together":
        body = _get_json(client, entry.label, MODELS_URL[provider], _bearer(api_key))
        items = body if isinstance(body, list) else _data_list(body, entry.label)
        kept = [i for i in items if not isinstance(i, dict) or i.get("type") in (None, "chat", "language")]
        return _ids_from(kept, "id")
    if kind == "ollama":
        root = base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        body = _get_json(client, entry.label, root + "/api/tags", {})
        if not isinstance(body, dict) or not isinstance(body.get("models"), list):
            raise ListingFailed(f"{entry.label} did not send a model list")
        return _ids_from(body["models"], "name")
    if kind == "compatible":
        headers = _bearer(api_key) if api_key else {}
        body = _get_json(client, entry.label, base_url.rstrip("/") + "/models", headers)
        items = body if isinstance(body, list) else _data_list(body, entry.label)
        return _ids_from(items, "id")
    raise ListingFailed(f"{entry.label} did not send a model list")


def _anthropic(client, label, url, api_key) -> list:
    headers = {"x-api-key": api_key or "", "anthropic-version": ANTHROPIC_VERSION}
    params = {"limit": "1000"}
    ids: list = []
    for _page in range(MAX_PAGES):
        body = _get_json(client, label, url, headers, params)
        ids += _ids_from(_data_list(body, label), "id")
        last_id = body.get("last_id")
        if body.get("has_more") is not True or not isinstance(last_id, str) or not last_id:
            break
        params = {"limit": "1000", "after_id": last_id}
    return ids  # when the page cap is hit, what was collected so far


def _google(client, label, url, api_key) -> list:
    headers = {"x-goog-api-key": api_key or ""}  # never ?key=, which ends up in logged URLs
    params = {"pageSize": "1000"}
    ids: list = []
    for _page in range(MAX_PAGES):
        body = _get_json(client, label, url, headers, params)
        if not isinstance(body, dict) or not isinstance(body.get("models"), list):
            raise ListingFailed(f"{label} did not send a model list")
        for item in body["models"]:
            if not isinstance(item, dict):
                continue
            methods = item.get("supportedGenerationMethods")
            name = item.get("name")
            if isinstance(methods, list) and "generateContent" in methods and isinstance(name, str):
                ids.append(name.removeprefix("models/"))
        token = body.get("nextPageToken")
        if not isinstance(token, str) or not token:
            break
        params = {"pageSize": "1000", "pageToken": token}
    return ids


# one bounded GET
def _get_json(client, label, url, headers, params=None):
    """GET one page and decode it, within the size bound; any status but 2xx is an error."""
    not_a_list = ListingFailed(f"{label} did not send a model list")
    with client.stream("GET", url, params=params, headers=headers) as response:
        code = response.status_code
        if code in (401, 403):
            raise ListingFailed(f"{label} refused the key (HTTP {code})")
        if not 200 <= code < 300:
            raise ListingFailed(f"{label} answered HTTP {code}")
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_BYTES:
            raise not_a_list
        chunks, total = [], 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > MAX_BYTES:
                raise not_a_list
            chunks.append(chunk)
    try:
        return json.loads(b"".join(chunks))
    except (ValueError, UnicodeDecodeError):
        raise not_a_list from None


def _bearer(api_key) -> dict:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _data_list(body, label) -> list:
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        return body["data"]
    raise ListingFailed(f"{label} did not send a model list")


def _is_mistral_chat(item) -> bool:
    if not isinstance(item, dict) or "capabilities" not in item:
        return True
    capabilities = item["capabilities"]
    return isinstance(capabilities, dict) and bool(capabilities.get("completion_chat"))


def _ids_from(items, field) -> list:
    return [item.get(field) for item in items if isinstance(item, dict)]


def _clean(ids) -> list[str]:
    """Strings of 1 to MAX_ID_LEN characters, deduplicated, sorted, at most MAX_IDS."""
    kept = {i for i in ids if isinstance(i, str) and 1 <= len(i) <= MAX_ID_LEN}
    return sorted(kept)[:MAX_IDS]
