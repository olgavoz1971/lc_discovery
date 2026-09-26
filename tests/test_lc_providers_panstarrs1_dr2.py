"""Tests for the Pan-STARRS1 DR2 MAST TAP lightcurve provider."""

from __future__ import annotations

import io

import pytest
from astropy.table import Table

from issued import load_issued

from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.providers.panstarrs1_dr2.fetch_metadata import votable_from_detections
from lc_discovery.providers.panstarrs1_dr2.mean_object_catalog import map_mean_object_table_to_catalog
from lc_discovery.providers.panstarrs1_dr2.provider import Panstarrs1Dr2Provider
from lc_discovery.providers.panstarrs1_dr2.ps1_names import format_ps1_object_name, parse_ps1_obj_id


@pytest.fixture
def provider():
    """Returns a Pan-STARRS1 DR2 provider instance."""
    return Panstarrs1Dr2Provider()


def test_format_ps1_object_name():
    """Display label is PS1 prefix plus normalised objID."""
    assert format_ps1_object_name(123456) == "PS1 123456"
    assert format_ps1_object_name("165243463579570976") == "PS1 165243463579570976"


def test_parse_ps1_obj_id_digits():
    """Long digit strings and prefixed ids parse as objID values."""
    assert parse_ps1_obj_id("123456789012345678") == 123456789012345678
    assert parse_ps1_obj_id("PS1 123456789012345678") == 123456789012345678
    assert parse_ps1_obj_id("Pan-STARRS1 123456789012345678") == 123456789012345678
    assert parse_ps1_obj_id("PS J001") is None
    assert parse_ps1_obj_id("999") is None


def test_provider_max_cone_radius_below_mast_limit(provider):
    """Cone radius cap stays inside the MAST PS1 TAP 0.25 deg service limit."""
    assert provider.max_discovery_search_radius_deg() < 0.25
    assert provider.max_discovery_search_radius_deg() == config.MAX_DISCOVERY_SEARCH_RADIUS_DEG


def test_adql_cone_includes_geometry_and_random_id():
    """Cone ADQL uses MAST geometry and randomId ordering."""
    adql = config.adql_mean_objects_cone(ra_deg=10.0, dec_deg=20.0, radius_arcsec=30.0, row_limit=50)
    assert "TOP 50" in adql
    assert "MeanObjectView" in adql
    assert "randomId" in adql
    assert "nDetections > 1" in adql
    assert "objname" not in adql


def test_map_mean_object_expands_bands_with_detections():
    """One mean-object row with g and r detections yields two catalogue rows."""
    tap = Table(
        {
            "objID": [999],
            "raMean": [10.0],
            "decMean": [20.0],
            "ng": [5],
            "nr": [2],
            "ni": [0],
            "nz": [0],
            "ny": [0],
            "gMeanPSFMag": [18.1],
            "rMeanPSFMag": [17.9],
        }
    )
    catalog = map_mean_object_table_to_catalog(
        tap,
        provider_id=config.PROVIDER_ID,
        centre_ra_deg=10.0,
        centre_dec_deg=20.0,
    )
    assert len(catalog) == 2
    assert set(catalog["filter_name"]) == {"g", "r"}
    assert catalog["object_name"][0] == "PS1 999"
    assert catalog["provider_note"][0] == config.DISCOVERY_CATALOG_PROVIDER_NOTE


def test_map_mean_object_sorts_by_separation():
    """Catalogue rows are ordered by ascending distance from the cone centre."""
    tap = Table(
        {
            "objID": [1, 2],
            "raMean": [10.0, 10.0 + 0.01],
            "decMean": [20.0, 20.0],
            "ng": [1, 1],
            "nr": [0, 0],
            "ni": [0, 0],
            "nz": [0, 0],
            "ny": [0, 0],
        }
    )
    catalog = map_mean_object_table_to_catalog(
        tap,
        provider_id=config.PROVIDER_ID,
        centre_ra_deg=10.0,
        centre_dec_deg=20.0,
    )
    assert len(catalog) == 2
    assert catalog["object_name"][0] == "PS1 1"
    assert catalog["object_name"][1] == "PS1 2"
    assert catalog["distance_arcsec"][0] < catalog["distance_arcsec"][1]


def test_adql_detection_joins_mean_object_for_epoch():
    """Lightcurve ADQL joins MeanObjectView for per-object epochMean."""
    adql = config.adql_detection_lightcurve(obj_id=999, filter_name="g")
    assert "m.epochMean" in adql
    assert "MeanObjectView" in adql
    assert "m.objID" in adql or "d.objID = m.objID" in adql


def test_votable_from_detections_keeps_missing_flux_error():
    """A missing flux error stays; a missing time or flux removes the row."""
    from astropy.time import Time

    epoch_mean_mjd = 58000.0
    expected_coosys = round(Time(epoch_mean_mjd, format="mjd").decimalyear, 1)
    det = Table(
        {
            "obsTime": [58000.1, 58001.2, float("nan")],
            "psfFlux": [1e-3, 1.1e-3, 1e-3],
            "psfFluxErr": [1e-4, float("nan"), 1e-4],
            "psfQfPerfect": [0.95, 0.99, 0.95],
            "epochMean": [epoch_mean_mjd, epoch_mean_mjd, epoch_mean_mjd],
        }
    )
    payload = votable_from_detections(
        det,
        obj_id=999,
        filter_name="r",
        ra_deg=10.0,
        dec_deg=20.0,
    )
    volc = load_issued(payload)
    assert len(volc) == 2
    assert "psf_flux" in volc.colnames
    assert volc.table.meta["name"] == "PS1 999 r"
    assert volc.table.meta["facility_name"] == config.FACILITY_NAME
    assert volc.coosys.epoch == pytest.approx(expected_coosys)
    assert volc.photdms["psf_flux_error"].photcal is volc.photdms["psf_flux"].photcal


