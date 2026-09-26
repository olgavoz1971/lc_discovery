"""Tests for the standardised multi-mission catalog table schema."""

import numpy as np
import numpy as np
import pytest
from astropy.table import Table

from lc_discovery.catalog_schema import (
    catalog_row_to_aggrid_dict,
    catalog_table_to_row_dicts,
    empty_catalog_table,
    validate_catalog_table,
)
from lc_discovery.lc_key import encode_lc_key


def _sample_catalog_row() -> dict:
    """Builds one valid catalog row dict for schema tests.

    Returns:
        dict: Row payload with required columns populated.
    """
    return {
        "distance_arcsec": 1.2,
        "ra_deg": 189.23,
        "dec_deg": -12.45,
        "object_name": "Gaia DR3 1936512041221649536",
        "filter_name": "Gaia G",
        "lc_key": encode_lc_key("gaia", {"source_id": 1936512041221649536, "band": "G"}),
        "t_min": 57100.0,
        "t_max": 57200.0,
        "n_points": 24,
    }


def test_empty_catalog_table_has_required_columns():
    """Empty catalog exposes the full standard column set."""
    table = empty_catalog_table()
    assert len(table) == 0
    for name in (
        "distance_arcsec",
        "ra_deg",
        "dec_deg",
        "object_name",
        "filter_name",
        "lc_key",
        "t_min",
        "t_max",
        "n_points",
    ):
        assert name in table.colnames


def test_validate_catalog_table_rejects_missing_required_column():
    """Validation fails when a required column is absent."""
    table = Table([_sample_catalog_row()])
    table.remove_column("lc_key")
    with pytest.raises(ValueError, match="missing required columns"):
        validate_catalog_table(table)


def test_validate_catalog_table_accepts_missing_time_coverage():
    """t_min and t_max are optional; validation adds masked optional columns."""
    row = _sample_catalog_row()
    del row["t_min"]
    del row["t_max"]
    table = validate_catalog_table(Table([row]))
    assert np.all(np.ma.is_masked(table["t_min"]))
    assert np.all(np.ma.is_masked(table["t_max"]))


def test_catalog_table_to_row_dicts_round_trip():
    """Catalog rows serialise to plain Python dicts for AgGrid."""
    table = validate_catalog_table(Table([_sample_catalog_row()]))
    rows = catalog_table_to_row_dicts(table)
    assert len(rows) == 1
    assert rows[0]["object_name"] == "Gaia DR3 1936512041221649536"
    assert rows[0]["n_points"] == 24


def test_catalog_row_to_aggrid_dict_adds_index():
    """AgGrid helper adds the display index column."""
    table = validate_catalog_table(Table([_sample_catalog_row()]))
    aggrid_row = catalog_row_to_aggrid_dict(table[0], row_index=0)
    assert aggrid_row["#"] == 1
    assert aggrid_row["filter_name"] == "Gaia G"
