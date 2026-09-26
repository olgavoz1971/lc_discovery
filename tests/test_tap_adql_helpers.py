"""Unit tests for shared TAP ADQL helper functions."""

from __future__ import annotations

from lc_discovery.tap.adql import adql_icrs_ra_dec_box_clauses


def test_adql_icrs_ra_dec_box_clauses_uses_qualified_columns():
    """Sky box helper emits BETWEEN predicates on the supplied column names."""
    clause = adql_icrs_ra_dec_box_clauses(
        ra_deg=346.34517,
        dec_deg=47.67631,
        radius_arcsec=10.0,
        ra_column="gs.ra",
        dec_column="gs.dec",
    )
    assert clause.startswith("gs.ra BETWEEN")
    assert "AND gs.dec BETWEEN" in clause
