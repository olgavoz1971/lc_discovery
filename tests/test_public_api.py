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
    assert "tess" in ids


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


def _tess_key() -> str:
    """Builds a valid TESS fetch key."""
    from lc_discovery.lc_key import encode_lc_key

    return encode_lc_key(
        "tess", {"tic": 1, "sector": 4, "author": "SPOC", "exptime": 120.0}
    )


def test_purge_cache_tess_deletes_one_product(monkeypatch):
    """purge_cache reaches the TESS plugin with the identity of one product."""
    seen = {}

    def fake_purge(**kwargs):
        seen.update(kwargs)
        return True

    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.purge_archive_product", fake_purge
    )
    assert lc_discovery.purge_cache(_tess_key()) is True
    assert seen == {"tic": 1, "sector": 4, "author": "SPOC", "exptime": 120.0}


def test_purge_cache_mission_without_local_cache_raises():
    """A mission with no local product cache fails fast."""
    from lc_discovery.lc_key import encode_lc_key

    key = encode_lc_key("ogle_ocvs", {"object_id": "X"})
    with pytest.raises(ValueError, match="no local product cache"):
        lc_discovery.purge_cache(key)


def test_tess_force_refresh_redownloads(monkeypatch):
    """fetch(force_refresh=True) purges and downloads again instead of reusing."""
    calls = []

    def fake_redownload(**kwargs):
        calls.append("redownload")
        return True, object(), {"obs_id": "x"}

    def fake_download(**kwargs):
        calls.append("download")
        return object(), {"obs_id": "x"}

    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.redownload_archive_product", fake_redownload
    )
    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.download_archive_product", fake_download
    )
    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.votable_from_lightcurve",
        lambda *a, **k: b"<VOTABLE/>",
    )
    assert lc_discovery.fetch(_tess_key(), force_refresh=True) == b"<VOTABLE/>"
    assert lc_discovery.fetch(_tess_key()) == b"<VOTABLE/>"
    assert calls == ["redownload", "download"]


def test_purge_cache_gaia_aip_removes_source_record(tmp_path, monkeypatch):
    """purge_cache deletes the prefetched record of the key's source only."""
    from lc_discovery.lc_key import encode_lc_key
    from lc_discovery.providers.gaia_dr3_aip import config, prefetch_store

    monkeypatch.setattr(config, "PREFETCH_CACHE_DIR", tmp_path)
    prefetch_store.store_epoch_photometry(11, {"x": 1})
    prefetch_store.store_epoch_photometry(22, {"x": 2})
    key = encode_lc_key("gaia_dr3_aip", {"source_id": 11, "band": "G"})
    assert lc_discovery.purge_cache(key) is True
    assert lc_discovery.purge_cache(key) is False
    assert not prefetch_store.epoch_photometry_is_cached(11)
    assert prefetch_store.epoch_photometry_is_cached(22)
