"""Tests for the mission coverage declaration (VO Registry model)."""

from __future__ import annotations

import pytest

from lc_discovery import MissionCoverage, list_missions
from lc_discovery.base import MissionCapabilities, MissionLightcurveProvider
from lc_discovery.coverage import validate_coverage

UNKNOWN = dict(spatial=None, temporal=None, spectral=None, waveband=None)


class _Provider(MissionLightcurveProvider):
    """Minimal provider; tests set ``coverage`` on subclasses."""

    mission_id = "dummy"
    display_name = "Dummy"
    export_profile = "test"
    capabilities = MissionCapabilities()
    description = "A dummy mission."
    data_group = "dummy"
    is_subset = False
    subset_description = ""
    group_rank = 1

    def search_catalog(self, **kwargs):
        raise NotImplementedError

    def fetch_lightcurve(self, lc_key, **kwargs):
        raise NotImplementedError


def _coverage(**changes) -> MissionCoverage:
    """Builds a coverage with all parts unknown, except the given ones.

    Args:
        **changes: Fields to set.

    Returns:
        MissionCoverage: Coverage object.
    """
    return MissionCoverage(**{**UNKNOWN, **changes})


def test_every_registered_mission_declares_coverage():
    for mission in list_missions():
        assert isinstance(mission.coverage, MissionCoverage)


def test_descriptor_requires_coverage():
    with pytest.raises(ValueError, match="coverage"):
        type("NoCoverage", (_Provider,), {})().descriptor()


def test_descriptor_returns_declared_coverage():
    declared = _coverage(spatial="0/0-11", temporal=((56863.0, 57902.0),))
    provider = type("Declared", (_Provider,), {"coverage": declared})()
    assert provider.descriptor().coverage is declared


def test_all_parts_must_be_given():
    with pytest.raises(TypeError):
        MissionCoverage(spatial=None)


def test_unknown_parts_are_valid():
    assert validate_coverage("m", _coverage()) is not None


def test_valid_full_coverage():
    validate_coverage(
        "m",
        MissionCoverage(
            spatial="0/0-11",
            temporal=((56863, 57902), (58324.0, 100000.0)),
            spectral=((2.0e-19, 4.0e-19),),
            waveband=("Optical",),
        ),
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"spatial": ""},
        {"spatial": 5},
        {"temporal": ()},
        {"temporal": [(1.0, 2.0)]},
        {"temporal": ((57902.0, 56863.0),)},
        {"temporal": ((56863.5, 57902.0),)},
        {"temporal": ((float("nan"), 57902.0),)},
        {"temporal": ((1.0, 2.0, 3.0),)},
        {"temporal": ((True, 2.0),)},
        {"spectral": ((0.0, 1e-19),)},
        {"spectral": ((3e-19, 2e-19),)},
        {"waveband": ()},
        {"waveband": ("Optical", "")},
        {"waveband": ["Optical"]},
    ],
)
def test_invalid_coverage_is_rejected(changes):
    with pytest.raises(ValueError, match="coverage"):
        validate_coverage("m", _coverage(**changes))


def _missions() -> dict:
    """Maps mission ids to their descriptors.

    Returns:
        dict: ``mission_id`` to ``MissionDescriptor``.
    """
    return {m.mission_id: m for m in list_missions()}


def test_gaia_missions_share_all_sky_and_observing_period():
    missions = _missions()
    for mission_id in ("gaia_dr3_ari", "gaia_dr3_aip", "gaia_dr3_veb"):
        coverage = missions[mission_id].coverage
        assert coverage.spatial == "0/0-11"
        assert coverage.temporal == ((56863.0, 57902.0),)


def test_simple_declared_values():
    missions = _missions()
    assert missions["asassn"].coverage.spatial == "0/0-11"
    assert missions["asassn"].coverage.temporal == ((56293.0, 100000.0),)
    assert missions["tess"].coverage.temporal == ((58324.0, 100000.0),)
    assert missions["tess"].coverage.spatial.startswith("0/0-11")  # planned sectors cover the sky
    assert missions["panstarrs1_dr2"].coverage.temporal == ((55197.0, 56748.0),)
    ztf = missions["ztf_dr24"].coverage
    assert ztf.temporal == ((58178.0, 60971.0),)  # DR24 ends 22 October 2025
    assert ztf.spatial == missions["panstarrs1_dr2"].coverage.spatial


