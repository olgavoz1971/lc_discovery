"""Map Gaia DR3 (ARI) ObsCore TAP rows onto the shared discovery catalogue schema."""

from __future__ import annotations

import logging
from typing import Any

from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.table import Table

from lc_discovery.catalog_schema import empty_catalog_table, validate_catalog_table
from lc_discovery.providers.gaia_dr3_ari import config
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.shared.gaia_dr3_source_id import format_gaia_source_name

logger = logging.getLogger(__name__)


def _row_value(row, column: str):
    """Returns one TAP row value when the column exists.

    Args:
        row: Astropy table row.
        column (str): Column name.

    Returns:
        object or None: Cell value, or ``None`` when absent or masked.
    """
    if column not in row.colnames:
        return None
    value = row[column]
    if value is None or value == "":
        return None
    return value


def map_obscore_row_to_catalog_rows(
    row,
    *,
    provider_id: str,
    distance_arcsec: float,
) -> list[dict[str, Any]]:
    """Expands one ObsCore row into three standard catalogue rows (G, BP, RP).

    Args:
        row: TAP ObsCore result row.
        provider_id (str): Registry slug stored in ``lc_key``.
        distance_arcsec (float): Separation from the search centre in arcseconds.

    Returns:
        list[dict]: Up to three standard catalogue row dicts.
    """
    access_url = _row_value(row, "access_url")
    if not access_url:
        return []

    ra_val = _row_value(row, "s_ra")
    dec_val = _row_value(row, "s_dec")
    if ra_val is None or dec_val is None:
        return []

    obs_id = _row_value(row, "obs_id")
    object_name = format_gaia_source_name(obs_id) if obs_id is not None else "Gaia DR3 source"

    t_min = _row_value(row, "t_min")
    t_max = _row_value(row, "t_max")
    n_points = _row_value(row, "t_xel")

    catalog_rows: list[dict[str, Any]] = []
    for band in config.GAIA_ARI_BANDS:
        lc_key = encode_lc_key(
            provider_id,
            {
                "access_url": str(access_url),
                "source_id": str(obs_id) if obs_id is not None else None,
                "band": band.band_code,
                "table_id": band.table_id,
                "filter_name": band.filter_name,
            },
        )
        catalog_row: dict[str, Any] = {
            "distance_arcsec": float(distance_arcsec),
            "ra_deg": float(ra_val),
            "dec_deg": float(dec_val),
            "object_name": object_name,
            "filter_name": band.filter_name,
            "lc_key": lc_key,
            "t_min": t_min,
            "t_max": t_max,
            "survey": "Gaia DR3",
            "provider_note": config.N_POINTS_PROVIDER_NOTE,
        }
        if n_points is not None:
            try:
                catalog_row["n_points"] = int(n_points)
            except (TypeError, ValueError):
                pass
        catalog_rows.append(catalog_row)
    return catalog_rows


def map_obscore_table_to_catalog(
    tap_table: Table,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps an ObsCore TAP result table onto the shared discovery catalogue schema.

    Args:
        tap_table (astropy.table.Table): Raw TAP query result.
        provider_id (str): Registry slug for ``lc_key`` encoding.
        centre_ra_deg (float, optional): Search centre RA for separation.
        centre_dec_deg (float, optional): Search centre Dec for separation.

    Returns:
        astropy.table.Table: Validated catalogue table (possibly empty).
    """
    if len(tap_table) == 0:
        return empty_catalog_table()

    centre = None
    if centre_ra_deg is not None and centre_dec_deg is not None:
        centre = SkyCoord(
            ra=float(centre_ra_deg) * u.deg,
            dec=float(centre_dec_deg) * u.deg,
            frame="icrs",
        )

    rows: list[dict[str, Any]] = []
    for row in tap_table:
        ra_val = _row_value(row, "s_ra")
        dec_val = _row_value(row, "s_dec")
        if ra_val is None or dec_val is None:
            continue
        if centre is not None:
            source = SkyCoord(ra=float(ra_val) * u.deg, dec=float(dec_val) * u.deg, frame="icrs")
            distance_arcsec = centre.separation(source).to_value(u.arcsec)
        else:
            distance_arcsec = 0.0
        rows.extend(
            map_obscore_row_to_catalog_rows(
                row,
                provider_id=provider_id,
                distance_arcsec=distance_arcsec,
            )
        )

    if not rows:
        return empty_catalog_table()
    return validate_catalog_table(Table(rows))
