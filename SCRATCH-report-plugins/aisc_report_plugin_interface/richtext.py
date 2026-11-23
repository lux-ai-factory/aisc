"""Light formatting for commentary, free text and plugins.

`render(text)` parses a small Markdown dialect (CommonMark plus pipe tables, raw HTML off, a single
newline is a line break, bare URLs stay text) and cleans the result against a fixed allowlist.
Headings become paragraphs, images become their alt text, and links keep only http, https and mailto.
It never raises: on any failure the escaped text comes back in one paragraph.
"""
from __future__ import annotations

import re

import nh3
from markdown_it import MarkdownIt
from markdown_it.token import Token
from markupsafe import Markup, escape

ALLOWED_TAGS = {"p", "br", "strong", "em", "ul", "ol", "li", "a", "table", "thead", "tbody", "tr", "th", "td",
                "code", "blockquote"}
URL_SCHEMES = {"http", "https", "mailto"}
MAX_CHARS = 20000

_MD = MarkdownIt("commonmark", {"html": False, "breaks": True, "linkify": False}).enable("table")
_SCHEME = re.compile(r"^\s*([a-zA-Z][a-zA-Z0-9+.\-]*):")


def _allowed_href(href: str) -> bool:
    match = _SCHEME.match(href or "")
    return bool(match) and match.group(1).lower() in URL_SCHEMES


def _clean_inline(children: list[Token]) -> list[Token]:
    out: list[Token] = []
    depth_stack: list[bool] = []
    for tok in children:
        if tok.type == "image":
            text = Token("text", "", 0)
            text.content = "".join(c.content for c in (tok.children or [])) or tok.content
            out.append(text)
            continue
        if tok.type == "link_open":
            keep = _allowed_href(str(tok.attrGet("href") or ""))
            depth_stack.append(keep)
            if keep:
                out.append(tok)
            continue
        if tok.type == "link_close":
            keep = depth_stack.pop() if depth_stack else True
            if keep:
                out.append(tok)
            continue
        out.append(tok)
    return out


def _transform(tokens: list[Token]) -> list[Token]:
    for tok in tokens:
        if tok.type in ("heading_open", "heading_close"):
            tok.type = "paragraph_open" if tok.type == "heading_open" else "paragraph_close"
            tok.tag = "p"
            tok.markup = ""
        elif tok.type == "inline" and tok.children:
            tok.children = _clean_inline(tok.children)
    return tokens


def render(text) -> Markup:
    """Light formatting to safe HTML (a Markup)."""
    source = "" if text is None else str(text)
    source = source[:MAX_CHARS]
    try:
        env: dict = {}
        tokens = _transform(_MD.parse(source, env))
        html = _MD.renderer.render(tokens, _MD.options, env)
        cleaned = nh3.clean(html, tags=ALLOWED_TAGS, attributes={"a": {"href"}, "*": set()},
                            url_schemes=URL_SCHEMES,
                            link_rel="noopener noreferrer")
        return Markup(cleaned)
    except Exception:  # noqa: BLE001 - never raise on user text
        return Markup("<p>") + escape(source) + Markup("</p>")
