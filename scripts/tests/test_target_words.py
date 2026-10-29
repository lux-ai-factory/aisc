"""In our pages and docs, a target is what an evaluation assesses: the system or a component on its AI card,
or a local model file. A model a test uses as a tool (judge, attacker, grader, embedder) is a helper model,
and the dataset column role named "target" in the datashape vocabulary is the label column."""
import re
from html.parser import HTMLParser

import pytest

from conftest import ROOT

PAGES = sorted((ROOT / "homepage").glob("*.html"))
DOCS = [ROOT / "README.md", ROOT / "docs/guide.md", ROOT / "docs/architecture.md"] + \
    sorted((ROOT / "docs/appendices").glob("*.md"))


class _Text(HTMLParser):
    """A page's words a person reads: text between tags and the string literals its scripts write into
    the page; never tag names, attributes, CSS or script comments and code."""

    def __init__(self):
        super().__init__()
        self.words, self._in = [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._in = tag

    def handle_endtag(self, tag):
        if tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._in == "style":
            return
        if self._in == "script":
            self.words += [m.group(2) for m in re.finditer(r"""(['"])((?:\\.|(?!\1).)*)\1""", data)]
        else:
            self.words.append(data)


def page_text(path):
    reader = _Text()
    reader.feed(path.read_text())
    return " ".join(reader.words)


def doc_text(path):
    """A Markdown doc's prose: fenced blocks and inline code (identifiers, commands) left out."""
    text = re.sub(r"```.*?```", " ", path.read_text(), flags=re.S)
    return re.sub(r"`[^`\n]*`", " ", text)


WRITTEN = [(p.relative_to(ROOT).as_posix(), page_text(p)) for p in PAGES] + \
          [(p.relative_to(ROOT).as_posix(), doc_text(p)) for p in DOCS]


@pytest.mark.parametrize("name,text", WRITTEN, ids=[n for n, _ in WRITTEN])
def test_a_target_is_never_a_column_or_a_tool_model(name, text):
    assert not re.search(r"\btarget[\s-]+(columns?|models?)\b", text, re.I), name


@pytest.mark.parametrize("name,text", WRITTEN, ids=[n for n, _ in WRITTEN])
def test_a_model_used_as_a_tool_is_called_a_helper_model(name, text):
    if re.search(r"\b(judge|attacker|grader|embedder)s?\b", text, re.I):
        assert re.search(r"\bhelper models?\b", text, re.I), name


@pytest.mark.parametrize("name,text", WRITTEN, ids=[n for n, _ in WRITTEN])
def test_helper_names_only_a_helper_model(name, text):
    """"helper" alone would blur the AI assistants of steps 1 and 2 with the models a test uses."""
    for m in re.finditer(r"(?<![\w/-])helpers?(?![\w-])", text, re.I):     # /helpers.html is a page, not a word
        assert re.match(r"\s+models?\b", text[m.end():], re.I), (name, text[max(0, m.start() - 60):m.end() + 40])


def test_the_guide_says_what_a_target_is_and_what_a_helper_model_is():
    guide = doc_text(ROOT / "docs/guide.md")
    said = [para for para in re.split(r"\n(?=- \*\*)|\n\n", guide) if re.search(r"\btarget\b", para)]
    about = " ".join(said)
    for word in ("assess", "component", "AI card", "local model file", "helper model", "judge"):
        assert word.lower() in about.lower(), word
