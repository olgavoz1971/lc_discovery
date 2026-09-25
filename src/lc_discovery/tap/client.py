"""Synchronous TAP query execution via pyvo."""

from __future__ import annotations

import logging

from astropy.table import Table

from lc_discovery.tap.dialect import TapQueryDialect
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)


def run_tap_sync_query(
    tap_url: str,
    adql: str,
    *,
    dialect: TapQueryDialect | str,
) -> Table:
    """Runs a synchronous TAP query and returns the result table.

    Args:
        tap_url (str): TAP service base URL.
        adql (str): Complete ADQL query string.
        dialect (TapQueryDialect or str): TAP ``LANG`` value (e.g. ``ADQL-2.1``).

    Returns:
        astropy.table.Table: Query result (possibly empty).

    Raises:
        PipeException: When pyvo is unavailable or the TAP call fails.
    """
    if not tap_url or not str(tap_url).strip():
        raise PipeException("TAP URL is empty.")
    if not adql or not str(adql).strip():
        raise PipeException("ADQL query is empty.")

    language = dialect.value if isinstance(dialect, TapQueryDialect) else str(dialect)
    logger.info(
        "TAP ADQL query tap_url=%s dialect=%s adql=%s",
        tap_url,
        language,
        adql.strip(),
    )

    try:
        import pyvo
    except ImportError as exc:
        raise PipeException("pyvo is required for TAP provider queries.") from exc

    try:
        service = pyvo.dal.TAPService(tap_url)
        result = service.run_sync(adql, language=language)
        table = result.to_table()
        logger.info(
            "TAP sync query tap_url=%s dialect=%s rows=%s",
            tap_url,
            language,
            len(table),
        )
        return table
    except PipeException:
        raise
    except Exception as exc:
        logger.warning(
            "TAP query failed tap_url=%s dialect=%s: %s",
            tap_url,
            language,
            exc,
        )
        raise PipeException(f"TAP query failed: {exc}") from exc
