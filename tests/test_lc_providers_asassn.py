"""Tests for the ASAS-SN Sky Patrol lightcurve provider."""

from __future__ import annotations

import io
from unittest.mock import MagicMock

import pandas as pd
import pytest
import requests
from astropy.table import Table

from lc_discovery.providers.asassn import config
from lc_discovery.providers.asassn.fetch_metadata import votable_from_band_table
from lc_discovery.providers.asassn.catalog import map_metadata_table_to_catalog
from lc_discovery.providers.asassn.provider import AsassnProvider
from lc_discovery.providers.asassn.skypatrol_fetch import fetch_discovery_cone
from lc_discovery.catalog_schema import read_discovery_truncation_meta
from catalogue_numbers import AA_AND
from lc_discovery.lc_key import decode_lc_key
from issued import load_issued


def _sample_metadata_df() -> pd.DataFrame:
    """One ``stellar_main`` discovery row for AA And."""
    return pd.DataFrame(
        {
            "asas_sn_id": [85900701048],
            "ra_deg": [AA_AND.ra_deg],
            "dec_deg": [AA_AND.dec_deg],
            "pstarrs_g_mag": [10.898],
            "gaia_id": [AA_AND.source_id],
        }
    )


def test_map_metadata_expands_two_candidate_bands():
    """One metadata row becomes g and V candidate catalogue rows."""
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 2
    assert set(catalog["filter_name"]) == {config.ASASSN_G_FILTER_NAME, config.ASASSN_V_FILTER_NAME}
    g_rows = catalog[catalog["filter_name"] == config.ASASSN_G_FILTER_NAME]
    assert float(g_rows["mag"][0]) == pytest.approx(10.898)
    v_rows = catalog[catalog["filter_name"] == config.ASASSN_V_FILTER_NAME]
    assert v_rows["mag"].mask.all()
    assert all(catalog["provider_note"] == config.DISCOVERY_CATALOG_PROVIDER_NOTE)


def test_catalog_lc_key_payload():
    """Fetch handle stores canonical asas_sn_id and band."""
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload == {"asas_sn_id": "85900701048", "band": "g"}


def test_votable_from_band_table_keeps_camera():
    """Band slice writes a calibrated VOTable and keeps the camera column."""
    band_df = pd.DataFrame(
        {
            "jd": [2459000.5, 2459001.5],
            "flux": [120.0, 125.0],
            "flux_err": [0.3, 0.4],
            "camera": ["bs", "br"],
        }
    )
    payload = votable_from_band_table(
        band_df,
        asas_sn_id=85900701048,
        band_code="g",
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        epoch_jd=None,
        period_days=None,
    )
    volc = load_issued(payload)
    assert len(volc) == 2
    assert list(volc["camera"]) == ["bs", "br"]


def test_votable_from_band_table_without_camera():
    """The issued VOTable omits camera when Sky Patrol omits that column."""
    band_df = pd.DataFrame(
        {
            "jd": [2459000.5, 2459001.5],
            "flux": [120.0, 125.0],
            "flux_err": [0.3, 0.4],
        }
    )
    payload = votable_from_band_table(
        band_df,
        asas_sn_id=85900701048,
        band_code="g",
        ra_deg=None,
        dec_deg=None,
        epoch_jd=None,
        period_days=None,
    )
    volc = load_issued(payload)
    assert len(volc) == 2
    assert "camera" not in volc.colnames


def test_asassn_camera_is_in_the_issued_votable():
    """Per-epoch camera codes remain on the issued VOTable."""
    band_df = pd.DataFrame(
        {
            "jd": [2459000.5, 2459001.5],
            "flux": [120.0, 125.0],
            "flux_err": [0.3, 0.4],
            "camera": ["bs", "br"],
        }
    )
    payload = votable_from_band_table(
        band_df,
        asas_sn_id=85900701048,
        band_code="g",
        ra_deg=None,
        dec_deg=None,
        epoch_jd=None,
        period_days=None,
    )
    volc = load_issued(payload)
    assert list(volc["camera"]) == ["bs", "br"]


def test_search_catalog_by_gaia_id(monkeypatch):
    """search_catalog maps mocked metadata to two catalogue rows."""
    provider = AsassnProvider()

    def _fake_gaia(_gaia_id):
        return _sample_metadata_df()

    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_discovery_by_gaia_id",
        _fake_gaia,
    )

    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    assert len(table) == 2


