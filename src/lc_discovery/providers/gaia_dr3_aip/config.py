"""Configuration and ADQL 2.0 templates for the Gaia DR3 (AIP) TAP provider."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from lc_discovery.tap.adql import adql_top_limit_clause
from lc_discovery.tap.dialect import TapQueryDialect
from skvo_veb.utils.lc_config import JD_TO_MJD

PROVIDER_ID = "gaia_dr3_aip"
DISPLAY_NAME = "Gaia DR3 (AIP)"
TAP_URL = "https://gaia.aip.de/tap"
TAP_QUERY_DIALECT = TapQueryDialect.ADQL_2_0
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 1.0
GAIA_SOURCE_TABLE = "gaiadr3.gaia_source_lite"
EPOCH_PHOTOMETRY_TABLE = "gaiadr3.epoch_photometry"
VARI_CLASSIFIER_RESULT_TABLE = "gaiadr3.vari_classifier_result"
VARI_SUMMARY_TABLE = "gaiadr3.vari_summary"
GAIA_SURVEY = "Gaia DR3"

FACILITY_NAME = "Gaia"
INSTRUMENT_NAME = "Gaia"

CLASSIFIER_CLASS_COLUMN = "best_class_name"

# BJD reference epoch for AIP epoch-photometry time columns (2010-01-01T00:00:00).
GAIA_AIP_TIME_EPOCH_JD = 2455197.5
GAIA_AIP_TIME_EPOCH_MJD = GAIA_AIP_TIME_EPOCH_JD - JD_TO_MJD

# PhotCal constants aligned with Gaia DR3 (ARI) archive products (see data/gaia_ari.vot).
GAIA_AIP_ZERO_POINT_REFERENCE_MAGNITUDE = 0.0
GAIA_AIP_MAGNITUDE_SYSTEM = "Vega"

SOURCE_SELECT_COLUMNS = (
    "gs.source_id",
    "gs.ra",
    "gs.dec",
    "gs.phot_g_mean_mag",
    "vcr.best_class_name",
)

VARI_SUMMARY_FLAG_COLUMNS = (
    "in_vari_cepheid",
    "in_vari_rrlyrae",
    "in_vari_eclipsing_binary",
    "in_vari_long_period_variable",
    "in_vari_ms_oscillator",
    "in_vari_short_timescale",
    "in_vari_rotation_modulation",
    "in_vari_planetary_transit",
    "in_vari_compact_companion",
    "in_vari_agn",
    "in_vari_microlensing",
)

EPOCH_SELECT_COLUMNS = (
    "source_id",
    "g_transit_time",
    "g_transit_flux_over_error",
    "g_transit_mag",
    "g_transit_n_obs",
    "bp_obs_time",
    "bp_flux_over_error",
    "bp_mag",
    "rp_obs_time",
    "rp_flux_over_error",
    "rp_mag",
)

N_POINTS_PROVIDER_NOTE = (
    "Epoch photometry prefetched at discovery from gaiadr3.epoch_photometry. "
    "G-band n_points uses valid transit epochs; BP/RP counts omit n_obs."
)

DISCOVERY_CATALOG_PROVIDER_NOTE = (
    "Epoch photometry and time coverage are fetched when a row is loaded, "
    "not at catalogue search."
)

PREFETCH_CACHE_DIR = Path(
    os.environ.get(
        "GAIA_AIP_PREFETCH_CACHE_DIR",
        str(Path(__file__).resolve().parents[3] / "cache" / "lc_providers" / "gaia_dr3_aip"),
    )
)

MAX_SOURCE_IDS_PER_EPOCH_QUERY = 50


@dataclass(frozen=True)
class GaiaAipBandSpec:
    """One Gaia DR3 epoch-photometry passband exposed by the AIP TAP tables."""

    band_code: str
    filter_name: str
    filter_identifier: str
    zp_flux_jy: float
    effective_wavelength_angstrom: float
    time_column: str
    mag_column: str
    snr_column: str


GAIA_AIP_BANDS: tuple[GaiaAipBandSpec, ...] = (
    GaiaAipBandSpec(
        band_code="G",
        filter_name="Gaia G",
        filter_identifier="GAIADR3.G",
        zp_flux_jy=3296.2,
        effective_wavelength_angstrom=6230.0,
        time_column="g_transit_time",
        mag_column="g_transit_mag",
        snr_column="g_transit_flux_over_error",
    ),
    GaiaAipBandSpec(
        band_code="BP",
        filter_name="Gaia BP",
        filter_identifier="GAIADR3.Gbp",
        zp_flux_jy=3534.7,
        effective_wavelength_angstrom=5050.0,
        time_column="bp_obs_time",
        mag_column="bp_mag",
        snr_column="bp_flux_over_error",
    ),
    GaiaAipBandSpec(
        band_code="RP",
        filter_name="Gaia RP",
        filter_identifier="GAIADR3.Grp",
        zp_flux_jy=2620.3,
        effective_wavelength_angstrom=7730.0,
        time_column="rp_obs_time",
        mag_column="rp_mag",
        snr_column="rp_flux_over_error",
    ),
)

_BAND_BY_CODE = {band.band_code: band for band in GAIA_AIP_BANDS}


def band_spec_for_code(band_code: str) -> GaiaAipBandSpec:
    """Returns the configured band specification for a Gaia passband code.

    Args:
        band_code (str): Gaia band code (``G``, ``BP``, or ``RP``).

    Returns:
        GaiaAipBandSpec: Band metadata and epoch-photometry column mapping.

    Raises:
        ValueError: When ``band_code`` is not supported.
    """
    normalised = str(band_code).strip().upper()
    if normalised == "G":
        key = "G"
    elif normalised in {"BP", "BP_BAND"}:
        key = "BP"
    elif normalised in {"RP", "RP_BAND"}:
        key = "RP"
    else:
        key = normalised
    spec = _BAND_BY_CODE.get(key)
    if spec is None:
        supported = ", ".join(sorted(_BAND_BY_CODE))
        raise ValueError(f"Unsupported Gaia AIP band '{band_code}'. Supported: {supported}.")
    return spec


def _select_clause(columns: tuple[str, ...]) -> str:
    """Returns a comma-separated SELECT column list.

    Args:
        columns (tuple[str, ...]): ADQL column names.

    Returns:
        str: SELECT list fragment.
    """
    return ", ".join(columns)


def adql_gaia_source_by_id(source_id: int | str) -> str:
    """Builds ADQL 2.0 for direct ``gaiadr3.gaia_source`` lookup with class join.

    Args:
        source_id (int or str): Gaia DR3 source identifier.

    Returns:
        str: Complete ADQL query string.
    """
    sid = int(source_id)
    select_cols = _select_clause(SOURCE_SELECT_COLUMNS)
    return (
        f"SELECT {select_cols} "
        f"FROM {GAIA_SOURCE_TABLE} AS gs "
        f"LEFT JOIN {VARI_CLASSIFIER_RESULT_TABLE} AS vcr "
        f"ON gs.source_id = vcr.source_id "
        f"WHERE gs.source_id = {sid} AND gs.has_epoch_photometry = 'True'"
    )


def adql_gaia_source_cone(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    row_limit: int | None = None,
) -> str:
    """Builds ADQL 2.0 cone search on ``gaiadr3.gaia_source`` with class join.

    Discovery cone radius for this mission is capped at one degree, so a single
    ``SELECT TOP`` on ``gaia_source`` with ``CONTAINS`` and a classifier join
    is acceptable on Gaia@AIP TAP.

    Args:
        ra_deg (float): Cone centre right ascension in degrees.
        dec_deg (float): Cone centre declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        row_limit (int, optional): Maximum number of source rows (``SELECT TOP``).

    Returns:
        str: Complete ADQL query string.
    """
    radius_deg = float(radius_arcsec) / 3600.0
    ra = float(ra_deg)
    dec = float(dec_deg)
    top = adql_top_limit_clause(row_limit)
    select_cols = _select_clause(SOURCE_SELECT_COLUMNS)
    return (
        f"SELECT {top}{select_cols} "
        f"FROM {GAIA_SOURCE_TABLE} AS gs "
        f"LEFT JOIN {VARI_CLASSIFIER_RESULT_TABLE} AS vcr "
        f"ON gs.source_id = vcr.source_id "
        f"WHERE gs.has_epoch_photometry = 'True' "
        f"AND 1 = CONTAINS(POINT('ICRS', gs.ra, gs.dec), "
        f"CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) "
        f"ORDER BY gs.random_index"
    )


def adql_vari_summary_for_source_ids(source_ids: list[int] | tuple[int, ...]) -> str:
    """Builds ADQL 2.0 for ``gaiadr3.vari_summary`` membership flags.

    Args:
        source_ids (list[int] or tuple[int, ...]): Gaia DR3 source identifiers.

    Returns:
        str: Complete ADQL query string.

    Raises:
        ValueError: When ``source_ids`` is empty.
    """
    if not source_ids:
        raise ValueError("source_ids must not be empty for vari_summary query.")
    ids_csv = ", ".join(str(int(source_id)) for source_id in source_ids)
    columns = ("source_id", *VARI_SUMMARY_FLAG_COLUMNS)
    return (
        f"SELECT {_select_clause(columns)} "
        f"FROM {VARI_SUMMARY_TABLE} "
        f"WHERE source_id IN ({ids_csv})"
    )


def adql_vari_period_for_source_ids(
    table_name: str,
    period_column: str,
    source_ids: list[int] | tuple[int, ...],
) -> str:
    """Builds ADQL 2.0 selecting one period column from a ``gaiadr3.vari_*`` table.

    Args:
        table_name (str): Fully qualified vari table name.
        period_column (str): Period or frequency column name.
        source_ids (list[int] or tuple[int, ...]): Gaia DR3 source identifiers.

    Returns:
        str: Complete ADQL query string.

    Raises:
        ValueError: When ``source_ids`` is empty.
    """
    if not source_ids:
        raise ValueError("source_ids must not be empty for vari period query.")
    ids_csv = ", ".join(str(int(source_id)) for source_id in source_ids)
    return (
        f"SELECT source_id, {period_column} "
        f"FROM {table_name} "
        f"WHERE source_id IN ({ids_csv})"
    )


def adql_epoch_photometry_for_source_ids(source_ids: list[int] | tuple[int, ...]) -> str:
    """Builds ADQL 2.0 for ``gaiadr3.epoch_photometry`` on one or more sources.

    Args:
        source_ids (list[int] or tuple[int, ...]): Gaia DR3 source identifiers.

    Returns:
        str: Complete ADQL query string.

    Raises:
        ValueError: When ``source_ids`` is empty.
    """
    if not source_ids:
        raise ValueError("source_ids must not be empty for epoch photometry query.")
    ids_csv = ", ".join(str(int(source_id)) for source_id in source_ids)
    return (
        f"SELECT {_select_clause(EPOCH_SELECT_COLUMNS)} "
        f"FROM {EPOCH_PHOTOMETRY_TABLE} "
        f"WHERE source_id IN ({ids_csv})"
    )
