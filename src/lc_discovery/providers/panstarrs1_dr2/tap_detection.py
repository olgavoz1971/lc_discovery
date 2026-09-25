"""TAP fetch for Pan-STARRS1 DR2 detection epoch tables."""

from __future__ import annotations

import logging

from astropy.table import Table

from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.tap.client import run_tap_sync_query

logger = logging.getLogger(__name__)


def fetch_detection_table(*, obj_id: int, filter_name: str) -> Table:
    """Downloads epoch photometry for one object and filter.

    Args:
        obj_id (int): Pan-STARRS mean object identifier.
        filter_name (str): PS1 filter ``g``, ``r``, ``i``, ``z``, or ``y``.

    Returns:
        astropy.table.Table: Detection rows (possibly empty).

    Raises:
        ValueError: When TAP fails or the filter name is invalid.
    """
    band = config.band_spec_for_filter_name(filter_name)
    adql = config.adql_detection_lightcurve(
        obj_id=int(obj_id),
        filter_name=band.filter_name,
    )
    try:
        table = run_tap_sync_query(
            config.TAP_URL,
            adql,
            dialect=config.TAP_QUERY_DIALECT,
        )
    except ValueError:
        raise
    except Exception as exc:
        logger.warning(
            "%s detection TAP failed obj_id=%s filter=%s: %s",
            config.DISPLAY_NAME,
            obj_id,
            filter_name,
            exc,
        )
        raise ValueError(
            f"{config.DISPLAY_NAME}: detection query failed for objID={obj_id}."
        ) from exc
    logger.info(
        "%s detection fetch obj_id=%s filter=%s rows=%s",
        config.DISPLAY_NAME,
        obj_id,
        filter_name,
        len(table),
    )
    return table
