"""Map ``MeanObjectView`` TAP rows onto the shared discovery catalogue schema."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.catalog_schema import empty_catalog_table, validate_catalog_table
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.providers.panstarrs1_dr2.ps1_names import format_ps1_object_name

logger = logging.getLogger(__name__)


def _column_map(table: Table) -> dict[str, str]:
    """Builds a lowercase column name lookup for a TAP result table.

    Args:
        table (astropy.table.Table): TAP query result.

    Returns:
        dict: Lowercase name to actual column name.
    """
    return {str(name).lower(): str(name) for name in table.colnames}


def _cell(row, columns: dict[str, str], key: str):
    """Returns one row value using case-insensitive column lookup.

    Args:
        row: Astropy table row.
        columns (dict): Lowercase to actual column map.
        key (str): Logical column name.

    Returns:
        object or None: Cell value when present and finite.
    """
    actual = columns.get(key.lower())
    if actual is None:
        return None
    value = row[actual]
    if value is None or value == "":
        return None
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def _object_name_for_row(obj_id_int: int) -> str:
    """Returns catalogue ``object_name`` as the Pan-STARRS ``objID``.

    Args:
        obj_id_int (int): Mean-object identifier.

    Returns:
        str: Display label for discovery tables.
    """
    return format_ps1_object_name(obj_id_int)


def _n_detections_for_band(row, columns: dict[str, str], band: config.Ps1BandSpec) -> int:
    """Reads per-filter detection count from a mean-object row.

    Args:
        row: Astropy table row.
        columns (dict): Column name map.
        band (Ps1BandSpec): Target band.

    Returns:
        int: Detection count, or zero when missing.
    """
    value = _cell(row, columns, band.n_det_column)
    if value is None:
        return 0
    try:
        count = int(value)
    except (TypeError, ValueError):
        return 0
    return max(count, 0)


def _mean_mag_for_band(row, columns: dict[str, str], band: config.Ps1BandSpec) -> float | None:
    """Reads mean PSF magnitude for one band when finite.

    Args:
        row: Astropy table row.
        columns (dict): Column name map.
        band (Ps1BandSpec): Target band.

    Returns:
        float or None: Mean magnitude.
    """
    value = _cell(row, columns, band.mean_mag_column)
    if value is None:
        return None
    try:
        mag = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(mag):
        return None
    return mag


def _distance_arcsec(
    row,
    columns: dict[str, str],
    *,
    centre_ra_deg: float | None,
    centre_dec_deg: float | None,
) -> float:
    """Computes separation from the search centre when coordinates are known.

    Args:
        row: Astropy table row.
        columns (dict): Column name map.
        centre_ra_deg (float, optional): Cone centre RA in degrees.
        centre_dec_deg (float, optional): Cone centre Dec in degrees.

    Returns:
        float: Distance in arcseconds, or zero when centre is unknown.
    """
    if centre_ra_deg is None or centre_dec_deg is None:
        return 0.0
    ra = _cell(row, columns, "raMean")
    dec = _cell(row, columns, "decMean")
    if ra is None or dec is None:
        return 0.0
    target = SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg)
    centre = SkyCoord(ra=float(centre_ra_deg) * u.deg, dec=float(centre_dec_deg) * u.deg)
    return float(target.separation(centre).arcsec)


def map_mean_object_table_to_catalog(
    tap_table: Table,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Expands mean-object rows into one catalogue row per band with detections.

    Args:
        tap_table (astropy.table.Table): ``MeanObjectView`` query result.
        provider_id (str): Registry mission slug for ``lc_key``.
        centre_ra_deg (float, optional): Cone centre for distance sorting.
        centre_dec_deg (float, optional): Cone centre for distance sorting.

    Returns:
        astropy.table.Table: Validated discovery catalogue (possibly empty).
    """
    if tap_table is None or len(tap_table) == 0:
        return empty_catalog_table()

    columns = _column_map(tap_table)
    rows: list[dict[str, Any]] = []

    for row in tap_table:
        obj_id = _cell(row, columns, "objID")
        ra_val = _cell(row, columns, "raMean")
        dec_val = _cell(row, columns, "decMean")
        if obj_id is None or ra_val is None or dec_val is None:
            continue
        try:
            obj_id_int = int(obj_id)
        except (TypeError, ValueError):
            continue

        object_name = _object_name_for_row(obj_id_int)
        distance = _distance_arcsec(
            row,
            columns,
            centre_ra_deg=centre_ra_deg,
            centre_dec_deg=centre_dec_deg,
        )

        for band in config.PS1_BANDS:
            n_det = _n_detections_for_band(row, columns, band)
            if n_det < 1:
                continue
            lc_key = encode_lc_key(
                provider_id,
                {
                    "obj_id": str(obj_id_int),
                    "filter": band.filter_name,
                    "ra_deg": float(ra_val),
                    "dec_deg": float(dec_val),
                    "object_name": object_name,
                },
            )
            catalog_row: dict[str, Any] = {
                "distance_arcsec": distance,
                "ra_deg": float(ra_val),
                "dec_deg": float(dec_val),
                "object_name": object_name,
                "filter_name": band.filter_name,
                "filter_identifier": band.filter_identifier,
                "lc_key": lc_key,
                "n_points": int(n_det),
                "survey": config.SURVEY_LABEL,
                "provider_note": config.DISCOVERY_CATALOG_PROVIDER_NOTE,
            }
            mean_mag = _mean_mag_for_band(row, columns, band)
            if mean_mag is not None:
                catalog_row["mag"] = mean_mag
            rows.append(catalog_row)

    if not rows:
        return empty_catalog_table()

    return validate_catalog_table(Table(rows))
