"""Tests for the ZTF DR24 lightcurve provider."""

from __future__ import annotations

import pandas as pd
import pytest

from lc_discovery.discovery_fetch_context import DiscoveryFetchContext
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.providers.ztf import config
from lc_discovery.providers.ztf.fetch_metadata import resolve_lookup_name_for_fetch
from lc_discovery.providers.ztf.oid import parse_ztf_oid
from lc_discovery.providers.ztf.provider import ZtfDr24Provider
from lc_discovery.discovery_fetch_context import SEARCH_MODE_SIMBAD_CONE


@pytest.fixture
def provider():
    """Returns a ZTF DR24 provider instance."""
    return ZtfDr24Provider()


def test_parse_ztf_oid_digits_only():
    """Digit-only strings parse as OIDs; names do not."""
    assert parse_ztf_oid("85900701048") == 85900701048
    assert parse_ztf_oid("AA And") is None


def test_effective_lookup_association_arcsec():
    """Association threshold is min(radius, provider cap)."""
    assert config.effective_lookup_association_arcsec(2.0) == pytest.approx(2.0)
    assert config.effective_lookup_association_arcsec(3600.0) == pytest.approx(5.0)


def test_resolve_lookup_name_within_tau():
    """Lookup metadata applies for Simbad cone rows within tau_eff."""
    ctx = DiscoveryFetchContext(
        search_mode=SEARCH_MODE_SIMBAD_CONE,
        user_target="AA And",
        simbad_main_id="AA And",
        radius_arcsec=30.0,
        distance_arcsec=3.0,
    )
    assert resolve_lookup_name_for_fetch(ctx) == "AA And"


def test_resolve_lookup_name_outside_tau():
    """Distant cone rows do not inherit the lookup label."""
    ctx = DiscoveryFetchContext(
        search_mode=SEARCH_MODE_SIMBAD_CONE,
        user_target="AA And",
        simbad_main_id="AA And",
        radius_arcsec=3600.0,
        distance_arcsec=120.0,
    )
    assert resolve_lookup_name_for_fetch(ctx) is None


def test_search_catalog_maps_oid_row(monkeypatch, provider):
    """OID discovery returns one standardised catalogue row."""
    frame = pd.DataFrame(
        [
            {
                "oid": 123456789012,
                "ra": 316.01,
                "dec": 46.52,
                "filtercode": "zr",
                "nobsrel": 42,
                "meanmag": 14.5,
            }
        ]
    )
    monkeypatch.setattr(
        "lc_discovery.providers.ztf.provider.query_objects_by_oid",
        lambda oid: frame,
    )
    catalog = provider.search_catalog(archive_id="123456789012")
    assert len(catalog) == 1
    assert catalog["object_name"][0] == "ZTF OID 123456789012"
    assert catalog["filter_name"][0] == "ZTF r"
    assert catalog["n_points"][0] == 42


def test_search_catalog_excludes_zero_nobsrel(monkeypatch, provider):
    """Discovery omits OIDs with nobsrel zero before building the catalogue."""
    frame = pd.DataFrame(
        [
            {
                "oid": 1001,
                "ra": 316.01,
                "dec": 46.52,
                "filtercode": "zg",
                "nobsrel": 0,
                "meanmag": 12.0,
            },
            {
                "oid": 1002,
                "ra": 316.01,
                "dec": 46.52,
                "filtercode": "zr",
                "nobsrel": 5,
                "meanmag": 13.0,
            },
        ]
    )
    monkeypatch.setattr(
        "lc_discovery.providers.ztf.provider.query_objects_cone",
        lambda **kwargs: frame,
    )
    catalog = provider.search_catalog(ra_deg=316.01, dec_deg=46.52, radius_arcsec=60.0)
    assert len(catalog) == 1
    assert catalog["n_points"][0] == 5


def test_search_catalog_cone_truncates_and_sorts(monkeypatch, provider):
    """Cone discovery caps OID rows and sorts by distance."""
    rows = []
    for idx, dist_factor in enumerate((0.5, 0.1, 0.2)):
        rows.append(
            {
                "oid": 1000 + idx,
                "ra": 316.01 + dist_factor / 3600.0,
                "dec": 46.52,
                "filtercode": "zg",
                "nobsrel": 10,
                "meanmag": 12.0,
            }
        )
    frame = pd.DataFrame(rows)
    monkeypatch.setattr(
        "lc_discovery.providers.ztf.provider.query_objects_cone",
        lambda **kwargs: frame,
    )
    catalog = provider.search_catalog(ra_deg=316.01, dec_deg=46.52, radius_arcsec=60.0)
    assert len(catalog) == 3
    distances = list(catalog["distance_arcsec"])
    assert distances == sorted(distances)


def test_fetch_lightcurve_builds_mag_native_volc(monkeypatch, provider):
    """Fetch path builds a magnitude-native VOLightCurve with OID labels."""
    oid = 123456789012
    lc_key = encode_lc_key(config.PROVIDER_ID, {"oid": str(oid)})
    meta = pd.DataFrame(
        [
            {
                "oid": oid,
                "ra": 316.01,
                "dec": 46.52,
                "filtercode": "zr",
                "nobsrel": 3,
                "meanmag": 14.0,
            }
        ]
    )
    epochs = pd.DataFrame(
        {
            "oid": [oid, oid],
            "hjd": [2458000.1, 2458001.2],
            "mag": [14.1, 14.2],
            "magerr": [0.05, float("nan")],
            "catflags": [0, 0],
            "chi": [1.1, 1.2],
            "sharp": [0.01, 0.02],
            "field": [596, 596],
            "ccdid": [1, 1],
            "qid": [2, 2],
            "limitmag": [20.5, 20.4],
        }
    )
    monkeypatch.setattr(
        "lc_discovery.providers.ztf.provider.query_objects_by_oid",
        lambda oid_arg: meta,
    )
    monkeypatch.setattr(
        "lc_discovery.providers.ztf.provider.fetch_photometry_by_oid",
        lambda oid_arg, fetch_quality=config.FETCH_QUALITY_RAW: epochs,
    )
    import io

    from issued import load_issued

    payload = provider.fetch_lightcurve(lc_key)
    volc = load_issued(payload)
    assert len(volc) == 2
    assert "hjd" in volc.colnames
    assert "mag_err" in volc.colnames
    assert "catflag" in volc.colnames
    assert list(volc.table["oid"]) == [oid, oid]
    assert volc.photdms["mag_err"].photcal is volc.photdms["mag"].photcal
