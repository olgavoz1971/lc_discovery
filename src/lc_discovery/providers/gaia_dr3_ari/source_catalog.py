"""Map ``gaiadr3.gaia_source`` TAP rows (with classifier join) onto the discovery catalogue."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
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
    if isinstance(value, np.generic):
        value = value.item()
    if value is np.ma.masked:
        return None
    return value


def map_source_row_to_catalog_rows(
    source_row,
    *,
    provider_id: str,
    distance_arcsec: float,
) -> list[dict[str, Any]]:
    """Expands one ``gaia_source`` row into three band catalogue rows.

    Args:
        source_row: TAP ``gaia_source`` result row (with optional classifier join).
        provider_id (str): Registry slug stored in ``lc_key``.
        distance_arcsec (float): Separation from the search centre in arcseconds.

    Returns:
        list[dict]: Three standard catalogue row dicts (G, BP, RP).
    """
    source_id = _row_value(source_row, "source_id")
    ra_val = _row_value(source_row, "ra")
    dec_val = _row_value(source_row, "dec")
    if source_id is None or ra_val is None or dec_val is None:
        return []

    object_name = format_gaia_source_name(source_id)
    mean_mag = _row_value(source_row, "phot_g_mean_mag")
    object_class = _row_value(source_row, config.CLASSIFIER_CLASS_COLUMN)
    catalog_rows: list[dict[str, Any]] = []

    for band in config.GAIA_ARI_BANDS:
        lc_key = encode_lc_key(
            provider_id,
            {
                "source_id": str(source_id),
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
            "survey": config.GAIA_SURVEY,
            "provider_note": config.DISCOVERY_CATALOG_PROVIDER_NOTE,
        }
        if mean_mag is not None and band.band_code == "G":
            try:
                catalog_row["mag"] = float(mean_mag)
            except (TypeError, ValueError):
                pass
        if object_class is not None and str(object_class).strip():
            catalog_row["object_class"] = str(object_class).strip()
        catalog_rows.append(catalog_row)
    return catalog_rows


def map_source_table_to_catalog(
    source_table: Table,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps Gaia source TAP rows onto the shared catalogue schema.

    Args:
        source_table (astropy.table.Table): ``gaiadr3.gaia_source`` TAP result.
        provider_id (str): Registry slug for ``lc_key`` encoding.
        centre_ra_deg (float, optional): Search centre RA for separation.
        centre_dec_deg (float, optional): Search centre Dec for separation.

    Returns:
        astropy.table.Table: Validated catalogue table (possibly empty).
    """
    if len(source_table) == 0:
        return empty_catalog_table()

    centre = None
    if centre_ra_deg is not None and centre_dec_deg is not None:
        centre = SkyCoord(
            ra=float(centre_ra_deg) * u.deg,
            dec=float(centre_dec_deg) * u.deg,
            frame="icrs",
        )

    rows: list[dict[str, Any]] = []
    for source_row in source_table:
        ra_val = _row_value(source_row, "ra")
        dec_val = _row_value(source_row, "dec")
        if ra_val is None or dec_val is None:
            continue
        if centre is not None:
            source = SkyCoord(ra=float(ra_val) * u.deg, dec=float(dec_val) * u.deg, frame="icrs")
            distance_arcsec = centre.separation(source).to_value(u.arcsec)
        else:
            distance_arcsec = 0.0
        rows.extend(
            map_source_row_to_catalog_rows(
                source_row,
                provider_id=provider_id,
                distance_arcsec=distance_arcsec,
            )
        )

    if not rows:
        return empty_catalog_table()
    return validate_catalog_table(Table(rows))
