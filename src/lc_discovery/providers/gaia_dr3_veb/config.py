"""Configuration and ADQL 2.1 templates for the Gaia DR3 VEB TAP provider."""

from __future__ import annotations

from lc_discovery.tap.adql import adql_top_limit_clause
from lc_discovery.tap.dialect import TapQueryDialect

PROVIDER_ID = "gaia_dr3_veb"
DISPLAY_NAME = "Gaia DR3 VEB"
TAP_URL = "https://skvo.science.upjs.sk/tap"
TAP_QUERY_DIALECT = TapQueryDialect.ADQL_2_1
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 10.0
SSA_TABLE = "gaiadr3_eb.ts_ssa"

FACILITY_NAME = "Gaia"
INSTRUMENT_NAME = "Gaia"

# Flux is in electron/s (unit s**-1). The archive flux zero point is in Jy
# and is discarded for these filters. Magnitude zero points: Riello et al.
# 2021, A&A 649, A3.
GAIA_DR3_ZP_FLUX = 1.0
GAIA_DR3_ZP_FLUX_UNIT = "s**-1"
GAIA_DR3_ZP_MAG_UNIT = "mag"
GAIA_DR3_ZP_MAG_BY_FILTER_IDENTIFIER = {
    "GAIA/GAIA3.G": 25.6874,
    "GAIA/GAIA3.Gbp": 25.3385,
    "GAIA/GAIA3.Grp": 24.7479,
}
GAIA_DR3_ZP_SOURCE = "Riello et al. 2021, A&A 649, A3"

SSA_SELECT_COLUMNS = (
    "accref",
    "ssa_bandpass",
    "ssa_dstitle",
    "ssa_targname",
    "ssa_targclass",
    "ssa_location",
    "ssa_length",
    "ssa_creator",
    "ssa_collection",
    "t_min",
    "t_max",
)


def _select_clause() -> str:
    """Returns the shared SSA SELECT column list.

    Returns:
        str: Comma-separated SSA column names.
    """
    return ", ".join(SSA_SELECT_COLUMNS)


def _time_bound_clauses(
    *,
    time_start_mjd: float | None,
    time_end_mjd: float | None,
) -> list[str]:
    """Builds optional ADQL time-window predicates in MJD.

    Matches the VEB service convention ``t_min > start`` and ``t_max < end``.

    Args:
        time_start_mjd (float, optional): Lower bound in MJD.
        time_end_mjd (float, optional): Upper bound in MJD.

    Returns:
        list[str]: Zero or more ADQL predicate fragments.
    """
    clauses: list[str] = []
    if time_start_mjd is not None:
        clauses.append(f"t_min > {float(time_start_mjd)}")
    if time_end_mjd is not None:
        clauses.append(f"t_max < {float(time_end_mjd)}")
    return clauses


def adql_catalog_by_source_id(
    source_id: int,
    *,
    time_start_mjd: float | None = None,
    time_end_mjd: float | None = None,
) -> str:
    """Builds ADQL 2.1 for direct Gaia ``source_id`` SSA catalogue lookup.

    Args:
        source_id (int): Gaia DR3 source identifier.
        time_start_mjd (float, optional): Lower time bound in MJD.
        time_end_mjd (float, optional): Upper time bound in MJD.

    Returns:
        str: Complete ADQL query string.
    """
    predicates = [
        f"source_id = {int(source_id)}",
        *_time_bound_clauses(
            time_start_mjd=time_start_mjd,
            time_end_mjd=time_end_mjd,
        ),
    ]
    where = " AND ".join(predicates)
    return f"SELECT {_select_clause()} FROM {SSA_TABLE} WHERE {where}"


def adql_catalog_cone(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    time_start_mjd: float | None = None,
    time_end_mjd: float | None = None,
    row_limit: int | None = None,
) -> str:
    """Builds ADQL 2.1 for cone search on ``ssa_location``.

    Uses ``1 = CONTAINS(ssa_location, CIRCLE(...))`` per ADQL 2.1 geometry
    rules (point-in-circle). The deprecated ``'ICRS'`` coord-sys argument is
    omitted for ADQL 2.1 services.

    Args:
        ra_deg (float): Cone centre right ascension in degrees.
        dec_deg (float): Cone centre declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        time_start_mjd (float, optional): Lower time bound in MJD.
        time_end_mjd (float, optional): Upper time bound in MJD.
        row_limit (int, optional): Maximum number of SSA rows (``SELECT TOP``).

    Returns:
        str: Complete ADQL query string.
    """
    radius_deg = float(radius_arcsec) / 3600.0
    ra = float(ra_deg)
    dec = float(dec_deg)
    predicates = [
        f"1 = CONTAINS(ssa_location, CIRCLE({ra}, {dec}, {radius_deg}))",
        *_time_bound_clauses(
            time_start_mjd=time_start_mjd,
            time_end_mjd=time_end_mjd,
        ),
    ]
    where = " AND ".join(predicates)
    top = adql_top_limit_clause(row_limit)
    return f"SELECT {top}{_select_clause()} FROM {SSA_TABLE} WHERE {where}"
