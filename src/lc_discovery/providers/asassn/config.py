"""Configuration for the ASAS-SN Sky Patrol lightcurve provider."""

from __future__ import annotations

from dataclasses import dataclass

from skvo_veb.utils.lc_config import (
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH,
    PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT,
    PHOTCAL_KEY_FILTER_IDENTIFIER,
    PHOTCAL_KEY_FILTER_NAME,
    PHOTCAL_KEY_MAG_SYS,
    PHOTCAL_KEY_ZP_FLUX,
    PHOTCAL_KEY_ZP_FLUX_UNIT,
    PHOTCAL_KEY_ZP_MAG,
    PHOTCAL_KEY_ZP_MAG_UNIT,
)

PROVIDER_ID = "asassn"
DISPLAY_NAME = "ASAS-SN"
EXPORT_PROFILE = PROVIDER_ID
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 10.0

STELLAR_MAIN_CATALOG = "stellar_main"
STELLAR_MAIN_DISCOVERY_COLS: tuple[str, ...] = (
    "asas_sn_id",
    "ra_deg",
    "dec_deg",
    "pstarrs_g_mag",
)

ASASSN_TIMESCALE = "UTC"
ASASSN_REFPOSITION = "HELIOCENTER"
ASASSN_PIPELINE = "ASAS-SN Sky Patrol"
ASASSN_SURVEY = "ASAS-SN"
ASASSN_FLUX_UNIT_MJY = "mJy"

AB_REFERENCE_FLUX_JY = 3631.0

DISCOVERY_CATALOG_PROVIDER_NOTE = (
    "ASAS-SN passband is not confirmed in catalogue metadata; this row is a "
    "candidate filter. The lightcurve may be empty after download."
)

ASASSN_G_FILTER_IDENTIFIER = "SLOAN/SDSS.g"
ASASSN_G_EFFECTIVE_WAVELENGTH_M = 467.2e-9
ASASSN_G_FILTER_NAME = "ASAS-SN g"
ASASSN_G_MAG_SYS = "AB"
ASASSN_G_CALIBRATION_CATALOG = "ATLAS REFCAT2"

ASASSN_V_FILTER_IDENTIFIER = "Generic/Johnson.V"
ASASSN_V_EFFECTIVE_WAVELENGTH_M = 546.8e-9
ASASSN_V_FILTER_NAME = "ASAS-SN V"
ASASSN_V_MAG_SYS = "Vega"
ASASSN_V_CALIBRATION_CATALOG = "APASS"

ASASSN_G_ZP_FLUX = AB_REFERENCE_FLUX_JY
ASASSN_V_ZP_FLUX = 3836.3


@dataclass(frozen=True)
class AsassnBandSpec:
    """One ASAS-SN Sky Patrol photometric band."""

    band_code: str
    filter_name: str
    filter_identifier: str
    calibration_catalog: str
    mag_sys: str
    zp_flux_jy: float
    effective_wavelength_m: float


ASASSN_BANDS: tuple[AsassnBandSpec, ...] = (
    AsassnBandSpec(
        band_code="g",
        filter_name=ASASSN_G_FILTER_NAME,
        filter_identifier=ASASSN_G_FILTER_IDENTIFIER,
        calibration_catalog=ASASSN_G_CALIBRATION_CATALOG,
        mag_sys=ASASSN_G_MAG_SYS,
        zp_flux_jy=ASASSN_G_ZP_FLUX,
        effective_wavelength_m=ASASSN_G_EFFECTIVE_WAVELENGTH_M,
    ),
    AsassnBandSpec(
        band_code="V",
        filter_name=ASASSN_V_FILTER_NAME,
        filter_identifier=ASASSN_V_FILTER_IDENTIFIER,
        calibration_catalog=ASASSN_V_CALIBRATION_CATALOG,
        mag_sys=ASASSN_V_MAG_SYS,
        zp_flux_jy=ASASSN_V_ZP_FLUX,
        effective_wavelength_m=ASASSN_V_EFFECTIVE_WAVELENGTH_M,
    ),
)

_BAND_BY_CODE = {band.band_code: band for band in ASASSN_BANDS}


def band_spec_for_code(band_code: str) -> AsassnBandSpec:
    """Returns band metadata for an ASAS-SN ``phot_filter`` code.

    Args:
        band_code (str): ``g`` or ``V``.

    Returns:
        AsassnBandSpec: Band specification.

    Raises:
        ValueError: When the band code is not supported.
    """
    key = str(band_code).strip()
    if key == "g":
        lookup = "g"
    elif key.upper() == "V":
        lookup = "V"
    else:
        lookup = key
    spec = _BAND_BY_CODE.get(lookup)
    if spec is None:
        supported = ", ".join(sorted(_BAND_BY_CODE))
        raise ValueError(f"Unsupported ASAS-SN band {band_code!r}. Expected: {supported}.")
    return spec


def photcal_dict_for_band(band_code: str) -> dict:
    """Builds serialisable PhotCal metadata for one ASAS-SN band.

    Args:
        band_code (str): ``g`` or ``V``.

    Returns:
        dict: PhotCal GROUP fields aligned with legacy ASAS-SN export.
    """
    band = band_spec_for_code(band_code)
    return {
        PHOTCAL_KEY_FILTER_IDENTIFIER: band.filter_identifier,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(band.effective_wavelength_m),
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT: "m",
        PHOTCAL_KEY_FILTER_NAME: band.filter_name,
        PHOTCAL_KEY_ZP_FLUX: float(band.zp_flux_jy),
        PHOTCAL_KEY_ZP_FLUX_UNIT: "Jy",
        PHOTCAL_KEY_ZP_MAG: 0.0,
        PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
        PHOTCAL_KEY_MAG_SYS: band.mag_sys,
    }
