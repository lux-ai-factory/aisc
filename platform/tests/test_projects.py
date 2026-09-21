# The platform's own notion of a project: created once, referenced by every
# module later. These tests are about the rules that decide identity, so they
# need no database.
import pytest

from platform_service.projects import (
    InvalidProject,
    normalise_name,
    slug_for,
    validate_slug,
)


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
    with pytest.raises(InvalidProject):
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
