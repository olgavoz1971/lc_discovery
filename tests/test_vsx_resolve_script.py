"""Tests of scripts/vsx_resolve.py (parsing only; no network)."""

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "vsx_resolve.py"
spec = importlib.util.spec_from_file_location("vsx_resolve", SCRIPT)
vsx_resolve = importlib.util.module_from_spec(spec)
sys.modules["vsx_resolve"] = vsx_resolve
spec.loader.exec_module(vsx_resolve)

SAMPLE = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    "<VSXObject><Name>TCP J23580961+5502508</Name><AUID>000-BPL-357</AUID>"
    "<RA2000>359.54012</RA2000><Declination2000>55.04742</Declination2000>"
    "<VariabilityType>UGWZ</VariabilityType><Period>0.05940</Period>"
    "<MaxMag>11.7 V</MaxMag><MinMag>20.9 V</MinMag><Category>Variable</Category>"
    "<OID>2344951</OID><Constellation>Cas</Constellation></VSXObject>"
)


def test_parses_a_record():
    star = vsx_resolve.parse_vsx_xml("x", SAMPLE)
    assert star.name == "TCP J23580961+5502508"
    assert (star.ra_deg, star.dec_deg) == (359.54012, 55.04742)
    assert star.period_days == 0.0594 and star.epoch_jd is None
    assert star.detail_url.endswith("view=detail.top&oid=2344951")


def test_empty_record_is_not_resolved():
    with pytest.raises(vsx_resolve.VsxNotResolvedError):
        vsx_resolve.parse_vsx_xml("nope", "<VSXObject/>")


def test_bad_answers_fail_explicitly():
    with pytest.raises(ValueError):
        vsx_resolve.parse_vsx_xml("x", "<html></html>")
    with pytest.raises(ValueError):
        vsx_resolve.parse_vsx_xml("x", "not xml")
    with pytest.raises(ValueError):
        vsx_resolve.parse_vsx_xml("x", "<VSXObject><Name>A</Name></VSXObject>")
