"""Tests for the UPJŠ time-series TAP provider."""

import io

import numpy as np
from astropy.table import Table

from lc_discovery.lc_key import decode_lc_key
from lc_discovery.registry import get_provider, list_missions
from lc_discovery.providers.upjs_ts import config
from lc_discovery.providers.upjs_ts.provider import UpjsTsProvider
from lc_discovery.providers.upjs_ts.resolve_target import resolve_upjs_target_name
from lc_discovery.providers.upjs_ts.ssa_catalog import map_ssa_table_to_catalog


def _sample_upjs_ssa_table() -> Table:
    """Builds a TAP SSA table matching the UPJŠ service shape."""
    return Table(
        {
            "object_id": ["3716", "3716"],
            "accref": [
                "https://skvo.science.upjs.sk/upjs_ts/q/sdl/dlget?ID=example-v",
                "https://skvo.science.upjs.sk/upjs_ts/q/sdl/dlget?ID=example-r",
            ],
            "ssa_bandpass": ["V", "R"],
            "ssa_targname": [
                "Gaia DR3 1866728237239754112",
                "Gaia DR3 1866728237239754112",
            ],
            "ssa_targclass": ["RR*", "RR*"],
            "ssa_location": [np.array([289.432, 36.102]), np.array([289.432, 36.102])],
            "ssa_length": [800, 790],
            "ssa_collection": ["UPJS", "UPJS"],
            "t_min": [54000.0, 54000.0],
            "t_max": [60000.0, 60000.0],
            "mean_mag": [13.94, 14.1],
        }
    )