def test_resolve_target_name_long_obj_id(provider):
    """Long numeric targets resolve to objID archive lookup."""
    match = provider.resolve_target_name("608067000000000000")
    assert match is not None
    assert match.archive_id == "608067000000000000"
    assert match.match_kind == "ps1_obj_id"


def test_resolve_target_name_rejects_ps_iau_name(provider):
    """PS IAU strings are not resolved (objname TAP lookup disabled)."""
    assert provider.resolve_target_name("PS J123.4+56.7") is None


def test_search_catalog_by_obj_id_object_name(monkeypatch, provider):
    """Direct object_name entry with long objID queries by objID only."""
    mean = Table(
        {
            "objID": [608067000000000000],
            "raMean": [10.0],
            "decMean": [20.0],
            "ng": [1],
            "nr": [0],
            "ni": [0],
            "nz": [0],
            "ny": [0],
        }
    )
    captured = {}

    def _fake_tap(_url, adql, **_kwargs):
        captured["adql"] = adql
        return mean

    monkeypatch.setattr(
        "lc_discovery.providers.panstarrs1_dr2.provider.run_tap_sync_query",
        _fake_tap,
    )
    catalog = provider.search_catalog(object_name="608067000000000000")
    assert "objID = 608067000000000000" in captured["adql"]
    assert "objname" not in captured["adql"]
    assert catalog["object_name"][0] == "PS1 608067000000000000"


def test_search_catalog_cone_sorted_by_separation(monkeypatch, provider):
    """Cone discovery returns rows sorted by distance_arcsec."""
    mean = Table(
        {
            "objID": [200, 100],
            "raMean": [10.0 + 0.02, 10.0],
            "decMean": [20.0, 20.0],
            "ng": [1, 1],
            "nr": [0, 0],
            "ni": [0, 0],
            "nz": [0, 0],
            "ny": [0, 0],
        }
    )

    monkeypatch.setattr(
        "lc_discovery.providers.panstarrs1_dr2.provider.run_tap_sync_query",
        lambda *_args, **_kwargs: mean,
    )

    catalog = provider.search_catalog(ra_deg=10.0, dec_deg=20.0, radius_arcsec=15.0)
    assert list(catalog["object_name"]) == ["PS1 100", "PS1 200"]
    assert catalog["distance_arcsec"][0] <= catalog["distance_arcsec"][1]


def test_search_catalog_cone_mocked(monkeypatch, provider):
    """Cone search maps mocked MeanObjectView rows."""
    mean = Table(
        {
            "objID": [100],
            "raMean": [10.0],
            "decMean": [20.0],
            "ng": [3],
            "nr": [0],
            "ni": [0],
            "nz": [0],
            "ny": [0],
            "gMeanPSFMag": [19.0],
        }
    )

    monkeypatch.setattr(
        "lc_discovery.providers.panstarrs1_dr2.provider.run_tap_sync_query",
        lambda *_args, **_kwargs: mean,
    )

    catalog = provider.search_catalog(ra_deg=10.0, dec_deg=20.0, radius_arcsec=15.0)
    assert len(catalog) == 1
    payload = decode_lc_key(catalog["lc_key"][0])["payload"]
    assert payload["obj_id"] == "100"
    assert payload["filter"] == "g"


def test_fetch_lightcurve_mocked(monkeypatch, provider):
    """Fetch runs detection TAP and builds VOLightCurve."""
    det = Table(
        {
            "obsTime": [58000.5],
            "psfFlux": [2e-3],
            "psfFluxErr": [2e-4],
            "psfQfPerfect": [1.0],
            "epochMean": [57123.45],
        }
    )
    key = map_mean_object_table_to_catalog(
        Table(
            {
                "objID": [100],
                "raMean": [10.0],
                "decMean": [20.0],
                "ng": [1],
                "nr": [0],
                "ni": [0],
                "nz": [0],
                "ny": [0],
            }
        ),
        provider_id=config.PROVIDER_ID,
    )["lc_key"][0]

    monkeypatch.setattr(
        "lc_discovery.providers.panstarrs1_dr2.provider.fetch_detection_table",
        lambda **_kwargs: det,
    )

    payload = provider.fetch_lightcurve(key)
    volc = load_issued(payload)
    assert len(volc) == 1
    assert volc.table.meta["name"] == "PS1 100 g"
    assert float(volc.photdms["psf_flux"].photcal.zp_flux.value) == pytest.approx(3631.0)


def test_detection_description_uses_psf_and_obj_id_only():
    """objID label matches format_ps1_object_name; PSF type comes from config."""
    text = config.detection_lightcurve_description(obj_id=165243463579570976, filter_name="z")
    assert "PSF photometry" in text
    assert "PS1 165243463579570976" in text
    assert "objID 165243463579570976" in text
    assert "filter=z" in text
    assert "(objID=" not in text


def test_issued_title_is_object_label_and_filter():
    """The table name is the object label and the filter."""
    det = Table(
        {
            "obsTime": [58000.5],
            "psfFlux": [2e-3],
            "psfFluxErr": [2e-4],
            "psfQfPerfect": [1.0],
            "epochMean": [57123.45],
        }
    )
    payload = votable_from_detections(
        det,
        obj_id=165243463579570976,
        filter_name="i",
        ra_deg=10.0,
        dec_deg=20.0,
    )
    volc = load_issued(payload)
    assert volc.table.meta["name"] == "PS1 165243463579570976 i"
    assert "objID 165243463579570976" in volc.table.meta["description"]
