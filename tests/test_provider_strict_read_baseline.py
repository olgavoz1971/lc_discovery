"""Baseline (Ticket 33, phase 0): what the strict core of ``volightcurve`` finds in issued products.

Each issued product is read with ``read_lightcurve(..., strict=True)``, which accepts only what a
VOTable declares. The findings (what parses, what the check methods report as missing) are
recorded below as ``BASELINE``. The test fails when a finding changes, so every later phase has to
update the baseline on purpose. Nothing here changes a writer, and nothing uses the network.

Cases (all ten providers; recorded products live in ``tests/data``):

* Recorded as issued by Discovery: ``ztf`` (OID 1772216100034775, ZTF r), ``ogle_ocvs``
  (OGLE-LMC-RRLYR-13820).
* Recorded as the TAP service sends it, then passed through ``enrich_votable``: ``gaia_dr3_veb``,
  ``upjs_ts``, ``personal_ts`` (V band); ``gaia_dr3_ari`` and ``gaia_dr3_aip`` from the bundled samples.
* Recorded as issued by Discovery after the unit fix: ``tess`` (TESS-SPOC, TIC 455790537, sector 17),
  ``panstarrs1_dr2`` (PS1 165213463504091232, i).
* ``asassn`` has no case: no natural product is available yet (the service does not answer).
"""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("volightcurve", reason="volightcurve is a dev dependency of the Ticket 33 baseline")

from volightcurve import read_lightcurve  # noqa: E402

from lc_discovery.providers.gaia_dr3_veb.fetch_metadata import enrich_votable  # noqa: E402

_DATA = Path(__file__).parent / "data"


def _photcal_summary(photdm) -> dict | None:
    """Condenses the photometry filter and calibration of one column for the baseline.

    Args:
        photdm: ``PhotDM`` of one column.

    Returns:
        dict or None: ``filter``, ``zp_mag``, ``zp_flux`` (value and unit text) and ``mag_sys``;
            ``None`` when the column has no calibration.
    """
    cal = photdm.photcal
    if cal is None:
        return None
    return {
        "filter": photdm.filter.filter_id if photdm.filter is not None else None,
        "zp_mag": None if cal.zp_mag is None else (float(cal.zp_mag.value), str(cal.zp_mag.unit)),
        "zp_flux": None if cal.zp_flux is None else (float(cal.zp_flux.value), str(cal.zp_flux.unit)),
        "mag_sys": cal.mag_sys,
    }


def strict_findings(payload: bytes) -> dict:
    """Reads a product with the strict core and lists what it finds. Changes nothing.

    Args:
        payload (bytes): Issued VOTable.

    Returns:
        dict: ``parses`` and, when it parses, ``columns``, ``time_problems``, ``unit_findings`` (first 60 characters of each message),
            ``conversion_problems`` (per photometry column), ``suggested`` (what the core would
            suggest for the missing values), ``timesys`` and ``photcal`` (per column).
    """
    try:
        volc = read_lightcurve(io.BytesIO(payload), filename="issued.vot", strict=True)
    except Exception as exc:  # a product the strict core cannot read is a finding, not a crash
        return {"parses": False, "error": str(exc)}
    from volightcurve.suggestions import suggestions_for_missing

    photometry = volc.get_mag_colnames() + volc.get_flux_colnames()
    return {
        "parses": True,
        "columns": list(volc.table.colnames),
        "time_problems": volc.time_problems(),
        "unit_findings": {
            key: [text[:60] for text in (*report.errors, *report.notes)]
            for key, report in volc.check_units().items()
            if report.errors or report.notes
        },
        "conversion_problems": {name: volc.conversion_problems(name) for name in photometry},
        "suggested": suggestions_for_missing(volc),
        "timesys": {
            "timescale": volc.timesys.timescale,
            "refposition": volc.timesys.refposition,
            "timeorigin": volc.timesys.timeorigin,
        },
        "photcal": {name: _photcal_summary(dm) for name, dm in volc.photdms.items()},
    }


def _veb_raw() -> bytes:
    """Returns the recorded Gaia DR3 VEB product as the server sends it."""
    return (_DATA / "gaia_dr3_veb_g_raw.xml").read_bytes()


