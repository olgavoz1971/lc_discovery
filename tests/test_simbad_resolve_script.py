"""Tests of scripts/simbad_resolve.py (no network)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from astropy.table import Table

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "simbad_resolve.py"
spec = importlib.util.spec_from_file_location("simbad_resolve", SCRIPT)
simbad_resolve = importlib.util.module_from_spec(spec)
sys.modules["simbad_resolve"] = simbad_resolve
spec.loader.exec_module(simbad_resolve)


class _FakeSimbad:
    """Minimal stand-in for astroquery.simbad.Simbad."""

    def __init__(self, ids):
        self._ids = ids

    def query_objectids(self, main_id):
        return None if self._ids is None else Table({"ID": self._ids})


def test_column_lookup_ignores_case():
    table = Table({"MAIN_ID": ["x"]})
    assert simbad_resolve._column(table, "main_id")[0] == "x"
    with pytest.raises(KeyError):
        simbad_resolve._column(table, "ra")


def test_identifiers_start_with_main_id_without_duplicates():
    fake = _FakeSimbad(["V* AA And", "TIC 1", "TIC 1"])
    assert simbad_resolve._identifiers(fake, "V* AA And") == ("V* AA And", "TIC 1")


def test_missing_identifiers_fail_explicitly():
    with pytest.raises(simbad_resolve.SimbadNotResolvedError):
        simbad_resolve._identifiers(_FakeSimbad(None), "X")


def test_empty_name_is_rejected():
    with pytest.raises(ValueError):
        simbad_resolve.resolve_simbad_name("  ")
