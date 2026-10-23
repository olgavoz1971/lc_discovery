"""Configuration for the TESS MAST/Lightkurve archive lightcurve provider."""

from __future__ import annotations

from lc_discovery.catalog_schema import CatalogExtraColumn
from lc_discovery.epoch import JD_TO_MJD

PROVIDER_ID = "tess"
DISPLAY_NAME = "TESS archive"
EXPORT_PROFILE = PROVIDER_ID

MAX_DISCOVERY_CATALOG_ROWS = 500
# 10 arcmin.
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 10.0 / 60.0

TESS_TIMESCALE = "TDB"
TESS_REFPOSITION = "BARYCENTER"
# Lightkurve TIME is BTJD = JD − 2457000. Issued time is MJD.
TESS_BTJD_OFFSET = 2457000.0
ISSUED_TIMEORIGIN = JD_TO_MJD

FACILITY_NAME = "TESS"
INSTRUMENT_NAME = "TESS"

TESS_FILTER_IDENTIFIER = "TESS/TESS.Red"
TESS_FILTER_NAME = "TESS"

FIELD_SECTOR = "sector"
FIELD_EXP = "exp"
FIELD_AUTHOR = "author"
CATALOG_EXTRA_COLUMNS: tuple[CatalogExtraColumn, ...] = (
    CatalogExtraColumn(field=FIELD_SECTOR, header="Sector", width=56),
    CatalogExtraColumn(field=FIELD_EXP, header="Exp", width=56),
    CatalogExtraColumn(field=FIELD_AUTHOR, header="Author", width=76),
)
TESS_EFFECTIVE_WAVELENGTH_ANGSTROM = 7453.0
TESS_MAG_SYS = "Vega"

# Instrument zero point for SPOC / TESS-SPOC electron s-1 target flux only.
# TESS Instrument Handbook; MIT Transients README restatement.
# https://tess.mit.edu/public/tesstransients/pages/readme.html
SPOC_INSTRUMENT_ZP_AUTHORS = frozenset({"SPOC", "TESS-SPOC"})
TESS_ELECTRON_S_ZERO_POINT_REF_MAG = 20.44
TESS_ELECTRON_S_ZERO_POINT_REF_MAG_UNCERTAINTY = 0.05
TESS_ELECTRON_S_ZERO_POINT_FLUX = 1.0
# VOUnits 1.1 has no electron, and "s-1" is not a valid VOUnits spelling. The flux is
# electrons per second, issued as "count/s": the same text on the columns and on the zero point.
TESS_ELECTRON_S_ZERO_POINT_FLUX_UNIT = "count/s"

TARS_AUTHOR = "TARS"
# Authors whose HLSP files Lightkurve reads with the generic reader.
GENERIC_READER_AUTHORS = frozenset({TARS_AUTHOR})


def btjd_to_mjd(btjd: float) -> float:
    """Converts Lightkurve BTJD to Modified Julian Date.

    Args:
        btjd (float): Barycentric TESS Julian Date (JD − 2457000).

    Returns:
        float: MJD = BTJD + 2457000 − 2400000.5.
    """
    return float(btjd) + TESS_BTJD_OFFSET - ISSUED_TIMEORIGIN


def effective_wavelength_m() -> float:
    """Returns the TESS passband effective wavelength in metres.

    Returns:
        float: 7453 Å expressed in metres.
    """
    return TESS_EFFECTIVE_WAVELENGTH_ANGSTROM * 1e-10


def format_tic_name(tic: int | str) -> str:
    """Returns the catalogue label for a TIC identifier.

    Args:
        tic (int or str): TESS Input Catalogue number.

    Returns:
        str: Label such as ``TIC 159717514``.
    """
    return f"TIC {int(tic)}"


def format_sector_cell(sector: int) -> str:
    """Formats the TESS Sector catalogue cell.

    Args:
        sector (int): TESS sector number.

    Returns:
        str: Sector number only, such as ``16``.
    """
    return str(int(sector))


def format_exp_cell(exptime: float) -> str:
    """Formats the TESS Exp catalogue cell.

    Args:
        exptime (float): MAST cadence in seconds.

    Returns:
        str: Short cadence such as ``120s``.
    """
    return f"{float(exptime):g}s"