def _ztf_issued() -> bytes:
    """Returns the recorded ZTF product as Discovery issued it."""
    return (_DATA / "ztf_oid_1772216100034775_zr_orig.xml").read_bytes()


def _ogle_issued() -> bytes:
    """Returns the recorded OGLE product (OGLE-LMC-RRLYR-13820) as Discovery issued it."""
    return (_DATA / "ogle_lmc_rrlyr_13820_issued.vot").read_bytes()


def _tess_issued() -> bytes:
    """Returns the recorded TESS-SPOC product (TIC 455790537, sector 17) as Discovery issued it."""
    return (_DATA / "tess_spoc_sector17_orig.vot").read_bytes()


def _gaia_aip_issued() -> bytes:
    """Builds the Gaia@AIP G-band product from the bundled epoch-photometry sample."""
    from astropy.table import Table

    from lc_discovery.providers.gaia_dr3_aip.epoch_photometry import cache_dict_from_tap_table
    from lc_discovery.providers.gaia_dr3_aip.fetch_metadata import votable_from_cached_epoch

    table = Table.read(_DATA / "gaia_aip.vot", format="votable")
    epoch = cache_dict_from_tap_table(table)[10655814178816]
    return votable_from_cached_epoch(epoch, band_code="G")


def _gaia_ari_issued() -> bytes:
    """Enriches the bundled Gaia@ARI time-series download, first table (G band)."""
    from lc_discovery.providers.gaia_dr3_ari.fetch_metadata import enrich_votable as enrich_ari

    return enrich_ari((_DATA / "gaia_ari.vot").read_bytes(), table_id=0)


def _ps1_issued() -> bytes:
    """Returns the recorded Pan-STARRS1 product (PS1 165213463504091232, i) as Discovery issued it."""
    return (_DATA / "panstarrs1_dr2_issued.xml").read_bytes()


def _upjs_issued() -> bytes:
    """Enriches the recorded UPJS time-series product as the TAP service sends it (V band)."""
    from lc_discovery.providers.upjs_ts.fetch_metadata import enrich_votable as enrich_upjs

    return enrich_upjs((_DATA / "upjs_ts_V_raw.xml").read_bytes())


def _personal_issued() -> bytes:
    """Enriches the recorded personal-collections product as the TAP service sends it (V band)."""
    from lc_discovery.providers.personal_ts.fetch_metadata import enrich_votable as enrich_personal

    return enrich_personal((_DATA / "personal_ts_V_raw.xml").read_bytes())


