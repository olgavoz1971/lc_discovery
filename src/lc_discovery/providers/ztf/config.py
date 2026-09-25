"""Configuration for the ZTF DR24 IRSA lightcurve provider."""

from __future__ import annotations

from dataclasses import dataclass

from skvo_veb.utils.lc_config import (
    JD_TO_MJD,
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
from lc_discovery.discovery_fetch_context import (
    effective_lookup_association_arcsec as _shared_effective_lookup_association_arcsec,
)

PROVIDER_ID = "ztf_dr24"
DISPLAY_NAME = "ZTF DR24"
EXPORT_PROFILE = PROVIDER_ID
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 1.0

OBJECTS_TABLE = "ztf_objects_dr24"
ZTF_SURVEY = "ZTF"
ZTF_PIPELINE = "ZTF IRSA Light Curves"

ZTF_TIMESCALE = "UTC"
ZTF_REFPOSITION = "HELIOCENTER"

FACILITY_NAME = "Palomar"
INSTRUMENT_NAME = "ZTF"
PUBLICATION_BIBCODE = "2019PASP..131a8003M"

AB_REFERENCE_FLUX_JY = 3631.0

LOOKUP_ASSOCIATION_MAX_ARCSEC = 5.0

FETCH_QUALITY_RAW = "raw"
FETCH_QUALITY_BAD_CATFLAGS = "bad_catflags"
ZTF_BAD_CATFLAGS_MASK = 32768

DISCOVERY_TAP_COLUMNS: tuple[str, ...] = (
    "oid",
    "ra",
    "dec",
    "filtercode",
    "nobsrel",
    "meanmag",
)


@dataclass(frozen=True)
class ZtfBandSpec:
    """One ZTF ``filtercode`` band."""

    filtercode: str
    filter_name: str
    filter_identifier: str
    effective_wavelength_angstrom: float
    mag_sys: str = "AB"
    zp_flux_jy: float = AB_REFERENCE_FLUX_JY


ZTF_BANDS: tuple[ZtfBandSpec, ...] = (
    ZtfBandSpec(
        filtercode="zg",
        filter_name="ZTF g",
        filter_identifier="Palomar/ZTF.g",
        effective_wavelength_angstrom=4746.48,
    ),
    ZtfBandSpec(
        filtercode="zr",
        filter_name="ZTF r",
        filter_identifier="Palomar/ZTF.r",
        effective_wavelength_angstrom=6366.38,
    ),
    ZtfBandSpec(
        filtercode="zi",
        filter_name="ZTF i",
        filter_identifier="Palomar/ZTF.i",
        effective_wavelength_angstrom=7829.03,
    ),
)

_BAND_BY_CODE = {band.filtercode: band for band in ZTF_BANDS}


def band_spec_for_filtercode(filtercode: str) -> ZtfBandSpec:
    """Returns band metadata for a ZTF ``filtercode``.

    Args:
        filtercode (str): IRSA filter code (``zg``, ``zr``, ``zi``).

    Returns:
        ZtfBandSpec: Band specification.

    Raises:
        ValueError: When the filter code is not supported.
    """
    key = str(filtercode or "").strip()
    spec = _BAND_BY_CODE.get(key)
    if spec is None:
        supported = ", ".join(sorted(_BAND_BY_CODE))
        raise ValueError(f"Unsupported ZTF filtercode {filtercode!r}. Expected: {supported}.")
    return spec


def photcal_dict_for_filtercode(filtercode: str) -> dict:
    """Builds serialisable PhotCal metadata for one ZTF band.

    Args:
        filtercode (str): IRSA ``filtercode`` value.

    Returns:
        dict: PhotCal GROUP fields for export.
    """
    band = band_spec_for_filtercode(filtercode)
    wavelength_m = band.effective_wavelength_angstrom * 1e-10
    return {
        PHOTCAL_KEY_FILTER_IDENTIFIER: band.filter_identifier,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(wavelength_m),
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT: "m",
        PHOTCAL_KEY_FILTER_NAME: band.filter_name,
        PHOTCAL_KEY_ZP_FLUX: float(band.zp_flux_jy),
        PHOTCAL_KEY_ZP_FLUX_UNIT: "Jy",
        PHOTCAL_KEY_ZP_MAG: 0.0,
        PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
        PHOTCAL_KEY_MAG_SYS: band.mag_sys,
    }


def effective_lookup_association_arcsec(radius_arcsec: float | None) -> float:
    """Computes τ_eff = min(radius, provider lookup association cap).

    Args:
        radius_arcsec (float, optional): Discovery cone radius in arcseconds.

    Returns:
        float: Association threshold in arcseconds.
    """
    return _shared_effective_lookup_association_arcsec(
        radius_arcsec,
        max_arcsec=LOOKUP_ASSOCIATION_MAX_ARCSEC,
    )


def format_ztf_oid_name(oid: int | str) -> str:
    """Returns the standard catalogue label for a ZTF OID.

    Args:
        oid (int or str): ZTF object/lightcurve identifier.

    Returns:
        str: Label such as ``ZTF OID 1234567890``.
    """
    return f"ZTF OID {int(oid)}"
