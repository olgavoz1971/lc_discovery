"""Heidelberg Gaia DR3 timeseries datalink URLs for epoch photometry products."""

from __future__ import annotations

from lc_discovery.providers.gaia_dr3_ari import config


def build_timeseries_datalink_url(source_id: int | str) -> str:
    """Builds the ARI HTTP datalink for one Gaia DR3 bundled epoch VOTable.

    The service returns a multi-table VOTable (G, BP, RP bands) addressed
    via ``table_id`` when parsing the download.

    Args:
        source_id (int or str): Gaia DR3 ``source_id``.

    Returns:
        str: Absolute datalink URL such as
            ``https://gaia.ari.uni-heidelberg.de/timeseries/gaiadr3?sourceid=…``.
    """
    sid = int(source_id)
    return f"{config.TIMESERIES_DATALINK_BASE_URL}?sourceid={sid}"
