"""Tests for Pan-STARRS MeanObjectView epoch conversion."""

from __future__ import annotations

import pytest
from astropy.table import Table
from astropy.time import Time

from lc_discovery.providers.panstarrs1_dr2.mean_object_epoch import (
    coosys_epoch_year_from_detection_table,
    coosys_epoch_year_from_epoch_mean_mjd,
)


def test_coosys_epoch_year_from_epoch_mean_mjd():
    """epochMean MJD converts to decimal year via Astropy, rounded for COOSYS."""
    mjd = 57123.45
    raw = float(Time(mjd, format="mjd").decimalyear)
    assert coosys_epoch_year_from_epoch_mean_mjd(mjd) == pytest.approx(round(raw, 1))


def test_coosys_epoch_year_from_detection_table_first_finite_row():
    """Joined detection tables expose epochMean on every row."""
    mjd = 58000.0
    table = Table({"epochMean": [float("nan"), mjd, mjd]})
    column_map = {"epochmean": "epochMean"}
    year = coosys_epoch_year_from_detection_table(table, column_map=column_map)
    assert year == round(float(Time(mjd, format="mjd").decimalyear), 1)


def test_coosys_epoch_year_from_detection_table_missing_column():
    """Missing epochMean fails fast."""
    table = Table({"obsTime": [58000.0]})
    with pytest.raises(ValueError, match="epochMean"):
        coosys_epoch_year_from_detection_table(table, column_map={"obstime": "obsTime"})
