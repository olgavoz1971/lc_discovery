"""Standardised catalog table schema for multi-mission lightcurve discovery.

One catalog row represents one plottable lightcurve (not one astrophysical source).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np
from astropy.table import Table, vstack

logger = logging.getLogger(__name__)

DISCOVERY_META_MAY_BE_TRUNCATED = "discovery_may_be_truncated"
DISCOVERY_META_TRUNCATION_DETAIL = "discovery_truncation_detail"
CATALOG_META_EXTRA_FIELDS = "catalog_extra_fields"


@dataclass(frozen=True)
class CatalogExtraColumn:
    """One provider-declared catalogue display column.

    Attributes:
        field (str): Table field id. Must not clash with core names.
        header (str): Column title shown in the results table.
        width (int, optional): Preferred column width in pixels. When omitted
            the host applies its narrow default for provider extras.
    """

    field: str
    header: str
    width: int | None = None

REQUIRED_CATALOG_COLUMNS = (
    "distance_arcsec",
    "ra_deg",
    "dec_deg",
    "object_name",
    "filter_name",
    "lc_key",
)

OPTIONAL_CATALOG_COLUMNS = (
    "t_min",
    "t_max",
    "filter_identifier",
    "n_points",
    "mag",
    "object_class",
    "survey",
    "provider_note",
    "epoch",
    "period",
)

CATALOG_COLUMN_DTYPES = {
    "distance_arcsec": np.float64,
    "ra_deg": np.float64,
    "dec_deg": np.float64,
    "object_name": object,
    "filter_name": object,
    "lc_key": object,
    "t_min": np.float64,
    "t_max": np.float64,
    "filter_identifier": object,
    "n_points": np.int64,
    "mag": np.float64,
    "object_class": object,
    "survey": object,
    "provider_note": object,
    "epoch": np.float64,
    "period": np.float64,
}


def extra_column_fields(
    extra_columns: Sequence[CatalogExtraColumn] | Sequence[str] | None,
) -> tuple[str, ...]:
    """Returns field ids from an extra-column declaration.

    Args:
        extra_columns: ``CatalogExtraColumn`` items, field-id strings, or None.

    Returns:
        tuple[str, ...]: Field ids in declaration order.
    """
    if not extra_columns:
        return ()
    fields: list[str] = []
    for item in extra_columns:
        if isinstance(item, CatalogExtraColumn):
            fields.append(item.field)
        else:
            fields.append(str(item))
    return tuple(fields)


def empty_catalog_table(
    extra_columns: Sequence[CatalogExtraColumn] | Sequence[str] | None = None,
) -> Table:
    """Creates an empty catalog table with all standard columns present.

    Args:
        extra_columns: Optional extra display columns declared by a provider.

    Returns:
        astropy.table.Table: Empty table with required, optional, and extra columns.
    """
    extra_fields = extra_column_fields(extra_columns)
    _reject_core_name_clash(extra_fields)
    columns = {}
    for name in REQUIRED_CATALOG_COLUMNS + OPTIONAL_CATALOG_COLUMNS:
        dtype = CATALOG_COLUMN_DTYPES[name]
        columns[name] = np.array([], dtype=dtype)
    for name in extra_fields:
        columns[name] = np.array([], dtype=object)
    table = Table(columns)
    table.meta[CATALOG_META_EXTRA_FIELDS] = extra_fields
    return table


def validate_catalog_table(
    table: Table,
    extra_columns: Sequence[CatalogExtraColumn] | Sequence[str] | None = None,
) -> Table:
    """Validates and normalises a mission catalog table.

    Extra columns are allowed only when declared (argument or table meta).
    Their names must not duplicate a core required or optional column.

    Args:
        table (astropy.table.Table): Candidate catalog from a provider search.
        extra_columns: Provider extra-column declaration. When omitted, field
            ids are read from ``table.meta['catalog_extra_fields']``.

    Returns:
        astropy.table.Table: Copy with required, optional, and declared extra columns.

    Raises:
        TypeError: If ``table`` is not an Astropy ``Table``.
        ValueError: If required columns are missing, extras clash with core
            names, or undeclared columns are present.
    """
    if not isinstance(table, Table):
        raise TypeError(f"Catalog table must be astropy.table.Table, got {type(table)!r}")

    missing = [name for name in REQUIRED_CATALOG_COLUMNS if name not in table.colnames]
    if missing:
        raise ValueError(f"Catalog table missing required columns: {missing}")

    if extra_columns is not None:
        extra_fields = extra_column_fields(extra_columns)
    else:
        extra_fields = extra_column_fields(table.meta.get(CATALOG_META_EXTRA_FIELDS))
    _reject_core_name_clash(extra_fields)

    allowed = set(REQUIRED_CATALOG_COLUMNS) | set(OPTIONAL_CATALOG_COLUMNS) | set(extra_fields)
    unknown = [name for name in table.colnames if name not in allowed]
    if unknown:
        raise ValueError(f"Catalog table has unknown columns: {unknown}")

    normalised = table.copy()
    for name in OPTIONAL_CATALOG_COLUMNS:
        if name not in normalised.colnames:
            normalised[name] = np.ma.masked_all(len(normalised), dtype=CATALOG_COLUMN_DTYPES[name])
    for name in extra_fields:
        if name not in normalised.colnames:
            normalised[name] = np.array([""] * len(normalised), dtype=object)

    ordered = REQUIRED_CATALOG_COLUMNS + OPTIONAL_CATALOG_COLUMNS + extra_fields
    result = normalised[ordered]
    result.meta.update(table.meta)
    result.meta[CATALOG_META_EXTRA_FIELDS] = extra_fields
    return result


def _reject_core_name_clash(extra_fields: Sequence[str]) -> None:
    """Raises when an extra field id collides with a core catalogue name.

    Args:
        extra_fields (Sequence[str]): Declared extra field ids.

    Raises:
        ValueError: When a core name is reused.
    """
    core = set(REQUIRED_CATALOG_COLUMNS) | set(OPTIONAL_CATALOG_COLUMNS)
    clash = [name for name in extra_fields if name in core]
    if clash:
        raise ValueError(
            f"Extra catalogue columns must not reuse core names: {clash}."
        )


def sort_catalog_by_distance(table: Table) -> Table:
    """Sorts catalogue rows by ascending ``distance_arcsec`` (masked last).

    Tie-breakers: ``object_name``, then ``filter_name``, for stable separation
    ordering when several bands share the same sky position.

    Args:
        table (astropy.table.Table): Standardised discovery catalogue.

    Returns:
        astropy.table.Table: Sorted copy when the column is present.
    """
    if len(table) == 0 or "distance_arcsec" not in table.colnames:
        return table
    distances = np.asarray(table["distance_arcsec"], dtype=np.float64)
    if np.ma.isMaskedArray(distances):
        fill = np.nanmax(distances.filled(np.nan)) + 1.0 if len(distances) else 0.0
        distances = distances.filled(fill)
    object_names = np.asarray(table["object_name"]).astype(str) if "object_name" in table.colnames else np.zeros(len(table), dtype=str)
    filter_names = np.asarray(table["filter_name"]).astype(str) if "filter_name" in table.colnames else np.zeros(len(table), dtype=str)
    order = np.lexsort((filter_names, object_names, distances))
    return table[order]


def read_discovery_truncation_meta(table: Table) -> tuple[bool, str | None]:
    """Reads discovery truncation hints attached by a mission provider.

    Args:
        table (astropy.table.Table): Catalogue table from ``search_catalog``.

    Returns:
        tuple[bool, str | None]: ``(may_be_truncated, detail_message)``.
    """
    may_be = bool(table.meta.get(DISCOVERY_META_MAY_BE_TRUNCATED))
    detail = table.meta.get(DISCOVERY_META_TRUNCATION_DETAIL)
    if detail is not None and not str(detail).strip():
        detail = None
    elif detail is not None:
        detail = str(detail)
    return may_be, detail


def catalog_table_to_row_dicts(table: Table) -> list[dict[str, Any]]:
    """Serialises a catalog table to plain dict rows for JSON stores.

    Args:
        table (astropy.table.Table): Validated catalog table.

    Returns:
        list[dict]: One dict per row with native Python scalars.
    """
    validated = validate_catalog_table(table)
    rows: list[dict[str, Any]] = []
    for row in validated:
        record: dict[str, Any] = {}
        for name in validated.colnames:
            value = row[name]
            if isinstance(value, np.generic):
                value = value.item()
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            record[name] = None if value is np.ma.masked else value
        rows.append(record)
    return rows


def catalog_row_to_indexed_dict(row, *, row_index: int) -> dict[str, Any]:
    """Converts one catalog row to a dict with a one-based display index.

    Args:
        row: Astropy table row or dict-like catalog record.
        row_index (int): Zero-based row index shown in the ``#`` column.

    Returns:
        dict: Row payload with the index.
    """
    if hasattr(row, "colnames"):
        payload = {name: row[name] for name in row.colnames}
    else:
        payload = dict(row)

    indexed_row: dict[str, Any] = {"#": row_index + 1}
    for key, value in payload.items():
        if isinstance(value, np.generic):
            value = value.item()
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        indexed_row[key] = None if value is np.ma.masked else value
    return indexed_row


def append_catalog_rows(base: Table, extra: Table) -> Table:
    """Concatenates two catalog tables after schema validation.

    Args:
        base (astropy.table.Table): Existing catalog (may be empty).
        extra (astropy.table.Table): Rows to append.

    Returns:
        astropy.table.Table: Combined validated catalog.
    """
    if len(base) == 0:
        return validate_catalog_table(extra)
    if len(extra) == 0:
        return validate_catalog_table(base)
    return validate_catalog_table(vstack([validate_catalog_table(base), validate_catalog_table(extra)]))


def catalog_row_overlaps_time_bounds(
    row_t_min,
    row_t_max,
    *,
    time_start_mjd: float | None,
    time_end_mjd: float | None,
) -> bool:
    """Checks whether one catalogue row overlaps a query time window in MJD.

    Row ``t_min`` / ``t_max`` follow ObsCore-style naming (MJD). Masked or NaN
    row bounds are treated as unknown coverage and are kept in the result.

    ``time_start_mjd`` / ``time_end_mjd`` use ``None`` for an open bound
    (negative or positive infinity respectively).

    Args:
        row_t_min: Catalogue row coverage start in MJD.
        row_t_max: Catalogue row coverage end in MJD.
        time_start_mjd (float, optional): Query lower bound in MJD.
        time_end_mjd (float, optional): Query upper bound in MJD.

    Returns:
        bool: True when the row time span intersects the query window.
    """
    if row_t_min is np.ma.masked or row_t_max is np.ma.masked:
        return True
    if np.isnan(float(row_t_min)) or np.isnan(float(row_t_max)):
        return True
    query_start = float("-inf") if time_start_mjd is None else float(time_start_mjd)
    query_end = float("inf") if time_end_mjd is None else float(time_end_mjd)
    return float(row_t_min) <= query_end and float(row_t_max) >= query_start


def filter_catalog_table_by_time_bounds(
    table: Table,
    *,
    time_start_mjd: float | None,
    time_end_mjd: float | None,
) -> Table:
    """Filters a catalogue table to rows overlapping optional MJD time bounds.

    Args:
        table (astropy.table.Table): Candidate catalogue from a provider search.
        time_start_mjd (float, optional): Query lower bound in MJD.
        time_end_mjd (float, optional): Query upper bound in MJD.

    Returns:
        astropy.table.Table: Filtered catalogue (possibly empty).
    """
    if time_start_mjd is None and time_end_mjd is None:
        return table
    if len(table) == 0:
        return table
    if "t_min" not in table.colnames or "t_max" not in table.colnames:
        logger.warning(
            "Catalogue table lacks t_min/t_max columns; skipping time-bound filter."
        )
        return table

    keep_mask = [
        catalog_row_overlaps_time_bounds(
            row["t_min"],
            row["t_max"],
            time_start_mjd=time_start_mjd,
            time_end_mjd=time_end_mjd,
        )
        for row in table
    ]
    filtered = table[keep_mask]
    if len(filtered) == 0:
        return empty_catalog_table()
    return validate_catalog_table(filtered)
