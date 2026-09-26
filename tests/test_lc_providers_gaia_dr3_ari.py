"""Tests for the Gaia DR3 (ARI) TAP provider (``gaia_source`` discovery)."""

from __future__ import annotations

from pathlib import Path

import pytest
from astropy.table import Table

from lc_discovery.providers.gaia_dr3_ari import config
from lc_discovery.providers.gaia_dr3_ari.datalink import build_timeseries_datalink_url
from lc_discovery.providers.gaia_dr3_ari.provider import GaiaDr3AriProvider
from lc_discovery.providers.gaia_dr3_ari.source_catalog import map_source_table_to_catalog
from catalogue_numbers import AA_AND
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.tap.dialect import TapQueryDialect


def _sample_source_table() -> Table:
    """Builds one ``gaia_source`` discovery row for AA And."""
    return Table(
        {
            "source_id": [AA_AND.source_id],
            "ra": [AA_AND.ra_deg],
            "dec": [AA_AND.dec_deg],
            "phot_g_mean_mag": [12.34],
            "best_class_name": ["EclipsingBinary"],
        }
    )


def test_timeseries_datalink_url():
    """Datalink URLs use ``sourceid`` query parameter on the Heidelberg endpoint."""
    url = build_timeseries_datalink_url(AA_AND.source_id)
    assert url == (
        f"{config.TIMESERIES_DATALINK_BASE_URL}?sourceid={AA_AND.source_id}"
    )


def test_map_source_table_expands_to_three_bands():
    """One source row produces G, BP, and RP catalogue rows."""
    catalog = map_source_table_to_catalog(
        _sample_source_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 3
    assert set(catalog["filter_name"]) == {"Gaia G", "Gaia BP", "Gaia RP"}
    assert all(catalog["provider_note"] == config.DISCOVERY_CATALOG_PROVIDER_NOTE)
    g_rows = catalog[catalog["filter_name"] == "Gaia G"]
    assert float(g_rows["mag"][0]) == pytest.approx(12.34)
    assert str(g_rows["object_class"][0]) == "EclipsingBinary"


def test_source_catalog_lc_key_payload():
    """Each catalogue row stores source_id, band, and table_id for fetch."""
    catalog = map_source_table_to_catalog(
        _sample_source_table(),
        provider_id=config.PROVIDER_ID,
    )
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload["source_id"] == str(AA_AND.source_id)
    assert payload["band"] == "G"
    assert payload["table_id"] == 0
    assert payload["filter_name"] == "Gaia G"
    assert "access_url" not in payload


def test_ari_adql_source_id_query():
    """Direct lookup ADQL joins classifier results on ``gaia_source``."""
    adql = config.adql_gaia_source_by_source_id(AA_AND.source_id)
    assert f"FROM {config.GAIA_SOURCE_TABLE} AS gs" in adql
    assert f"LEFT JOIN {config.VARI_CLASSIFIER_RESULT_TABLE} AS vcr" in adql
    assert f"gs.source_id = {AA_AND.source_id}" in adql
    assert "gs.has_epoch_photometry = 'True'" in adql
    assert "vcr.best_class_name" in adql


def test_ari_adql_cone_query():
    """Cone ADQL uses ICRS geometry on ``gs.ra``/``gs.dec`` with classifier join."""
    adql = config.adql_gaia_source_cone(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert f"FROM {config.GAIA_SOURCE_TABLE} AS gs" in adql
    assert "CONTAINS(POINT('ICRS', gs.ra, gs.dec), CIRCLE('ICRS'" in adql
    assert f"CIRCLE('ICRS', {AA_AND.ra_deg}, {AA_AND.dec_deg}," in adql
    adql_limited = config.adql_gaia_source_cone(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
        row_limit=100,
    )
    assert "SELECT TOP 100 " in adql_limited
    assert "ORDER BY random_index" in adql_limited


def test_ari_tap_dialect_is_adql_20():
    """ARI provider declares ADQL 2.0 for the Heidelberg TAP service."""
    assert config.TAP_QUERY_DIALECT == TapQueryDialect.ADQL_2_0


def test_ari_capabilities_no_discovery_time_filter():
    """Discovery does not apply ObsCore-style time bounds."""
    provider = GaiaDr3AriProvider()
    assert provider.capabilities.supports_discovery_time_filter is False
    assert provider.capabilities.provides_catalog_epoch_period is False


def test_ari_search_catalog_by_source_id(monkeypatch):
    """search_catalog maps one source row to three standard catalogue products."""
    provider = GaiaDr3AriProvider()
    captured: dict[str, str] = {}

    def _fake_tap(_url, adql, *, dialect):
        captured["dialect"] = dialect
        captured["adql"] = adql
        return _sample_source_table()

    monkeypatch.setattr(
        "lc_discovery.providers.gaia_dr3_ari.provider.run_tap_sync_query",
        _fake_tap,
    )

    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    assert len(table) == 3
    assert captured["dialect"] == TapQueryDialect.ADQL_2_0
    assert f"gs.source_id = {AA_AND.source_id}" in captured["adql"]


def test_ari_fetch_lightcurve_local_sample(monkeypatch):
    """fetch_lightcurve downloads one band via the timeseries datalink URL."""
    provider = GaiaDr3AriProvider()
    sample_path = (
        Path(__file__).resolve().parent / "data" / "gaia_ari.vot"
    )
    payload = sample_path.read_bytes()
    requested_url: list[str] = []

    def _fake_urlopen(request, timeout=0):
        requested_url.append(request.full_url)

        class _Resp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        return _Resp()

    monkeypatch.setattr(
        "urllib.request.urlopen",
        _fake_urlopen,
    )

    catalog = map_source_table_to_catalog(
        _sample_source_table(),
        provider_id=config.PROVIDER_ID,
    )
    lc_key = catalog["lc_key"][0]
    payload_out = provider.fetch_lightcurve(lc_key)
    assert requested_url == [build_timeseries_datalink_url(AA_AND.source_id)]
    import io

    from issued import load_issued

    volc = load_issued(payload_out)
    assert len(volc) == 20
    assert volc.photdms["mag"].filter.filter_id == "GAIADR3.G"
    assert float(volc.photdms["mag"].photcal.zp_mag.value) == 0.0
    assert volc.table.meta.get("period") == pytest.approx(1.7217551595287013)
