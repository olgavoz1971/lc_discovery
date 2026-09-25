"""MeanObjectView epoch helpers for Pan-STARRS1 DR2 COOSYS metadata."""

from __future__ import annotations

import numpy as np
from astropy.table import Table
from astropy.time import Time

from lc_discovery.providers.panstarrs1_dr2 import config
from skvo_veb.utils.my_tools import PipeException


def coosys_epoch_year_from_epoch_mean_mjd(epoch_mean_mjd: float) -> float:
    """Converts ``MeanObjectView.epochMean`` (MJD) to a decimal year for COOSYS.

    Args:
        epoch_mean_mjd (float): Mean epoch of detections in Modified Julian Date.

    Returns:
        float: ICRS coordinate epoch as decimal year (one decimal place for VO).
    """
    year = float(Time(epoch_mean_mjd, format="mjd").decimalyear)
    return round(year, config.COOSYS_EPOCH_DECIMAL_PLACES)


def coosys_epoch_year_from_detection_table(
    detection_table: Table,
    *,
    column_map: dict[str, str],
) -> float:
    """Reads ``epochMean`` from a joined Detection query result.

    Args:
        detection_table (astropy.table.Table): TAP rows including ``epochMean``.
        column_map (dict): Lowercase to actual column names.

    Returns:
        float: COOSYS epoch in decimal years.

    Raises:
        PipeException: When the column or a finite value is missing.
    """
    actual = column_map.get("epochmean")
    if actual is None:
        raise PipeException(
            f"{config.DISPLAY_NAME}: detection query result missing epochMean column."
        )
    values = np.asarray(detection_table[actual], dtype=np.float64)
    for value in values:
        if np.isfinite(value):
            return coosys_epoch_year_from_epoch_mean_mjd(float(value))
    raise PipeException(
        f"{config.DISPLAY_NAME}: detection query returned no finite epochMean for COOSYS."
    )