# The findings of 2026-10-23. A change here is a change of what a provider issues.
BASELINE: dict[str, dict] = {
    "gaia_dr3_veb, as the server sends it": {
        "parses": True,
        "columns": ["obs_time", "phot", "flux_error"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {
            "phot": [
                "Zero-point magnitude "
                "(zp_mag) is missing, "
                "so magnitude and flux "
                "cannot be converted.",
                "Flux column unit (1 / " "s) is not equivalent " "to the zero-point flux " "unit (Jy).",
            ]
        },
        "suggested": {"calibration": {"phot": {"zp_mag": 0.0, "zp_mag_unit": "mag"}}},
        "timesys": {"timescale": "TCB", "refposition": "BARYCENTER", "timeorigin": 2455197.5},
        "photcal": {
            "phot": {
                "filter": "GAIA/GAIA3.Gbp",
                "zp_mag": None,
                "zp_flux": (3552.01, "Jy"),
                "mag_sys": "Vega",
            }
        },
    },
    "gaia_dr3_veb, after enrich_votable": {
        "parses": True,
        "columns": ["obs_time", "phot", "flux_error"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"phot": []},
        "suggested": {},
        "timesys": {"timescale": "TCB", "refposition": "BARYCENTER", "timeorigin": 2455197.5},
        "photcal": {
            "phot": {
                "filter": "GAIA/GAIA3.Gbp",
                "zp_mag": (25.3385, "mag"),
                "zp_flux": (1.0, "1 / s"),
                "mag_sys": "Vega",
            },
            "flux_error": {
                "filter": "GAIA/GAIA3.Gbp",
                "zp_mag": (25.3385, "mag"),
                "zp_flux": (1.0, "1 / s"),
                "mag_sys": "Vega",
            },
        },
    },
    "ztf, as issued": {
        "parses": True,
        "columns": [
            "hjd",
            "mag",
            "mag_err",
            "oid",
            "catflag",
            "chi",
            "sharp",
            "field",
            "ccdid",
            "qid",
            "limitmag",
        ],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"mag": []},
        "suggested": {},
        "timesys": {"timescale": "UTC", "refposition": "HELIOCENTER", "timeorigin": 0.0},
        "photcal": {
            "mag_err": {
                "filter": "Palomar/ZTF.r",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3631.0, "Jy"),
                "mag_sys": "AB",
            },
            "mag": {
                "filter": "Palomar/ZTF.r",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3631.0, "Jy"),
                "mag_sys": "AB",
            },
        },
    },
    "tess, as issued": {
        "parses": True,
        "columns": [
            "time",
            "pdcsap_flux",
            "pdcsap_flux_err",
            "sap_flux",
            "sap_flux_err",
            "sap_bkg",
            "sap_bkg_err",
        ],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"pdcsap_flux": [], "sap_flux": []},
        "suggested": {},
        "timesys": {"timescale": "TDB", "refposition": "BARYCENTER", "timeorigin": 2400000.5},
        "photcal": {
            "pdcsap_flux_err": {
                "filter": "TESS/TESS.Red",
                "zp_mag": (20.44, "mag"),
                "zp_flux": (1.0, "ct / s"),
                "mag_sys": "Vega",
            },
            "sap_flux_err": {
                "filter": "TESS/TESS.Red",
                "zp_mag": (20.44, "mag"),
                "zp_flux": (1.0, "ct / s"),
                "mag_sys": "Vega",
            },
            "sap_bkg_err": {"filter": "TESS/TESS.Red", "zp_mag": None, "zp_flux": None, "mag_sys": "Vega"},
            "pdcsap_flux": {
                "filter": "TESS/TESS.Red",
                "zp_mag": (20.44, "mag"),
                "zp_flux": (1.0, "ct / s"),
                "mag_sys": "Vega",
            },
            "sap_flux": {
                "filter": "TESS/TESS.Red",
                "zp_mag": (20.44, "mag"),
                "zp_flux": (1.0, "ct / s"),
                "mag_sys": "Vega",
            },
            "sap_bkg": {"filter": "TESS/TESS.Red", "zp_mag": None, "zp_flux": None, "mag_sys": "Vega"},
        },
    },
    "ogle_ocvs, as issued": {
        "parses": True,
        "columns": ["obs_time", "phot", "mag_err", "ogle_phase"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"phot": []},
        "suggested": {},
        "timesys": {"timescale": "UTC", "refposition": "HELIOCENTER", "timeorigin": 2400000.5},
        "photcal": {
            "phot": {
                "filter": "Generic/Bessell.I",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (2415.6497711876, "Jy"),
                "mag_sys": "Vega",
            },
            "mag_err": {
                "filter": "Generic/Bessell.I",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (2415.6497711876, "Jy"),
                "mag_sys": "Vega",
            },
        },
    },
    "gaia_dr3_aip, built from the epoch sample": {
        "parses": True,
        "columns": ["transit_time", "transit_mag", "mag_error", "transit_flux_over", "transit_n_obs"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"transit_mag": []},
        "suggested": {},
        "timesys": {"timescale": "TCB", "refposition": "BARYCENTER", "timeorigin": 2455197.5},
        "photcal": {
            "transit_mag": {
                "filter": "GAIA/GAIA3.G",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3228.75, "Jy"),
                "mag_sys": "Vega",
            },
            "mag_error": {
                "filter": "GAIA/GAIA3.G",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3228.75, "Jy"),
                "mag_sys": "Vega",
            },
        },
    },
    "gaia_dr3_ari, after enrich_votable": {
        "parses": True,
        "columns": [
            "solution_id",
            "transit_id",
            "time",
            "mag",
            "flux",
            "flux_error",
            "flux_over_error",
            "rejected_by_photometry",
            "rejected_by_variability",
            "other_flags",
            "p1",
            "p2",
        ],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"mag": [], "flux": []},
        "suggested": {},
        "timesys": {"timescale": "TCB", "refposition": "barycenter", "timeorigin": 2455197.5},
        "photcal": {
            "mag": {
                "filter": "GAIADR3.G",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3296.2, "Jy"),
                "mag_sys": "Vega",
            },
            "flux": {
                "filter": "GAIADR3.G",
                "zp_mag": (25.6874, "mag"),
                "zp_flux": (1.0, "1 / s"),
                "mag_sys": "Vega",
            },
            "flux_error": {
                "filter": "GAIADR3.G",
                "zp_mag": (25.6874, "mag"),
                "zp_flux": (1.0, "1 / s"),
                "mag_sys": "Vega",
            },
        },
    },
    "panstarrs1_dr2, as issued": {
        "parses": True,
        "columns": ["obs_time", "psf_flux", "psf_flux_error"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"psf_flux": []},
        "suggested": {},
        "timesys": {"timescale": "tai", "refposition": "TOPOCENTER", "timeorigin": 2400000.5},
        "photcal": {
            "psf_flux_error": {
                "filter": "PAN-STARRS/PS1.i",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3631.0, "Jy"),
                "mag_sys": "AB",
            },
            "psf_flux": {
                "filter": "PAN-STARRS/PS1.i",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3631.0, "Jy"),
                "mag_sys": "AB",
            },
        },
    },
    "upjs_ts, after enrich_votable": {
        "parses": True,
        "columns": ["obs_time", "phot", "mag_err", "origin_image", "airmass", "comp_stars"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"phot": []},
        "suggested": {},
        "timesys": {"timescale": "TCB", "refposition": "BARYCENTER", "timeorigin": 2400000.5},
        "photcal": {
            "phot": {
                "filter": "Generic/Bessell.V",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3630.2172842325, "Jy"),
                "mag_sys": "Vega",
            },
            "mag_err": {
                "filter": "Generic/Bessell.V",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3630.2172842325, "Jy"),
                "mag_sys": "Vega",
            },
        },
    },
    "personal_ts, after enrich_votable": {
        "parses": True,
        "columns": ["obs_time", "phot", "mag_err", "facility", "note"],
        "time_problems": [],
        "unit_findings": {},
        "conversion_problems": {"phot": []},
        "suggested": {},
        "timesys": {"timescale": "UTC", "refposition": "HELIOCENTER", "timeorigin": 2400000.5},
        "photcal": {
            "phot": {
                "filter": "Generic/Bessell.V",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3630.2172842325, "Jy"),
                "mag_sys": "Vega",
            },
            "mag_err": {
                "filter": "Generic/Bessell.V",
                "zp_mag": (0.0, "mag"),
                "zp_flux": (3630.2172842325, "Jy"),
                "mag_sys": "Vega",
            },
        },
    },
}


