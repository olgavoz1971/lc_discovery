"""Tests for personal cross-identification helpers."""

from astropy.table import Table

from lc_discovery.providers.personal_ts.cross_ident import (
    alias_matches_identifiers,
    identifier_tokens,
    lookup_object_id_by_alias,
)
from lc_discovery.providers.personal_ts.resolve_target import (
    resolve_personal_target_name,
    target_name_candidates,
)


def test_identifier_tokens_splits_semicolons():
    """Semicolon-separated identifiers split into trimmed alias tokens."""
    tokens = identifier_tokens("MO Psc;SDSS J231110.88+013002.7;ZTF21abvicen")
    assert tokens == ["MO Psc", "SDSS J231110.88+013002.7", "ZTF21abvicen"]


def test_alias_matches_identifiers_is_case_insensitive():
    """Cross-ident matching ignores surrounding spaces and letter case."""
    identifiers = "MO Psc;SDSS J231110.88+013002.7"
    assert alias_matches_identifiers("mo psc", identifiers)
    assert alias_matches_identifiers("  MO   Psc ", identifiers)
    assert not alias_matches_identifiers("MO PscX", identifiers)


def test_target_name_candidates_normalises_messy_spellings():
    """Messy UI spellings expand to underscore and title-case candidates."""
    candidates = target_name_candidates("aA_AND")
    assert "aA_AND" in candidates
    assert "Aa_And" in candidates


def test_resolve_personal_target_name_uses_cross_ident_table(monkeypatch):
    """Cross-ident aliases resolve to archive object ids before Simbad."""
    objects_table = Table(
        {
            "object_id": ["MO_Psc"],
            "identifiers": ["MO Psc;SDSS J231110.88+013002.7;ZTF21abvicen"],
        }
    )

    def fake_tap(url, adql, dialect=None):
        if "personal.objects" in adql and "MO Psc" in adql:
            return objects_table
        return Table(names=["object_id", "identifiers"])

    monkeypatch.setattr(
        "lc_discovery.providers.personal_ts.cross_ident.run_tap_sync_query",
        fake_tap,
    )

    match = resolve_personal_target_name("MO Psc")
    assert match is not None
    assert match.archive_id == "MO_Psc"
    assert match.match_kind == "personal_cross_ident"
    assert match.matched_label == "MO Psc"


def test_lookup_object_id_by_alias_verifies_exact_token(monkeypatch):
    """LIKE pre-filter hits are accepted only for exact semicolon tokens."""
    objects_table = Table(
        {
            "object_id": ["MO_Psc"],
            "identifiers": ["MO Psc;SDSS J231110.88+013002.7"],
        }
    )

    def fake_tap(url, adql, dialect=None):
        return objects_table

    monkeypatch.setattr(
        "lc_discovery.providers.personal_ts.cross_ident.run_tap_sync_query",
        fake_tap,
    )

    assert lookup_object_id_by_alias("MO Psc") == ("MO_Psc", "MO Psc")
    assert lookup_object_id_by_alias("MO PscX") is None
