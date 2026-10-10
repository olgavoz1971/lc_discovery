"""Tests for the TESS archive lightcurve provider."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from astropy.table import Table

from lc_discovery.lc_key import decode_lc_key, encode_lc_key
from lc_discovery.registry import get_provider, list_missions
from lc_discovery.providers.tess import config
from lc_discovery.providers.tess.columns import (
    is_spoc_family_flux_unit,
    background_role_for_name,
)
from lc_discovery.providers.tess.fetch_metadata import votable_from_lightcurve
from lc_discovery.providers.tess.provider import TessProvider
from lc_discovery.providers.tess.tic import parse_tic, pick_tic_from_simbad
from lc_discovery.simbad import SimbadResolveResult
from tests.issued import load_issued


@pytest.fixture
def provider():
    """Returns a TESS archive provider instance."""
    return TessProvider()


class _Col:
    """Numeric column with an optional unit, as Lightkurve exposes them."""

    def __init__(self, values, unit=None):
        self.value = np.asarray(values)
        self.unit = unit


class _FakeLC:
    """Minimal Lightkurve-like object for fetch tests."""

    def __init__(
        self, colnames, data, *, meta=None, author="SPOC", sector=16, units=None
    ):
        self.colnames = list(colnames)
        self._data = data
        self._units = units or {}
        self.meta = meta or {}
        self.AUTHOR = author
        self.SECTOR = sector
        self.LABEL = "TIC 1"
        self.ra = 10.0
        self.dec = -5.0
        self.time = SimpleNamespace(value=np.asarray(data["time"], dtype=float))

    def __getitem__(self, name):
        return _Col(self._data[name], unit=self._units.get(name))


def test_tess_cone_caps(provider):
    """TESS cone search allows 10 arcmin and 500 catalogue rows."""
    assert provider.max_discovery_search_radius_deg() == pytest.approx(10.0 / 60.0)
    assert provider.max_discovery_catalog_rows() == 500


def test_format_sector_and_exp_cells_are_short():
    """Sector and Exp cells have no extra words or parentheses."""
    assert config.format_sector_cell(16) == "16"
    assert config.format_exp_cell(120.0) == "120s"


def test_tess_registry_entry():
    """TESS archive is registered for Discovery independently of Dash pages."""
    mission_ids = {item.mission_id for item in list_missions()}
    assert "tess" in mission_ids
    registered = get_provider("tess")
    assert registered.display_name == "TESS archive"
    assert registered.is_mock is False


def test_parse_tic_like_gaia_source_id():
    """TIC strings and bare digits parse; names do not."""
    assert parse_tic("TIC 159717514") == 159717514
    assert parse_tic("TIC:159717514") == 159717514
    assert parse_tic("35119266") == 35119266
    assert parse_tic("AA And") is None


def test_pick_tic_from_simbad():
    """Simbad identifiers yield a TIC match."""
    result = SimbadResolveResult(
        query_name="AA And",
        main_id="AA And",
        identifiers=("AA And", "TIC 123456789", "Gaia DR3 1"),
        ra_deg=1.0,
        dec_deg=2.0,
    )
    match = pick_tic_from_simbad(result)
    assert match is not None
    assert match.archive_id == "123456789"
    assert match.match_kind == "tic"


def test_resolve_target_name(provider):
    """Provider resolves TIC before Simbad."""
    match = provider.resolve_target_name("TIC 159717514")
    assert match.matched_label == "TIC 159717514"
    assert match.archive_id == "159717514"


def test_search_catalog_maps_all_products(monkeypatch, provider):
    """TIC discovery keeps every sector/author/exptime row."""
    search_table = Table(
        {
            "target_name": ["159717514", "159717514"],
            "author": ["SPOC", "QLP"],
            "mission": ["TESS Sector 16", "TESS Sector 16"],
            "exptime": [120.0, 1800.0],
            "s_ra": [316.0, 316.0],
            "s_dec": [46.5, 46.5],
            "t_min": [58400.0, 58400.0],
            "t_max": [58425.0, 58425.0],
            "tmag": [10.1, 10.1],
            "sequence_number": [16, 16],
        }
    )
    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.search_by_tic",
        lambda tic: search_table,
    )
    catalog = provider.search_catalog(archive_id="159717514")
    assert len(catalog) == 2
    assert catalog["object_name"][0] == "TIC 159717514"
    assert set(catalog["filter_name"]) == {"TESS"}
    assert set(catalog["author"]) == {"SPOC", "QLP"}
    assert set(catalog["sector"]) == {"16"}
    assert set(catalog["exp"]) == {"120s", "1800s"}
    payload = decode_lc_key(str(catalog["lc_key"][0]))["payload"]
    assert payload["tic"] == 159717514
    assert payload["sector"] == 16
    assert "author" in payload
    assert "exptime" in payload


def test_search_keeps_unknown_author(monkeypatch, provider):
    """Unregistered pipelines still appear in discovery."""
    search_table = Table(
        {
            "target_name": ["1"],
            "author": ["NOT-A-PIPELINE"],
            "mission": ["TESS Sector 1"],
            "exptime": [120.0],
            "s_ra": [1.0],
            "s_dec": [2.0],
            "sequence_number": [1],
        }
    )
    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.search_by_tic",
        lambda tic: search_table,
    )
    catalog = provider.search_catalog(archive_id="1000001")
    assert len(catalog) == 1
    assert catalog["author"][0] == "NOT-A-PIPELINE"


def test_background_role_by_name_only():
    """Only background is recognised by name; flux roles are never guessed."""
    assert background_role_for_name("sap_bkg") == "background"
    assert background_role_for_name("sap_bkg_err") == "background_error"
    assert background_role_for_name("sap_flux") is None
    assert background_role_for_name("psf_flux") is None


def test_spoc_family_flux_units():
    """Electron s-1 and counts per second count as the SPOC unit family."""
    assert is_spoc_family_flux_unit("electron s-1")
    assert is_spoc_family_flux_unit("e-/s")
    assert is_spoc_family_flux_unit("counts/s")
    assert not is_spoc_family_flux_unit("mag")
    assert not is_spoc_family_flux_unit(None)


def test_spoc_issued_keeps_sap_and_pdcsap():
    """SPOC VOTable keeps both flux series, background, and 20.44 on target flux."""
    n = 3
    time_btjd = np.array([1400.0, 1400.1, 1400.2])
    lc = _FakeLC(
        [
            "time",
            "pdcsap_flux",
            "pdcsap_flux_err",
            "sap_flux",
            "sap_flux_err",
            "sap_bkg",
            "sap_bkg_err",
        ],
        units={
            "pdcsap_flux": "electron s-1",
            "pdcsap_flux_err": "electron s-1",
            "sap_flux": "electron s-1",
            "sap_flux_err": "electron s-1",
            "sap_bkg": "electron s-1",
            "sap_bkg_err": "electron s-1",
        },
        data={
            "time": time_btjd,
            "pdcsap_flux": np.array([100.0, 101.0, 102.0]),
            "pdcsap_flux_err": np.array([1.0, 1.0, 1.0]),
            "sap_flux": np.array([110.0, 111.0, 112.0]),
            "sap_flux_err": np.array([2.0, 2.0, 2.0]),
            "sap_bkg": np.array([5.0, 5.1, 5.2]),
            "sap_bkg_err": np.array([0.1, 0.1, 0.1]),
        },
    )
    payload = votable_from_lightcurve(
        lc, tic=1, sector=16, author="SPOC", exptime=120.0
    )
    issued = load_issued(payload)
    assert "pdcsap_flux" in issued.colnames
    assert "sap_flux" in issued.colnames
    assert "sap_bkg" in issued.colnames
    assert issued.photdms["pdcsap_flux"].photcal.zp_mag.value == pytest.approx(20.44)
    assert issued.photdms["sap_flux"].photcal.zp_mag.value == pytest.approx(20.44)
    assert issued.photdms["pdcsap_flux"].photcal.zp_flux.value == pytest.approx(1.0)
    assert issued.photdms["sap_bkg"].photcal.zp_mag is None
    assert issued["time"][0] == pytest.approx(config.btjd_to_mjd(1400.0))
    xml = payload.decode("utf-8")
    assert 'ID="ts"' in xml
    assert 'ref="ts"' in xml
    assert "time.epoch" in xml
    assert 'ucd="instr.background"' in xml
    assert "phot.flux;instr.background" not in xml


def test_qlp_uses_tessmag_not_2044():
    """QLP photcal uses TESSMAG, not the SPOC instrument zero point."""
    lc = _FakeLC(
        ["time", "sap_flux", "sap_flux_err", "kspsap_flux", "kspsap_flux_err"],
        {
            "time": np.array([1400.0, 1400.1]),
            "sap_flux": np.array([1.0, 1.01]),
            "sap_flux_err": np.array([0.01, 0.01]),
            "kspsap_flux": np.array([0.99, 1.0]),
            "kspsap_flux_err": np.array([0.01, 0.01]),
        },
        meta={"TESSMAG": 12.5},
        author="QLP",
        sector=10,
    )
    issued = load_issued(
        votable_from_lightcurve(lc, tic=2, sector=10, author="QLP", exptime=1800.0)
    )
    assert "sap_flux" in issued.colnames
    assert "kspsap_flux" in issued.colnames
    assert issued.photdms["sap_flux"].photcal.zp_mag.value == pytest.approx(12.5)
    assert issued.photdms["sap_flux"].photcal.zp_mag.value != pytest.approx(20.44)


def test_fetch_lightcurve_uses_download(monkeypatch, provider):
    """fetch_lightcurve issues VOTable bytes from a mocked download."""
    lc = _FakeLC(
        ["time", "pdcsap_flux", "pdcsap_flux_err", "sap_flux", "sap_flux_err"],
        {
            "time": np.array([1400.0]),
            "pdcsap_flux": np.array([50.0]),
            "pdcsap_flux_err": np.array([0.5]),
            "sap_flux": np.array([55.0]),
            "sap_flux_err": np.array([0.6]),
        },
    )
    monkeypatch.setattr(
        "lc_discovery.providers.tess.provider.download_archive_product",
        lambda **kwargs: (
            lc,
            {"obs_collection": "TESS", "obs_id": "o1", "product_filename": "f.fits"},
        ),
    )
    lc_key = encode_lc_key(
        "tess",
        {"tic": 1, "sector": 16, "author": "SPOC", "exptime": 120.0},
    )
    payload = provider.fetch_lightcurve(lc_key)
    assert isinstance(payload, bytes)
    issued = load_issued(payload)
    assert len(issued) == 1
    assert "pdcsap_flux" in issued.colnames
    assert "sap_flux" in issued.colnames
    assert b'name="mast_obs_id"' in payload
    assert b'value="f.fits"' in payload


def test_unknown_author_roles_from_flux_origin():
    """FLUX_ORIGIN gives the flux role; flux_err with data gives the error role."""
    lc = _FakeLC(
        ["time", "flux", "flux_err", "psf_flux", "sap_bkg", "quality", "flag"],
        {
            "time": np.array([1400.0, 1400.1]),
            "flux": np.array([10.0, 11.0]),
            "flux_err": np.array([0.2, 0.2]),
            "psf_flux": np.array([10.0, 11.0]),
            "sap_bkg": np.array([1.0, 1.1]),
            "quality": np.array([0, 8]),
            "flag": np.array(["G", "B"]),
        },
        meta={"FLUX_ORIGIN": "psf_flux"},
        author="NOT-A-PIPELINE",
        units={"psf_flux": "electron s-1", "sap_bkg": "electron s-1"},
    )
    payload = votable_from_lightcurve(
        lc, tic=3, sector=1, author="NOT-A-PIPELINE", exptime=120.0
    )
    issued = load_issued(payload)
    for name in ("flux", "flux_err", "psf_flux", "sap_bkg", "quality"):
        assert name in issued.colnames
    assert issued.photdms["psf_flux"].photcal.zp_mag.value == pytest.approx(20.44)
    assert issued.photdms["sap_bkg"].photcal.zp_mag is None
    xml = payload.decode("utf-8")
    assert 'ucd="instr.background"' in xml
    assert "phot.flux;instr.background" not in xml
    assert 'name="flag" datatype="char" arraysize="*"' in xml
    assert 'name="quality" datatype="long"' in xml
    assert "Author is not in the reviewed registry" in xml


def test_unknown_author_without_flux_origin_issues_everything_without_roles():
    """No FLUX_ORIGIN: every column issued, no flux role, no error."""
    lc = _FakeLC(
        ["time", "sap_flux"],
        {"time": np.array([1400.0]), "sap_flux": np.array([1.0])},
        author="NOT-A-PIPELINE",
    )
    payload = votable_from_lightcurve(
        lc, tic=4, sector=2, author="NOT-A-PIPELINE", exptime=1800.0
    )
    assert 'name="sap_flux"' in payload.decode("utf-8")
    assert "phot.flux" not in payload.decode("utf-8")


def test_unknown_author_magnitude_flux_is_phot_mag():
    """A declared flux column in mag is issued as phot.mag without 20.44."""
    lc = _FakeLC(
        ["time", "flux", "irm1"],
        {
            "time": np.array([1400.0]),
            "flux": np.array([12.0]),
            "irm1": np.array([12.0]),
        },
        meta={"FLUX_ORIGIN": "irm1"},
        author="CDIPS",
        units={"irm1": "mag"},
    )
    xml = votable_from_lightcurve(
        lc, tic=5, sector=16, author="CDIPS", exptime=1800.0
    ).decode("utf-8")
    assert 'ucd="phot.mag"' in xml
    assert "zeroPointReferenceMagnitude" not in xml


def test_known_author_without_electron_unit_has_no_2044():
    """20.44 depends on the file unit, also for SPOC."""
    lc = _FakeLC(
        ["time", "pdcsap_flux"],
        {"time": np.array([1400.0]), "pdcsap_flux": np.array([1.0])},
        units={"pdcsap_flux": "ppm"},
    )
    issued = load_issued(
        votable_from_lightcurve(lc, tic=6, sector=3, author="SPOC", exptime=120.0)
    )
    assert issued.photdms["pdcsap_flux"].photcal.zp_mag is None


def test_contradicting_time_system_raises():
    """A product declaring another time format fails explicitly."""
    lc = _FakeLC(["time", "flux"], {"time": np.array([1.0]), "flux": np.array([1.0])})
    lc.time.format = "jd"
    with pytest.raises(ValueError, match="BTJD"):
        votable_from_lightcurve(lc, tic=7, sector=1, author="X", exptime=1.0)
