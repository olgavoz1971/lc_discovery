"""Configuration and ADQL 2.1 templates for the UPJŠ time-series TAP provider."""

from __future__ import annotations

from lc_discovery.tap.adql import adql_top_limit_clause
from lc_discovery.tap.dialect import TapQueryDialect

PROVIDER_ID = "upjs_ts"
DISPLAY_NAME = "UPJŠ TS"
TAP_URL = "https://skvo.science.upjs.sk/tap"
TAP_QUERY_DIALECT = TapQueryDialect.ADQL_2_1
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 30.0
SSA_TABLE = "upjs_ts.ts_ssa"
OBJECTS_TABLE = "upjs_ts.objects"

# Magnitude zero point by photDM:PhotometryFilter.identifier.
# Applied to every product of this provider when that identifier is listed
# and the file has no magnitude zero point. The flux zero point stays as published.
ZP_MAG_BY_FILTER_IDENTIFIER = {
    "Generic/Bessell.U": 0.0,
    "Generic/Bessell.B": 0.0,
    "Generic/Bessell.V": 0.0,
    "Generic/Bessell.R": 0.0,
    "Generic/Bessell.I": 0.0,
    "SLOAN/SDSS.g": 0.0,
    "SLOAN/SDSS.r": 0.0,
    "SLOAN/SDSS.i": 0.0,
}
ZP_MAG_UNIT = "mag"

SSA_SELECT_COLUMNS = (
    "object_id",
    "accref",
    "ssa_bandpass",
    "ssa_targname",
    "ssa_targclass",
    "ssa_location",
    "ssa_length",
    "ssa_collection",
    "t_min",
    "t_max",
    "mean_mag",
)


def _select_clause() -> str:
    """Returns the shared SSA SELECT column list.

    Returns:
        str: Comma-separated SSA column names.
    """
    return ", ".join(SSA_SELECT_COLUMNS)


def _adql_string_literal(value: str) -> str:
    """Escapes a string for ADQL single-quoted literals.

    Args:
        value (str): Raw string value.

    Returns:
        str: ADQL-safe quoted literal.
    """
    return "'" + str(value).replace("'", "''") + "'"


def _time_bound_clauses(
    *,
    time_start_mjd: float | None,
    time_end_mjd: float | None,
) -> list[str]:
    """Builds optional ADQL time-window predicates in MJD.

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


def adql_catalog_by_object_id(
    object_id: str,
    *,
    time_start_mjd: float | None = None,
    time_end_mjd: float | None = None,
) -> str:
    """Builds ADQL 2.1 for direct ``object_id`` SSA catalogue lookup.

    Args:
        object_id (str): UPJŠ archive object identifier.
        time_start_mjd (float, optional): Lower time bound in MJD.
        time_end_mjd (float, optional): Upper time bound in MJD.

    Returns:
        str: Complete ADQL query string.
    """
    predicates = [
        f"object_id = {_adql_string_literal(object_id)}",
        *_time_bound_clauses(
            time_start_mjd=time_start_mjd,
            time_end_mjd=time_end_mjd,
        ),
    ]
    where = " AND ".join(predicates)
    return f"SELECT {_select_clause()} FROM {SSA_TABLE} WHERE {where}"


def adql_catalog_by_ssa_targname(
    ssa_targname: str,
    *,
    time_start_mjd: float | None = None,
    time_end_mjd: float | None = None,
) -> str:
    """Builds ADQL 2.1 for lookup on indexed ``ssa_targname`` (Gaia DR3 labels).

    Args:
        ssa_targname (str): SSA target name, typically ``Gaia DR3 <source_id>``.
        time_start_mjd (float, optional): Lower time bound in MJD.
        time_end_mjd (float, optional): Upper time bound in MJD.

    Returns:
        str: Complete ADQL query string.
    """
    predicates = [
        f"ssa_targname = {_adql_string_literal(ssa_targname)}",
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


def adql_objects_by_simbad_name(name: str) -> str:
    """Builds ADQL 2.1 for case-insensitive ``simbad_name`` lookup.

    Args:
        name (str): Simbad main identifier or alias text.

    Returns:
        str: Complete ADQL query string.
    """
    literal = _adql_string_literal(str(name))
    return (
        "SELECT object_id, gaia_name, simbad_name, vsx_name "
        f"FROM {OBJECTS_TABLE} "
        f"WHERE UPPER(simbad_name) = UPPER({literal})"
    )


def adql_objects_by_vsx_name(name: str) -> str:
    """Builds ADQL 2.1 for case-insensitive ``vsx_name`` lookup.

    Args:
        name (str): VSX catalogue name text.

    Returns:
        str: Complete ADQL query string.
    """
    literal = _adql_string_literal(str(name))
    return (
        "SELECT object_id, gaia_name, simbad_name, vsx_name "
        f"FROM {OBJECTS_TABLE} "
        f"WHERE vsx_name IS NOT NULL AND vsx_name <> '' "
        f"AND UPPER(vsx_name) = UPPER({literal})"
    )
