"""Gaia DR3 variability class and period resolution for the AIP TAP provider."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

import numpy as np
from astropy.table import Table, vstack

from lc_discovery.providers.gaia_dr3_aip import config

logger = logging.getLogger(__name__)


class PeriodKind(str, Enum):
    """How to interpret a period column returned by a ``gaiadr3.vari_*`` table."""

    DAYS = "days"
    FREQUENCY = "frequency"


@dataclass(frozen=True)
class VariSummaryRoute:
    """Maps one ``vari_summary`` membership flag to an optional period source table."""

    summary_flag: str
    table_name: str
    period_column: str | None
    period_kind: PeriodKind | None


# First matching true flag wins; AGN and microlensing are non-periodic.
VARI_SUMMARY_ROUTES: tuple[VariSummaryRoute, ...] = (
    VariSummaryRoute("in_vari_cepheid", "gaiadr3.vari_cepheid", "pf", PeriodKind.DAYS),
    VariSummaryRoute(
        "in_vari_rrlyrae",
        "gaiadr3.vari_rrlyrae",
        "pf",
        PeriodKind.DAYS,
    ),
    VariSummaryRoute(
        "in_vari_eclipsing_binary",
        "gaiadr3.vari_eclipsing_binary",
        "frequency",
        PeriodKind.FREQUENCY,
    ),
    VariSummaryRoute(
        "in_vari_long_period_variable",
        "gaiadr3.vari_long_period_variable",
        "frequency",
        PeriodKind.FREQUENCY,
    ),
    VariSummaryRoute(
        "in_vari_ms_oscillator",
        "gaiadr3.vari_ms_oscillator",
        "frequency1",
        PeriodKind.FREQUENCY,
    ),
    VariSummaryRoute(
        "in_vari_short_timescale",
        "gaiadr3.vari_short_timescale",
        "frequency",
        PeriodKind.FREQUENCY,
    ),
    VariSummaryRoute(
        "in_vari_rotation_modulation",
        "gaiadr3.vari_rotation_modulation",
        "best_rotation_period",
        PeriodKind.DAYS,
    ),
    VariSummaryRoute(
        "in_vari_planetary_transit",
        "gaiadr3.vari_planetary_transit",
        "transit_period",
        PeriodKind.DAYS,
    ),
    VariSummaryRoute(
        "in_vari_compact_companion",
        "gaiadr3.vari_compact_companion",
        "period",
        PeriodKind.DAYS,
    ),
    VariSummaryRoute("in_vari_agn", "gaiadr3.vari_agn", None, None),
    VariSummaryRoute("in_vari_microlensing", "gaiadr3.vari_microlensing", None, None),
)


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


def flag_is_true(value: Any) -> bool:
    """Interprets Gaia TAP boolean flag values.

    Args:
        value: TAP cell value.

    Returns:
        bool: True when the flag is logically set.
    """
    if value is None or value is np.ma.masked:
        return False
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, np.integer)):
        return int(value) != 0
    if isinstance(value, float):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "t", "1", "yes"}
    return False


def pick_vari_route(summary_row) -> VariSummaryRoute | None:
    """Selects the first matching ``vari_summary`` route for one source.

    Args:
        summary_row: One ``gaiadr3.vari_summary`` TAP row.

    Returns:
        VariSummaryRoute or None: First route whose membership flag is true.
    """
    for route in VARI_SUMMARY_ROUTES:
        if flag_is_true(_row_value(summary_row, route.summary_flag)):
            return route
    return None


def period_days_from_value(value: Any, *, period_kind: PeriodKind) -> float | None:
    """Converts one vari-table period cell to days.

    Args:
        value: Raw TAP period or frequency value.
        period_kind (PeriodKind): Interpretation of ``value``.

    Returns:
        float or None: Period in days when valid.
    """
    if value is None or value is np.ma.masked:
        return None
    if isinstance(value, np.generic):
        value = value.item()
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric) or numeric <= 0.0:
        return None
    if period_kind == PeriodKind.FREQUENCY:
        return 1.0 / numeric
    return numeric


def route_sources_by_vari_table(
    summary_table: Table,
) -> dict[str, list[int]]:
    """Groups source ids by the first matching specialised vari table.

    Args:
        summary_table (astropy.table.Table): ``gaiadr3.vari_summary`` TAP result.

    Returns:
        dict[str, list[int]]: Vari table name to source ids requiring a period query.
    """
    grouped: dict[str, list[int]] = {}
    for row in summary_table:
        source_id = _row_value(row, "source_id")
        if source_id is None:
            continue
        route = pick_vari_route(row)
        if route is None or route.period_column is None or route.period_kind is None:
            continue
        grouped.setdefault(route.table_name, []).append(int(source_id))
    return grouped


def _route_for_table(table_name: str) -> VariSummaryRoute | None:
    """Returns the route metadata for one vari table name.

    Args:
        table_name (str): Fully qualified vari table name.

    Returns:
        VariSummaryRoute or None: Matching route definition.
    """
    for route in VARI_SUMMARY_ROUTES:
        if route.table_name == table_name:
            return route
    return None


def periods_from_vari_table(
    table_name: str,
    tap_table: Table,
) -> dict[int, float]:
    """Extracts source periods in days from one specialised vari TAP table.

    Args:
        table_name (str): Fully qualified vari table name.
        tap_table (astropy.table.Table): TAP query result.

    Returns:
        dict[int, float]: Source id to period in days for valid rows.
    """
    route = _route_for_table(table_name)
    if route is None or route.period_column is None or route.period_kind is None:
        return {}

    periods: dict[int, float] = {}
    for row in tap_table:
        source_id = _row_value(row, "source_id")
        if source_id is None:
            continue
        period_days = period_days_from_value(
            _row_value(row, route.period_column),
            period_kind=route.period_kind,
        )
        if period_days is not None:
            periods[int(source_id)] = period_days
    return periods


def fetch_periods_by_source_id(
    source_ids: list[int],
    *,
    run_tap_query: Callable[[str], Table],
    batch_size: int | None = None,
) -> dict[int, float]:
    """Resolves variability periods for many sources via ``vari_summary`` routing.

    Args:
        source_ids (list[int]): Gaia DR3 source identifiers.
        run_tap_query (callable): Executes one ADQL string and returns an Astropy table.
        batch_size (int, optional): Maximum ids per TAP ``IN`` query.

    Returns:
        dict[int, float]: Source id to period in days when known.
    """
    if not source_ids:
        return {}

    chunk_size = batch_size or config.MAX_SOURCE_IDS_PER_EPOCH_QUERY
    summary_chunks: list[Table] = []
    for start in range(0, len(source_ids), chunk_size):
        batch = source_ids[start : start + chunk_size]
        adql = config.adql_vari_summary_for_source_ids(batch)
        summary_chunks.append(run_tap_query(adql))

    if not summary_chunks:
        return {}
    summary_table = summary_chunks[0] if len(summary_chunks) == 1 else vstack(summary_chunks)
    grouped = route_sources_by_vari_table(summary_table)

    periods: dict[int, float] = {}
    for table_name, table_source_ids in grouped.items():
        route = _route_for_table(table_name)
        if route is None or route.period_column is None:
            continue
        table_chunks: list[Table] = []
        for start in range(0, len(table_source_ids), chunk_size):
            batch = table_source_ids[start : start + chunk_size]
            adql = config.adql_vari_period_for_source_ids(
                table_name,
                route.period_column,
                batch,
            )
            table_chunks.append(run_tap_query(adql))
        if not table_chunks:
            continue
        tap_table = table_chunks[0] if len(table_chunks) == 1 else vstack(table_chunks)
        periods.update(periods_from_vari_table(table_name, tap_table))

    logger.info(
        "%s resolved variability periods for %s/%s sources",
        config.DISPLAY_NAME,
        len(periods),
        len(source_ids),
    )
    return periods
