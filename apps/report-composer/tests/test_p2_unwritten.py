"""Part 2, D3.8 composer side (10-specs-part2.md R2-D3.8.3): blocks still holding the placeholder
"Write this section." in a prose option (rule R2-D3.7.3) are flagged in the editor, computed in Python, on
page render and in the outline route's answer (`unwritten: [option names]` per item). A hint, not a problem:
Save and Generate are not refused. Database tests with the v2 fake renderer plus one plugin block type.
"""
import copy

import pytest

from conftest import IDS, new_layout
from v2_fakes import FakeRendererV2, clean_presets, client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]
PLACEHOLDER = "Write this section."
BUILT_IN_HINT = "Not written yet: this text still holds the placeholder and is left out of the report."
PLUGIN_HINT = "Not written yet: this text still holds the placeholder."

PLUGIN_TYPE = {
    "type_id": "auditor_notes", "title": "Auditor notes", "contract_version": 1, "description": "A plugin block.",
    "new_instance_options": {},
    "options_schema": {"type": "object", "additionalProperties": False, "properties": {
        "title": {"type": "string", "maxLength": 200, "title": "Section title", "description": "Heading."},
        "notes": {"type": "string", "title": "Notes", "description": "The auditor's notes."}}},
    "default_options": {"title": "", "notes": ""}}


class WithPlugin(FakeRendererV2):
    def block_types(self):
        return super().block_types() + [copy.deepcopy(PLUGIN_TYPE)]


@pytest.fixture
def client_plugin(make_client):
    return make_client(WithPlugin())


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def editor(client, auth, blocks):
    lay = new_layout(client, auth, name=unique("Unwritten"), system_id=IDS["A_V2"], blocks=blocks)
    return lay, soup(client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text)


def li_text(doc, iid):
    return doc.find("li", attrs={"data-instance-id": iid}).get_text(" ", strip=True)


def test_r2_d3_8_3_built_in_blocks_holding_the_placeholder_are_flagged(client_v2, auth):
    free = v2blk("free_text", text=PLACEHOLDER)
    card = v2blk("ai_card", commentary=f"  {PLACEHOLDER} ")
    chapter = v2blk("chapter", title="Evidence", intro=PLACEHOLDER)
    written = v2blk("free_text", text="Our findings.")
    lay, doc = editor(client_v2, auth, [v2blk("cover"), free, chapter, card, written])
    for b in (free, card, chapter):
        assert BUILT_IN_HINT in li_text(doc, b["instance_id"]), b["block_type"]
    assert "Not written yet" not in li_text(doc, written["instance_id"])


def test_r2_d3_8_3_plugin_blocks_holding_the_placeholder_are_flagged(client_plugin, auth):
    notes = v2blk("auditor_notes", notes=PLACEHOLDER)
    lay, doc = editor(client_plugin, auth, [notes])
    text = li_text(doc, notes["instance_id"])
    assert PLUGIN_HINT in text and BUILT_IN_HINT not in text


def test_r2_d3_8_3_the_outline_answer_lists_unwritten_options(client_v2, auth):
    cover, free = v2blk("cover"), v2blk("free_text", text="Written")
    lay, _ = editor(client_v2, auth, [cover, free])
    blocks = [cover, v2blk("free_text", text=PLACEHOLDER), v2blk("ai_card", commentary=PLACEHOLDER),
              v2blk("chapter", title="C", intro=PLACEHOLDER), free]
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/outline", json={"blocks": blocks}, headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    got = [item.get("unwritten") for item in r.json()["outline"]]
    assert got == [[], ["text"], ["commentary"], ["intro"], []]


def test_r2_d3_8_3_the_outline_answer_flags_plugin_blocks_too(client_plugin, auth):
    lay, _ = editor(client_plugin, auth, [v2blk("cover")])
    blocks = [v2blk("auditor_notes", notes=PLACEHOLDER), v2blk("auditor_notes", notes="Done")]
    r = client_plugin.post(f"/api/p/alpha/layouts/{lay['id']}/outline", json={"blocks": blocks},
                           headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert [item.get("unwritten") for item in r.json()["outline"]] == [["notes"], []]


def test_r2_d3_8_3_a_hint_not_a_problem_save_and_generate_go_through(client_v2, auth):
    """Compatibility guard: the placeholder never blocks validation, save or generate (passes today)."""
    free = v2blk("free_text", text=PLACEHOLDER)
    lay, _ = editor(client_v2, auth, [v2blk("cover"), free])
    v = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/validate", headers=auth("alice")).json()
    assert v["valid"] is True
    g = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert g.status_code == 201, g.text[:300]