def _current() -> dict[str, dict]:
    """Collects the findings for every case."""
    return {
        "gaia_dr3_veb, as the server sends it": strict_findings(_veb_raw()),
        "gaia_dr3_veb, after enrich_votable": strict_findings(enrich_votable(_veb_raw())),
        "ztf, as issued": strict_findings(_ztf_issued()),
        "tess, as issued": strict_findings(_tess_issued()),
        "ogle_ocvs, as issued": strict_findings(_ogle_issued()),
        "gaia_dr3_aip, built from the epoch sample": strict_findings(_gaia_aip_issued()),
        "gaia_dr3_ari, after enrich_votable": strict_findings(_gaia_ari_issued()),
        "panstarrs1_dr2, as issued": strict_findings(_ps1_issued()),
        "upjs_ts, after enrich_votable": strict_findings(_upjs_issued()),
        "personal_ts, after enrich_votable": strict_findings(_personal_issued()),
    }


def test_every_case_reports_findings_without_crashing():
    """Each issued product yields a findings dict; a product that does not parse says why."""
    for name, found in _current().items():
        assert "parses" in found, name
        if not found["parses"]:
            assert found["error"], name


def test_baseline_is_unchanged():
    """The recorded findings still hold. Update ``BASELINE`` deliberately when a provider changes."""
    assert _current() == BASELINE
