"""Map MAST/Lightkurve search rows onto the shared Discovery catalogue schema."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from astropy.table import Table

from lc_discovery.catalog_schema import empty_catalog_table, validate_catalog_table
from lc_discovery.lc_key import encode_lc_key
from lc_discovery.providers.tess import config
from lc_discovery.providers.tess.columns import parse_sector_from_mission_label
from lc_discovery.providers.tess.tic import parse_tic

logger = logging.getLogger(__name__)


def _cell(row, column: str):
    """Returns one search-table cell when the column exists.

    Args:
        row: Astropy table row.
        column (str): Column name.

    Returns:
        object or None: Cell value.
    """
    if column not in row.colnames:
        return None
    value = row[column]
    if value is None:
        return None
    if isinstance(value, np.ma.core.MaskedConstant) or np.ma.is_masked(value):
        return None
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        try:
            value = value.value
        except Exception:
            pass
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and value != value:
        return None
    return value


def _exptime_seconds(row) -> float | None:
    """Reads MAST cadence ``exptime`` as seconds.

    Args:
        row: Lightkurve search table row.

    Returns:
        float or None: Cadence in seconds.
    """
    raw = _cell(row, "exptime")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _tic_from_row(row) -> int | None:
    """Extracts a TIC from ``target_name`` or related search columns.

    Args:
        row: Lightkurve search table row.

    Returns:
        int or None: TIC when digits are present.
    """
    for column in ("target_name", "targetid", "obs_id"):
        raw = _cell(row, column)
        if raw is None:
            continue
        tic = parse_tic(str(raw))
        if tic is None:
            digits = "".join(ch for ch in str(raw) if ch.isdigit())
            if digits:
                try:
                    return int(digits)
                except ValueError:
                    continue
            continue
        return tic
    return None


def _float_or_none(value) -> float | None:
    """Parses a finite float.

    Args:
        value: Raw cell.

    Returns:
        float or None: Parsed value.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def map_search_table_to_catalog(
    search_table: Table,
    *,
    provider_id: str,
    centre_ra_deg: float | None = None,
    centre_dec_deg: float | None = None,
) -> Table:
    """Maps a Lightkurve search table to standardised Discovery rows.

    One MAST product (TIC + sector + author + exptime) is one catalogue row.
    Authors absent from the TESS registry are omitted.

    Args:
        search_table (astropy.table.Table): ``SearchResult.table``.
        provider_id (str): Mission slug for ``lc_key``.
        centre_ra_deg (float, optional): Cone centre RA for distance.
        centre_dec_deg (float, optional): Cone centre Dec for distance.

    Returns:
        astropy.table.Table: Validated catalogue (possibly empty).
    """
    if search_table is None or len(search_table) == 0:
        return empty_catalog_table(extra_columns=config.CATALOG_EXTRA_COLUMNS)

    rows: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for row in search_table:
        mapped = map_search_row_to_catalog_row(
            row,
            provider_id=provider_id,
            centre_ra_deg=centre_ra_deg,
            centre_dec_deg=centre_dec_deg,
        )
        if mapped is None:
            continue
        key = (
            mapped["_tic"],
            mapped["_sector"],
            mapped["_author"],
            mapped["_exptime"],
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                name: mapped[name]
                for name in (
                    "distance_arcsec",
                    "ra_deg",
                    "dec_deg",
                    "object_name",
                    "filter_name",
                    "lc_key",
                    "filter_identifier",
                    "t_min",
                    "t_max",
                    "mag",
                    config.FIELD_SECTOR,
                    config.FIELD_EXP,
                    config.FIELD_AUTHOR,
                )
                if name in mapped and mapped[name] is not np.ma.masked
            }
        )

    if not rows:
        return empty_catalog_table(extra_columns=config.CATALOG_EXTRA_COLUMNS)
    return validate_catalog_table(
        Table(rows),
        extra_columns=config.CATALOG_EXTRA_COLUMNS,
    )


def map_search_row_to_catalog_row(
    row,
    *,
    provider_id: str,
    centre_ra_deg: float | None,
    centre_dec_deg: float | None,
) -> dict[str, Any] | None:
    """Maps one MAST search row to catalogue fields.

    Args:
        row: Lightkurve search table row.
        provider_id (str): Mission slug.
        centre_ra_deg (float, optional): Cone centre RA.
        centre_dec_deg (float, optional): Cone centre Dec.

    Returns:
        dict or None: Catalogue fields plus private uniqueness keys.
    """
    author_raw = _cell(row, "author")
    if author_raw is None:
        return None
    author = str(author_raw).strip()
    if not author:
        return None

    tic = _tic_from_row(row)
    if tic is None:
        logger.warning("%s search row missing TIC; omitted.", config.DISPLAY_NAME)
        return None

    sector = _cell(row, "sequence_number")
    if sector is not None:
        try:
            sector = int(sector)
        except (TypeError, ValueError):
            sector = None
    if sector is None:
        sector = parse_sector_from_mission_label(str(_cell(row, "mission") or ""))
    if sector is None:
        logger.warning(
            "%s search row for TIC %s missing sector; omitted.",
            config.DISPLAY_NAME,
            tic,
        )
        return None

    exptime = _exptime_seconds(row)
    if exptime is None:
        logger.warning(
            "%s search row TIC %s sector %s missing exptime; omitted.",
            config.DISPLAY_NAME,
            tic,
            sector,
        )
        return None

    ra_val = _float_or_none(_cell(row, "s_ra"))
    dec_val = _float_or_none(_cell(row, "s_dec"))
    if ra_val is None or dec_val is None:
        logger.warning(
            "%s search row TIC %s missing coordinates; omitted.",
            config.DISPLAY_NAME,
            tic,
        )
        return None

    distance = _float_or_none(_cell(row, "distance"))
    if distance is None and centre_ra_deg is not None and centre_dec_deg is not None:
        from astropy.coordinates import SkyCoord
        from astropy import units as u

        centre = SkyCoord(ra=centre_ra_deg * u.deg, dec=centre_dec_deg * u.deg)
        target = SkyCoord(ra=ra_val * u.deg, dec=dec_val * u.deg)
        distance = float(centre.separation(target).arcsec)
    if distance is None:
        distance = 0.0

    object_name = config.format_tic_name(tic)
    filter_name = config.TESS_FILTER_NAME
    mag = _float_or_none(_cell(row, "tmag"))
    if mag is None:
        mag = _float_or_none(_cell(row, "TESSMAG"))

    t_min = _float_or_none(_cell(row, "t_min"))
    t_max = _float_or_none(_cell(row, "t_max"))

    payload = {
        "tic": int(tic),
        "sector": int(sector),
        "author": author,
        "exptime": float(exptime),
    }
    lc_key = encode_lc_key(provider_id, payload)
    return {
        "distance_arcsec": float(distance),
        "ra_deg": float(ra_val),
        "dec_deg": float(dec_val),
        "object_name": object_name,
        "filter_name": filter_name,
        "lc_key": lc_key,
        "filter_identifier": config.TESS_FILTER_IDENTIFIER,
        "t_min": np.ma.masked if t_min is None else float(t_min),
        "t_max": np.ma.masked if t_max is None else float(t_max),
        "mag": np.ma.masked if mag is None else float(mag),
        config.FIELD_SECTOR: config.format_sector_cell(int(sector)),
        config.FIELD_EXP: config.format_exp_cell(float(exptime)),
        config.FIELD_AUTHOR: author,
        "_tic": int(tic),
        "_sector": int(sector),
        "_author": author,
        "_exptime": float(exptime),
    }