def test_search_catalog_cone_truncation_hint(monkeypatch):
    """Cone search annotates truncation when source count hits the cap."""
    provider = AsassnProvider()
    rows = []
    for index in range(provider.discovery_cone_query_row_limit()):
        rows.append(
            {
                "asas_sn_id": 85900701048 + index,
                "ra_deg": AA_AND.ra_deg,
                "dec_deg": AA_AND.dec_deg,
                "pstarrs_g_mag": 10.0,
            }
        )

    def _fake_cone(**_kwargs):
        return pd.DataFrame(rows)

    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_discovery_cone",
        _fake_cone,
    )

    table = provider.search_catalog(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert len(table) == provider.discovery_cone_query_row_limit() * 2
    may_be, detail = read_discovery_truncation_meta(table)
    assert may_be is True
    assert detail is not None
    assert "ASAS-SN sources" in detail


def test_fetch_lightcurve_empty_band(monkeypatch):
    """Fetch fails fast when the candidate band has no photometry rows."""
    provider = AsassnProvider()
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    v_key = catalog[catalog["filter_name"] == config.ASASSN_V_FILTER_NAME]["lc_key"][0]

    photometry = pd.DataFrame(
        {
            "jd": [2459000.5],
            "flux": [120.0],
            "flux_err": [0.3],
            "phot_filter": ["g"],
            "camera": ["bs"],
        }
    )

    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_photometry_by_asas_sn_id",
        lambda _sid: photometry,
    )
    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_epoch_period_for_asas_sn_id",
        lambda _sid: (None, None),
    )
    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_discovery_by_asas_sn_id",
        lambda _sid: _sample_metadata_df(),
    )

    with pytest.raises(ValueError, match="no observations"):
        provider.fetch_lightcurve(v_key)


def test_fetch_lightcurve_builds_volc(monkeypatch):
    """Fetch downloads photometry and returns a calibrated VOTable."""
    provider = AsassnProvider()
    catalog = map_metadata_table_to_catalog(
        _sample_metadata_df(),
        provider_id=config.PROVIDER_ID,
    )
    g_key = catalog[catalog["filter_name"] == config.ASASSN_G_FILTER_NAME]["lc_key"][0]

    photometry = pd.DataFrame(
        {
            "jd": [2459000.5, 2459001.5],
            "flux": [120.0, 125.0],
            "flux_err": [0.3, 0.4],
            "phot_filter": ["g", "g"],
            "camera": ["bs", "br"],
        }
    )

    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_photometry_by_asas_sn_id",
        lambda _sid: photometry,
    )
    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_epoch_period_for_asas_sn_id",
        lambda _sid: (2459000.0, 0.46),
    )
    monkeypatch.setattr(
        "lc_discovery.providers.asassn.provider.fetch_discovery_by_asas_sn_id",
        lambda _sid: _sample_metadata_df(),
    )

    payload = provider.fetch_lightcurve(g_key)
    volc = load_issued(payload)
    assert len(volc) == 2
    assert volc.table.meta.get("period") == pytest.approx(0.46)
    assert list(volc["camera"]) == ["bs", "br"]
    assert volc["flux"][0] == pytest.approx(0.12)
    assert volc.photdms["flux"].filter.filter_id == config.ASASSN_G_FILTER_IDENTIFIER
    assert float(volc.photdms["flux"].photcal.zp_flux.value) == pytest.approx(3631.0)
    assert volc.photdms["flux_err"].photcal is volc.photdms["flux"].photcal
    assert b'name="epoch" datatype="double" value="2459000.0" unit="d" ucd="time.epoch" ref="ts"' in payload


def test_fetch_discovery_cone_maps_http_error_to_pipe_exception():
    """Sky Patrol HTTP failures surface as ValueError."""

    class _FailingClient:
        def cone_search(self, *args, **kwargs):
            response = MagicMock()
            response.status_code = 500
            raise requests.HTTPError(
                "500 Server Error: INTERNAL SERVER ERROR",
                response=response,
            )

    with pytest.raises(ValueError, match="HTTP 500"):
        fetch_discovery_cone(
            ra_deg=1.0,
            dec_deg=0.0,
            radius_arcsec=10.0,
            client=_FailingClient(),
        )