def test_map_upjs_ssa_table_uses_ssa_targname_for_object_name():
    """Catalogue rows show Gaia DR3 SSA labels rather than internal object ids."""
    catalog = map_ssa_table_to_catalog(
        _sample_upjs_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 2
    assert catalog["object_name"][0] == "Gaia DR3 1866728237239754112"
    assert catalog["object_class"][0] == "RR*"


def test_upjs_adql_gaia_targname_query():
    """Gaia DR3 ADQL selects on indexed ssa_targname."""
    adql = config.adql_catalog_by_ssa_targname("Gaia DR3 1866728237239754112")
    assert "FROM upjs_ts.ts_ssa" in adql
    assert "ssa_targname = 'Gaia DR3 1866728237239754112'" in adql


def test_upjs_adql_objects_simbad_case_insensitive():
    """Objects-table ADQL uses UPPER for case-insensitive Simbad matching."""
    adql = config.adql_objects_by_simbad_name("bd+76   642")
    assert "FROM upjs_ts.objects" in adql
    assert "UPPER(simbad_name) = UPPER(" in adql


def test_resolve_upjs_target_name_skips_gaia_labels():
    """Inner resolver leaves Gaia DR3 strings to direct ssa_targname search."""
    assert resolve_upjs_target_name("Gaia DR3 1866728237239754112") is None
    assert resolve_upjs_target_name("1866728237239754112") is None


def test_resolve_upjs_target_name_uses_objects_table(monkeypatch):
    """Simbad and VSX names resolve to object_id via upjs_ts.objects."""
    objects_table = Table(
        {
            "object_id": ["1"],
            "gaia_name": ["1656754192432536832"],
            "simbad_name": ["BD+76   642"],
            "vsx_name": [""],
        }
    )

    def fake_tap(url, adql, dialect=None):
        if "upjs_ts.objects" in adql and "simbad_name" in adql:
            return objects_table
        return Table(names=["object_id", "gaia_name", "simbad_name", "vsx_name"])

    monkeypatch.setattr(
        "lc_discovery.providers.upjs_ts.cross_ident.run_tap_sync_query",
        fake_tap,
    )

    match = resolve_upjs_target_name("bd+76   642")
    assert match is not None
    assert match.archive_id == "1"
    assert match.match_kind == "upjs_simbad_name"


def test_upjs_registry_entry():
    """UPJŠ TS provider is registered for Discovery."""
    mission_ids = {item.mission_id for item in list_missions()}
    assert "upjs_ts" in mission_ids
    provider = get_provider("upjs_ts")
    assert provider.display_name == "UPJŠ TS"


def test_upjs_search_catalog_by_gaia_name(monkeypatch):
    """Direct Gaia DR3 labels query ts_ssa by ssa_targname."""
    provider = UpjsTsProvider()
    captured: dict[str, str] = {}

    def fake_tap(url, adql, dialect=None):
        captured["adql"] = adql
        return _sample_upjs_ssa_table()

    monkeypatch.setattr(
        "lc_discovery.providers.upjs_ts.provider.run_tap_sync_query",
        fake_tap,
    )

    catalog = provider.search_catalog(object_name="Gaia DR3 1866728237239754112")
    assert "ssa_targname = 'Gaia DR3 1866728237239754112'" in captured["adql"]
    assert len(catalog) == 2

    lc_key = catalog["lc_key"][0]
    payload = decode_lc_key(lc_key)["payload"]
    assert payload["object_id"] == "3716"


def _upjs_votable(*, zp_mag: str | None, filter_id: str = "Generic/Bessell.V") -> bytes:
    """Minimal UPJŠ-like VOTable with an optional published magnitude zero point."""
    zp = ""
    if zp_mag is not None:
        zp = (
            '<PARAM name="zeroPointReferenceMagnitude" datatype="double" '
            'utype="photDM:PhotCal.zeroPoint.referenceMagnitude.value" '
            f'value="{zp_mag}" unit="mag"/>'
        )
    xml = f"""<?xml version="1.0"?>
<VOTABLE version="1.4" xmlns="http://www.ivoa.net/xml/VOTable/v1.3">
<RESOURCE>
<TABLE name="star">
<DESCRIPTION>UPJS series</DESCRIPTION>
<GROUP name="photcal">
<PARAM name="filterIdentifier" datatype="char" arraysize="*" utype="photDM:PhotometryFilter.identifier" value="{filter_id}"/>
<PARAM name="zeroPointFlux" datatype="double" utype="photDM:PhotCal.zeroPoint.flux.value" value="3631" unit="Jy"/>
{zp}
<FIELDref ref="mag"/>
</GROUP>
<FIELD name="jd" ID="jd" datatype="double" ucd="time.epoch"/>
<FIELD name="mag" ID="mag" datatype="double" ucd="phot.mag" unit="mag"/>
<FIELD name="mag_err" ID="mag_err" datatype="double" ucd="stat.error;phot.mag" unit="mag"/>
<DATA><TABLEDATA><TR><TD>2459000</TD><TD>12.2</TD><TD>0.01</TD></TR></TABLEDATA></DATA>
</TABLE>
</RESOURCE>
</VOTABLE>"""
    return xml.encode()


def _parse(payload: bytes):
    """Parses enriched bytes the way Discovery does after the plugin returns."""
    from issued import load_issued

    return load_issued(payload)


def test_upjs_sets_magnitude_zero_point_for_bessell_v():
    """UPJŠ Bessell V with no magnitude zero point receives 0 mag; flux zero point stays."""
    from lc_discovery.providers.upjs_ts.fetch_metadata import enrich_votable

    volc = _parse(enrich_votable(_upjs_votable(zp_mag=None)))
    photcal = volc.photdms["mag"].photcal
    assert float(photcal.zp_mag.value) == 0.0
    assert float(photcal.zp_flux.value) == 3631.0
    assert volc.table.meta["name"] == "star"
    assert volc.photdms["mag_err"].photcal is photcal


def test_upjs_sets_magnitude_zero_point_for_sdss_g():
    """UPJŠ SDSS g with no magnitude zero point receives 0 mag."""
    from lc_discovery.providers.upjs_ts.fetch_metadata import enrich_votable

    volc = _parse(enrich_votable(_upjs_votable(zp_mag=None, filter_id="SLOAN/SDSS.g")))
    assert float(volc.photdms["mag"].photcal.zp_mag.value) == 0.0


