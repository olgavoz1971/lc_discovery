"""Cross-identification lookup against ``upjs_ts.objects``."""

from __future__ import annotations

import logging

from lc_discovery.shared.tap_ssa_row import row_value
from lc_discovery.tap.client import run_tap_sync_query
from lc_discovery.providers.upjs_ts import config

logger = logging.getLogger(__name__)


def _lookup_object_id(adql: str, *, matched_label: str, match_kind: str) -> tuple[str, str] | None:
    """Runs one objects-table query and returns ``object_id`` when a row matches.

    Args:
        adql (str): ADQL query against ``upjs_ts.objects``.
        matched_label (str): User alias that produced the match.
        match_kind (str): Provider match kind for Discovery metadata.

    Returns:
        tuple[str, str] or None: ``(object_id, matched_label)`` when recognised.
    """
    table = run_tap_sync_query(
        config.TAP_URL,
        adql,
        dialect=config.TAP_QUERY_DIALECT,
    )
    if len(table) == 0:
        return None
    object_id = row_value(table[0], "object_id")
    if object_id is None:
        return None
    resolved_id = str(object_id).strip()
    logger.info(
        "%s %s matched alias=%r object_id=%r",
        config.DISPLAY_NAME,
        match_kind,
        matched_label,
        resolved_id,
    )
    return resolved_id, matched_label


def lookup_object_id_by_simbad_name(name: str) -> tuple[str, str] | None:
    """Resolves a Simbad-style name to ``object_id`` via ``upjs_ts.objects``.

    Args:
        name (str): Simbad identifier text from the UI.

    Returns:
        tuple[str, str] or None: ``(object_id, matched_label)`` when recognised.
    """
    query_name = str(name or "").strip()
    if not query_name:
        return None
    return _lookup_object_id(
        config.adql_objects_by_simbad_name(query_name),
        matched_label=query_name,
        match_kind="simbad_name",
    )


def lookup_object_id_by_vsx_name(name: str) -> tuple[str, str] | None:
    """Resolves a VSX name to ``object_id`` via ``upjs_ts.objects``.

    Args:
        name (str): VSX catalogue name from the UI.

    Returns:
        tuple[str, str] or None: ``(object_id, matched_label)`` when recognised.
    """
    query_name = str(name or "").strip()
    if not query_name:
        return None
    return _lookup_object_id(
        config.adql_objects_by_vsx_name(query_name),
        matched_label=query_name,
        match_kind="vsx_name",
    )
