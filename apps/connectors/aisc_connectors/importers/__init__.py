"""Every technology becomes the same canonical OpenAPI document (spec D3)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ImportResult:
    document: dict
    warnings: list[str] = field(default_factory=list)
    auth_suggestion: dict | None = None
    #: Secret values found in the source (a cURL Authorization header, say). They are offered to
    #: the admin to store in the vault and are never written into the document.
    detected_secrets: dict[str, str] = field(default_factory=dict)
    #: For LLM-shaped connectors: how the facades should call the chat operation.
    chat_suggestion: dict | None = None
