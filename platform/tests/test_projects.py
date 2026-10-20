# The platform's own notion of a project: created once, referenced by every
# module later. These tests are about the rules that decide identity, so they
# need no database.
import uuid

import pytest

from platform_service.projects import (
    InvalidProject,
    normalise_name,
    slug_for,
    validate_slug,
)
from tests.conftest import ALICE, needs_database


def test_a_name_becomes_a_url_safe_slug():
    assert slug_for("MicroCredit Assist Score (MCAS)") == "microcredit-assist-score-mcas"


def test_accents_and_punctuation_are_folded_not_dropped_silently():
    assert slug_for("Évaluation du modèle, v2") == "evaluation-du-modele-v2"


def test_runs_of_separators_collapse():
    assert slug_for("a   b___c---d") == "a-b-c-d"


def test_a_slug_never_starts_or_ends_with_a_separator():
    s = slug_for("  --hello--  ")
    assert s == "hello"


def test_a_name_with_nothing_usable_is_refused_rather_than_guessed():
    with pytest.raises(InvalidProject, match="no web address can be made from '!!! \\?\\?\\?'"):
        slug_for("!!! ???")


def test_a_name_is_required():
    for bad in ("", "   ", None):
        with pytest.raises(InvalidProject):
            normalise_name(bad)


def test_a_name_keeps_its_characters_but_loses_surrounding_space():
    assert normalise_name("  MCAS v1.2.0  ") == "MCAS v1.2.0"


def test_an_explicit_slug_is_validated_not_rewritten():
    assert validate_slug("mcas-2026") == "mcas-2026"
    for bad in ("MCAS", "mc as", "mcas!", "-mcas", "mcas-", "", "a" * 65):
        with pytest.raises(InvalidProject):
            validate_slug(bad)


def test_slugs_are_bounded_so_they_fit_a_path():
    assert len(slug_for("x" * 200)) <= 64


# A project is named two ways: the slug people read in a URL, and the pid rows
# point at. Modules are handed whichever their page has, so the platform takes
# either.
def test_a_pid_is_recognised_as_a_pid():
    from platform_service.projects import looks_like_pid

    assert looks_like_pid("01399e17-4b01-4be9-997a-7f5e3574ab22")
    assert looks_like_pid("01399E17-4B01-4BE9-997A-7F5E3574AB22")


def test_a_slug_is_not_mistaken_for_one():
    from platform_service.projects import looks_like_pid

    assert not looks_like_pid("microcredit-assist-score-mcas")
    assert not looks_like_pid("")
    assert not looks_like_pid("01399e17-4b01-4be9-997a")


# A slug shaped like a pid is read as a pid by every lookup, so its project could never
# be opened by its slug, and one equal to another project's pid would name that project.
PID_SHAPED = "0f8fad5b-d9cb-469f-a165-70867728950e"


def test_an_explicit_slug_shaped_like_a_pid_is_refused():
    with pytest.raises(InvalidProject):
        validate_slug(PID_SHAPED)


def test_a_name_shaped_like_a_pid_gets_a_slug_that_is_not():
    from platform_service.projects import looks_like_pid

    slug = slug_for(PID_SHAPED)
    assert not looks_like_pid(slug)
    assert slug.startswith(PID_SHAPED)
    assert slug_for(PID_SHAPED.upper()) == slug


@needs_database
def test_the_api_refuses_a_pid_shaped_slug_and_opens_a_pid_shaped_name_by_its_slug(client, as_user):
    shaped = str(uuid.uuid4())
    refused = client.post("/projects", json={"name": "x", "slug": shaped}, headers=as_user(ALICE))
    assert refused.status_code == 422, refused.text
    made = client.post("/projects", json={"name": shaped}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    assert made.json()["slug"] != shaped
    opened = client.get(f"/projects/{made.json()['slug']}", headers=as_user(ALICE))
    assert opened.status_code == 200, opened.text
    assert opened.json()["pid"] == made.json()["pid"]
