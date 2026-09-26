"""Tests for shared SSA TAP row parsing helpers."""

import numpy as np

from lc_discovery.shared.tap_ssa_row import (
    object_class_from_ssa_row,
    parse_ssa_location,
)


def test_parse_ssa_location_parenthesis_text():
    """Parenthesis sky location syntax parses to RA/Dec degrees."""
    ra, dec = parse_ssa_location("(17.193708333333312, -72.11341666666681)")
    assert ra == 17.193708333333312
    assert dec == -72.11341666666681


def test_parse_ssa_location_numeric_array():
    """Numeric pair columns from TAP parse to RA/Dec degrees."""
    ra, dec = parse_ssa_location(np.array([289.432, 36.102]))
    assert ra == 289.432
    assert dec == 36.102


def test_object_class_from_ssa_row():
    """Simbad object type is read from ssa_targclass when present."""
    row = {"ssa_targclass": "CV*"}
    assert object_class_from_ssa_row(row) == "CV*"

    assert object_class_from_ssa_row({"ssa_bandpass": "R"}) is None