def test_every_mission_declares_optical_waveband():
    for mission_id, mission in _missions().items():
        assert mission.coverage.waveband == ("Optical",), mission_id


def test_gaia_missions_share_the_registry_spectral_interval():
    for mission_id in ("gaia_dr3_ari", "gaia_dr3_aip", "gaia_dr3_veb"):
        (start, end), = _missions()[mission_id].coverage.spectral
        assert 1.8e-19 < start < 2.0e-19 and 6.0e-19 < end < 6.1e-19


def test_registry_values_of_upjs_served_missions():
    missions = _missions()
    assert missions["upjs_ts"].coverage.temporal == ((58726.0, 59520.0),)
    assert missions["personal_ts"].coverage.temporal == ((36804.0, 59496.0),)
    for mission_id in ("upjs_ts", "personal_ts"):
        coverage = missions[mission_id].coverage
        assert coverage.spatial and coverage.spectral


def test_ogle_space_comes_from_the_maintainer():
    coverage = _missions()["ogle_ocvs"].coverage
    assert coverage.spatial.startswith("2/112 3/338 369")
    assert coverage.temporal == ((48622.0, 100000.0),)
    assert coverage.spectral is not None  # rough, from the filter table


def test_moc_strings_of_upjs_served_missions_parse():
    mocpy = pytest.importorskip("mocpy")
    for mission_id in ("ogle_ocvs", "upjs_ts", "personal_ts"):
        moc = mocpy.MOC.from_string(_missions()[mission_id].coverage.spatial)
        assert 0.0 < moc.sky_fraction < 1.0, mission_id


def test_tool_renders_a_module_that_keeps_the_moc_string():
    pytest.importorskip("pyvo")
    import importlib.util
    from datetime import date
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "tools" / "fetch_registry_coverage.py"
    spec = importlib.util.spec_from_file_location("fetch_registry_coverage", path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    moc = "6/" + " ".join(str(n) for n in range(5000, 5100, 2))
    values = {"spatial": moc, "temporal": ((1.0, 2.0),), "spectral": ((1e-19, 2e-19),)}
    source = tool.render_module("ivo://x/y", values, "http://reg", date(2026, 10, 16))
    namespace: dict = {}
    exec(source, namespace)
    assert namespace["REGISTRY_SPATIAL_MOC"] == moc
    assert namespace["REGISTRY_TEMPORAL"] == ((1.0, 2.0),)


def test_moc_strings_parse_and_cover_the_expected_sky():
    mocpy = pytest.importorskip("mocpy")
    import astropy.units as u

    missions = _missions()
    all_sky = mocpy.MOC.from_string(missions["asassn"].coverage.spatial)
    assert all_sky.sky_fraction == pytest.approx(1.0)
    zone = mocpy.MOC.from_string(missions["ztf_dr24"].coverage.spatial)
    north = zone.contains_lonlat([0, 90, 180, 270] * u.deg, [-29, 0, 45, 89] * u.deg)
    south = zone.contains_lonlat([0, 90, 180, 270] * u.deg, [-60, -45, -40, -89] * u.deg)
    assert north.all()
    assert not south.any()


def test_coverage_must_be_the_dataclass():
    with pytest.raises(ValueError, match="MissionCoverage"):
        validate_coverage("m", {"spatial": None})


def test_rough_spectral_coverage_from_the_filter_table():
    missions = _missions()
    for mission_id in ("asassn", "ztf_dr24", "panstarrs1_dr2", "tess", "ogle_ocvs"):
        (start, end), = missions[mission_id].coverage.spectral
        assert 0.0 < start < end, mission_id
    # PS1 reaches further into the red than ZTF (z band) and ASAS-SN
    assert missions["panstarrs1_dr2"].coverage.spectral[0][0] < missions["ztf_dr24"].coverage.spectral[0][0]
    assert missions["asassn"].coverage.spectral[0][1] == missions["ztf_dr24"].coverage.spectral[0][1]
