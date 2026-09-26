"""Tests for the Gaia DR3 VEB TAP provider."""

from astropy.table import Table

from lc_discovery.providers.gaia_dr3_veb import config
from lc_discovery.providers.gaia_dr3_veb.provider import GaiaDr3VebProvider
from lc_discovery.providers.gaia_dr3_veb.ssa_catalog import map_ssa_table_to_catalog, parse_ssa_location
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.tap.dialect import TapQueryDialect
from catalogue_numbers import AA_AND


def _sample_ssa_table() -> Table:
    """Builds a TAP SSA table matching the UPJS VEB service shape."""
    return Table(
        {
            "accref": [
                "https://skvo.science.upjs.sk/gaiadr3_rp.vot",
                "https://skvo.science.upjs.sk/gaiadr3_g.vot",
                "https://skvo.science.upjs.sk/gaiadr3_bp.vot",
            ],
            "ssa_bandpass": ["Gaia RP", "Gaia G", "Gaia BP"],
            "ssa_dstitle": [
                "Gaia DR3 RP lightcurve",
                "Gaia DR3 G lightcurve",
                "Gaia DR3 BP lightcurve",
            ],
            "ssa_targname": [
                f"Gaia DR3 {AA_AND.source_id}",
            ]
            * 3,
            "ssa_targclass": ["EB*"] * 3,
            "ssa_location": [
                f"({AA_AND.ra_deg}, {AA_AND.dec_deg})",
            ]
            * 3,
            "ssa_length": [62, 64, 62],
            "ssa_creator": ["GAIA Collaboration"] * 3,
            "ssa_collection": ["Gaia DR3"] * 3,
            "t_min": [56889.6511, 56889.650676, 56889.651],
            "t_max": [57887.5337, 57887.709377, 57887.5336],
        }
    )


def test_parse_ssa_location():
    """ssa_location parenthesis and bracket syntax parse to RA/Dec degrees."""
    ra, dec = parse_ssa_location("(346.3451680066484, 47.67629184752743)")
    assert ra == 346.3451680066484
    assert dec == 47.67629184752743

    ra2, dec2 = parse_ssa_location("[346.3451680066484 47.67629184752743]")
    assert ra2 == 346.3451680066484
    assert dec2 == 47.67629184752743


def test_map_ssa_table_to_catalog_builds_lc_keys(monkeypatch):
    """SSA rows map to three standard catalogue products with accref lc_key payloads."""
    catalog = map_ssa_table_to_catalog(
        _sample_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    assert len(catalog) == 3
    assert set(catalog["filter_name"]) == {"Gaia RP", "Gaia G", "Gaia BP"}

    lc_key = catalog["lc_key"][0]
    payload = decode_lc_key(lc_key)["payload"]
    assert payload["accref"].startswith("https://skvo.science.upjs.sk/")
    assert payload["filter_name"] in {"Gaia RP", "Gaia G", "Gaia BP"}


def test_veb_adql_source_id_query():
    """Direct source_id ADQL 2.1 uses standard SELECT/WHERE predicates."""
    adql = config.adql_catalog_by_source_id(
        AA_AND.source_id,
        time_start_mjd=56889.0,
        time_end_mjd=60000.0,
    )
    assert "FROM gaiadr3_eb.ts_ssa" in adql
    assert f"source_id = {AA_AND.source_id}" in adql
    assert "t_min > 56889.0" in adql
    assert "t_max < 60000.0" in adql
    assert "accref" in adql
    assert adql.startswith("SELECT ")


def test_veb_adql_cone_query():
    """Cone ADQL 2.1 puts the sky point inside the search circle."""
    adql = config.adql_catalog_cone(
        ra_deg=AA_AND.ra_deg,
        dec_deg=AA_AND.dec_deg,
        radius_arcsec=10.0,
    )
    assert "1 = CONTAINS(ssa_location, CIRCLE(" in adql
    assert "'ICRS'" not in adql
    assert f"CIRCLE({AA_AND.ra_deg}, {AA_AND.dec_deg}," in adql


def test_veb_tap_dialect_is_adql_21():
    """VEB provider declares ADQL 2.1 for the UPJS TAP service."""
    assert config.TAP_QUERY_DIALECT == TapQueryDialect.ADQL_2_1


def test_veb_search_catalog_by_source_id(monkeypatch):
    """search_catalog casts Gaia DR3 strings to source_id and maps TAP rows."""
    provider = GaiaDr3VebProvider()
    captured: dict[str, str] = {}

    def _fake_tap(_url, adql, *, dialect):
        captured["dialect"] = dialect
        return _sample_ssa_table()

    monkeypatch.setattr(
        "lc_discovery.providers.gaia_dr3_veb.provider.run_tap_sync_query",
        _fake_tap,
    )

    table = provider.search_catalog(object_name=str(AA_AND.source_id))
    assert len(table) == 3
    assert captured["dialect"] == TapQueryDialect.ADQL_2_1

    prefixed = provider.search_catalog(object_name=f"Gaia DR3 {AA_AND.source_id}")
    assert len(prefixed) == 3


def test_veb_fetch_lightcurve_from_accref(monkeypatch):
    """fetch_lightcurve downloads accref bytes through the provider-specific resolver."""
    provider = GaiaDr3VebProvider()
    catalog = map_ssa_table_to_catalog(
        _sample_ssa_table(),
        provider_id=config.PROVIDER_ID,
    )
    lc_key = catalog["lc_key"][0]

    def _fake_fetch(accref, **kwargs):
        assert accref.startswith("https://")
        return b"<VOTABLE/>"

    monkeypatch.setattr(
        "lc_discovery.providers.gaia_dr3_veb.provider.fetch_votable_bytes",
        _fake_fetch,
    )
    monkeypatch.setattr(
        "lc_discovery.providers.gaia_dr3_veb.provider.enrich_votable",
        lambda payload: payload,
    )
    payload = provider.fetch_lightcurve(lc_key)
    assert payload == b"<VOTABLE/>"
