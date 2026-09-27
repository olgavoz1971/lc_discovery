"""Tests for the public package calls."""

from __future__ import annotations

import pytest

import lc_discovery
from lc_discovery import (
    MissionArchiveMatch,
    archive_id_from_identifiers,
    list_missions,
    resolve_target,
)


def test_public_exports_do_not_include_get_provider():
    """The package root does not export plugin accessors."""
    assert "get_provider" not in lc_discovery.__all__
    assert "MissionLightcurveProvider" not in lc_discovery.__all__


def test_list_missions_returns_registered_slugs():
    """list_missions includes the nine review missions."""
    ids = {item.mission_id for item in list_missions()}
    assert "ogle_ocvs" in ids
    assert "ztf_dr24" in ids


def test_resolve_target_ogle_loose_spelling():
    """OGLE maps a spaced Simbad-style name to an archive id."""
    match = resolve_target("ogle_ocvs", "OGLE SMC-ECL- 5425")
    assert match is not None
    assert isinstance(match, MissionArchiveMatch)
    assert match.archive_id == "OGLE-SMC-ECL-05425"


def test_archive_id_from_identifiers_ogle():
    """OGLE picks an object_id from identifier strings, not a Simbad type."""
    match = archive_id_from_identifiers(
        "ogle_ocvs",
        ["TYC 1-2-1", "OGLE SMC-ECL- 5425"],
        query_name="OGLE SMC-ECL- 5425",
        main_id="V* DP Peg",
    )
    assert match is not None
    assert match.archive_id == "OGLE-SMC-ECL-05425"
    assert match.match_kind == "ogle_object_id"


def test_resolve_target_unknown_mission():
    """Unknown mission slugs raise ValueError."""
    with pytest.raises(ValueError, match="Unknown mission"):
        resolve_target("not_a_mission", "AA And")
