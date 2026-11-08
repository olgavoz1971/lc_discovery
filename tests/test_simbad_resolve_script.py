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


class _FakeAstroquerySimbad:
    """Stand-in for the shared ``Simbad`` object with a settable mirror."""

    server = "simbad.cds.unistra.fr"


def _install_fake_simbad(monkeypatch, behaviour):
    """Replaces the Simbad object and the name resolver used by ``main``.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        behaviour: Callable run instead of ``resolve_simbad_name``.

    Returns:
        The fake Simbad class, so a test can read the mirror that was set.
    """
    import astroquery.simbad as aq

    fake = type("Simbad", (), {"server": "simbad.cds.unistra.fr"})
    monkeypatch.setattr(aq, "Simbad", fake)
    monkeypatch.setattr(simbad_resolve, "resolve_simbad_name", behaviour)
    return fake


def test_main_sets_the_requested_mirror_before_the_query(monkeypatch, capsys):
    """``--server`` is applied before the first query and the answer is exit code 0."""
    seen = {}

    def behaviour(name):
        seen["server"] = fake.server
        return simbad_resolve.SimbadResolveResult(
            query_name=name, main_id="X", identifiers=("X",), ra_deg=1.0, dec_deg=2.0
        )

    fake = _install_fake_simbad(monkeypatch, behaviour)
    code = simbad_resolve.main(["--server", "simbad.harvard.edu", "name", "X"])
    assert code == simbad_resolve.EXIT_ANSWERED
    assert seen["server"] == "simbad.harvard.edu"
    assert '"main_id": "X"' in capsys.readouterr().out


def test_main_not_found_is_an_answer_with_its_own_exit_code(monkeypatch, capsys):
    """An unknown name gives exit code 3: the mirror answered, do not ask another."""

    def behaviour(name):
        raise simbad_resolve.SimbadNotResolvedError("unknown")

    _install_fake_simbad(monkeypatch, behaviour)
    assert simbad_resolve.main(["name", "X"]) == simbad_resolve.EXIT_NOT_RESOLVED
    assert "answered" in capsys.readouterr().err


def test_main_network_failure_has_its_own_exit_code(monkeypatch, capsys):
    """A connection failure gives exit code 4 and names the mirror."""

    def behaviour(name):
        raise ConnectionError("no route")

    _install_fake_simbad(monkeypatch, behaviour)
    code = simbad_resolve.main(["--server", "simbad.cds.unistra.fr", "name", "X"])
    assert code == simbad_resolve.EXIT_NETWORK_FAILURE
    assert "simbad.cds.unistra.fr" in capsys.readouterr().err
