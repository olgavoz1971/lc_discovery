"""Tests for the UPJS personal time-series TAP provider."""

import numpy as np
from astropy.table import Table

from lc_discovery.lc_key import decode_lc_key
from lc_discovery.providers.personal_ts import config
from lc_discovery.providers.personal_ts.object_id import (
    normalize_personal_object_id,
    pick_personal_archive_id_from_simbad,
)
from lc_discovery.providers.personal_ts.provider import PersonalTsProvider
from lc_discovery.providers.personal_ts.ssa_catalog import map_ssa_table_to_catalog
from lc_discovery.registry import get_provider, list_missions
from types import SimpleNamespace


def _sample_personal_ssa_table() -> Table:
    """Builds a TAP SSA table matching the UPJS personal service shape."""
    return Table(
        {
            "object_id": ["AY_Lac", "AY_Lac"],
            "accref": [
                "https://skvo.science.upjs.sk/personal/q/sdl/dlget?ID=example-r",
                "https://skvo.science.upjs.sk/personal/q/sdl/dlget?ID=example-b",
            ],
            "ssa_bandpass": ["R", "B"],
            "ssa_targname": ["AY_Lac", "AY_Lac"],
            "ssa_targclass": ["CV*", "CV*"],
            "ssa_location": [np.array([289.432, 36.102]), np.array([289.432, 36.102])],
            "ssa_length": [1200, 1180],
            "ssa_collection": ["PERSONAL", "PERSONAL"],
            "t_min": [54000.0, 54000.0],
            "t_max": [60000.0, 60000.0],
            "mean_mag": [14.2, 14.8],
        }
    )


def test_normalize_personal_object_id():
    """Simbad spacing collapses to underscore archive ids."""
    assert normalize_personal_object_id("AY Lac") == "AY_Lac"
    assert normalize_personal_object_id("AY_Lac") == "AY_Lac"


def test_pick_personal_archive_id_from_simbad():
    """Simbad main id maps to a personal object_id."""
    result = SimpleNamespace(
        query_name="AY Lac",
        main_id="AY Lac",
        ra_deg=289.432,
        dec_deg=36.102,
        identifiers=["AY Lac"],
    )
    match = pick_personal_archive_id_from_simbad(result)
    assert match is not None
    assert match.archive_id == "AY_Lac"
    assert match.match_kind == "personal_object_id"


def test_map_personal_ssa_table_includes_object_class_and_mean_mag():
    """Personal TAP rows map to catalogue schema with Simbad class and magnitude."""
    catalog = map_ssa_table_to_catalog(
        _sample_personal_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 2
    assert set(catalog["filter_name"]) == {"R", "B"}
    assert set(catalog["object_class"]) == {"CV*"}
    assert float(catalog["mag"][0]) == 14.2

    lc_key = catalog["lc_key"][0]
    payload = decode_lc_key(lc_key)["payload"]
    assert payload["object_id"] == "AY_Lac"
    assert payload["accref"].startswith("https://skvo.science.upjs.sk/")


def test_personal_adql_object_id_query():
    """Direct object_id ADQL selects personal SSA columns including ssa_targclass."""
    adql = config.adql_catalog_by_object_id("AY_Lac")
    assert "FROM personal.ts_ssa" in adql
    assert "object_id = 'AY_Lac'" in adql
    assert "ssa_targclass" in adql


def test_personal_registry_entry():
    """Personal TS provider is registered for Discovery."""
    mission_ids = {item.mission_id for item in list_missions()}
    assert "personal_ts" in mission_ids
    provider = get_provider("personal_ts")
    assert provider.display_name == "Personal collections"
    assert provider.is_mock is False


def test_personal_search_catalog_by_object_id(monkeypatch):
    """Provider delegates object lookup to TAP and maps the SSA table."""
    provider = PersonalTsProvider()
    captured: dict[str, str] = {}

    def fake_tap(url, adql, dialect=None):
        captured["adql"] = adql
        return _sample_personal_ssa_table()

    monkeypatch.setattr(
        "lc_discovery.providers.personal_ts.provider.run_tap_sync_query",
        fake_tap,
    )

    catalog = provider.search_catalog(object_name="AY Lac")
    assert "object_id = 'AY_Lac'" in captured["adql"]
    assert len(catalog) == 2
    assert catalog["object_class"][0] == "CV*"


def test_personal_sets_magnitude_zero_point_for_arp_filter():
    """Personal collections set zp_mag 0 for Palomar/Arp1961.103aO_atm when the file has none."""
    import io

    from lc_discovery.providers.personal_ts.fetch_metadata import enrich_votable
    from issued import load_issued

    xml = """<?xml version="1.0"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
<RESOURCE>
<TABLE name="star">
<DESCRIPTION>Personal series</DESCRIPTION>
<GROUP name="photcal">
<PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="Palomar/Arp1961.103aO_atm"/>
<PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="2500" unit="Jy"/>
<FIELDref ref="mag"/>
</GROUP>
<FIELD name="jd" ID="jd" datatype="double" ucd="time.epoch"/>
<FIELD name="mag" ID="mag" datatype="double" ucd="phot.mag" unit="mag"/>
<FIELD name="mag_err" ID="mag_err" datatype="double" ucd="stat.error;phot.mag" unit="mag"/>
<DATA><TABLEDATA><TR><TD>2459000</TD><TD>12.2</TD><TD>0.01</TD></TR></TABLEDATA></DATA>
</TABLE>
</RESOURCE>
</VOTABLE>"""
    volc = load_issued(enrich_votable(xml.encode()))
    photcal = volc.photdms["mag"].photcal
    assert float(photcal.zp_mag.value) == 0.0
    assert float(photcal.zp_flux.value) == 2500.0
    assert volc.table.meta["name"] == "star"
    assert volc.photdms["mag_err"].photcal is photcal


