"""Gaia DR3 debug provider constants and synthetic VOTable emission helpers.

Used only by ``lc_providers.gaia_debug`` for Lightcurve Discovery UI development.
Not part of ``utils.mission_config`` (that package is for legacy TESS/ASAS-SN pages).
"""

from __future__ import annotations

import logging

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
from skvo_veb.utils.my_tools import sanitize_filename

logger = logging.getLogger(__name__)

PROVIDER_ID = "gaia"

GAIA_TIMESCALE = "TCB"
GAIA_REFPOSITION = "BARYCENTER"
GAIA_COOSYS_ID = "system"
GAIA_COOSYS_SYSTEM = "ICRS"
GAIA_COOSYS_EPOCH = 2016.0
GAIA_PIPELINE = "Gaia DR3 (debug catalogue)"
GAIA_SURVEY = "Gaia DR3"

FACILITY_NAME = "Gaia"
INSTRUMENT_NAME = "Gaia"

GAIA_G_BAND = "G"
GAIA_BP_BAND = "BP"
GAIA_RP_BAND = "RP"
GAIA_MOCK_BANDS = (GAIA_G_BAND, GAIA_BP_BAND, GAIA_RP_BAND)

GAIA_G_FILTER_IDENTIFIER = "Gaia/GAIA3.G"
GAIA_BP_FILTER_IDENTIFIER = "Gaia/GAIA3.BP"
GAIA_RP_FILTER_IDENTIFIER = "Gaia/GAIA3.RP"
GAIA_G_FILTER_NAME = "Gaia G"
GAIA_BP_FILTER_NAME = "Gaia BP"
GAIA_RP_FILTER_NAME = "Gaia RP"
GAIA_G_MAG_SYS = "Vega"
GAIA_G_EFFECTIVE_WAVELENGTH = 673.0e-9
GAIA_BP_EFFECTIVE_WAVELENGTH = 532.0e-9
GAIA_RP_EFFECTIVE_WAVELENGTH = 797.0e-9
GAIA_G_ZP_FLUX = 3.64e-9
GAIA_G_ZP_FLUX_UNIT = "Jy"
GAIA_G_ZP_MAG = 0.0

# Backward-compatible alias for tests that referenced mission_config.gaia.MISSION_ID.
MISSION_ID = PROVIDER_ID
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 1.0

_BAND_METADATA = {
    GAIA_G_BAND: {
        PHOTCAL_KEY_FILTER_IDENTIFIER: GAIA_G_FILTER_IDENTIFIER,
        PHOTCAL_KEY_FILTER_NAME: GAIA_G_FILTER_NAME,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(GAIA_G_EFFECTIVE_WAVELENGTH),
    },
    GAIA_BP_BAND: {
        PHOTCAL_KEY_FILTER_IDENTIFIER: GAIA_BP_FILTER_IDENTIFIER,
        PHOTCAL_KEY_FILTER_NAME: GAIA_BP_FILTER_NAME,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(GAIA_BP_EFFECTIVE_WAVELENGTH),
    },
    GAIA_RP_BAND: {
        PHOTCAL_KEY_FILTER_IDENTIFIER: GAIA_RP_FILTER_IDENTIFIER,
        PHOTCAL_KEY_FILTER_NAME: GAIA_RP_FILTER_NAME,
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: float(GAIA_RP_EFFECTIVE_WAVELENGTH),
    },
}


def normalise_band(band: str) -> str:
    """Validates and normalises a Gaia photometric band code.

    Args:
        band (str): Photometric band identifier (``G``, ``BP``, or ``RP``).

    Returns:
        str: Normalised band code.

    Raises:
        ValueError: If ``band`` is not supported by the debug provider.
    """
    normalised = str(band).strip().upper()
    if normalised not in GAIA_MOCK_BANDS:
        raise ValueError(
            f"Unsupported Gaia band '{band}'. "
            f"Debug provider supports {GAIA_MOCK_BANDS}."
        )
    return normalised


def resolve_photcal(band: str = GAIA_G_BAND) -> dict:
    """Builds serialisable ``metadata['photcal']`` for a Gaia lightcurve band.

    Args:
        band (str): Photometric band identifier.

    Returns:
        dict: PhotCal GROUP fields for VO export and CurveDash bridge metadata.
    """
    normalised = normalise_band(band)
    band_meta = _BAND_METADATA[normalised]
    return {
        PHOTCAL_KEY_FILTER_IDENTIFIER: band_meta[PHOTCAL_KEY_FILTER_IDENTIFIER],
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH: band_meta[PHOTCAL_KEY_EFFECTIVE_WAVELENGTH],
        PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT: "m",
        PHOTCAL_KEY_FILTER_NAME: band_meta[PHOTCAL_KEY_FILTER_NAME],
        PHOTCAL_KEY_ZP_FLUX: GAIA_G_ZP_FLUX,
        PHOTCAL_KEY_ZP_FLUX_UNIT: GAIA_G_ZP_FLUX_UNIT,
        PHOTCAL_KEY_ZP_MAG: GAIA_G_ZP_MAG,
        PHOTCAL_KEY_ZP_MAG_UNIT: "mag",
        PHOTCAL_KEY_MAG_SYS: GAIA_G_MAG_SYS,
    }


def filter_name_for_band(band: str) -> str:
    """Returns the display filter name for a Gaia band code.

    Args:
        band (str): Normalised Gaia band identifier.

    Returns:
        str: Human-readable filter label for catalogue tables.
    """
    return _BAND_METADATA[normalise_band(band)][PHOTCAL_KEY_FILTER_NAME]


def filter_identifier_for_band(band: str) -> str:
    """Returns the IVOA filter identifier for a Gaia band code.

    Args:
        band (str): Normalised Gaia band identifier.

    Returns:
        str: Filter identifier string for catalogue rows and VOTable export.
    """
    return _BAND_METADATA[normalise_band(band)][PHOTCAL_KEY_FILTER_IDENTIFIER]


def format_source_name(source_id: int | str) -> str:
    """Formats a Gaia ``source_id`` for display in catalog tables.

    Args:
        source_id (int or str): Gaia DR3 source identifier.

    Returns:
        str: Human-readable object label.
    """
    return f"Gaia DR3 {source_id}"


def build_fetch_votable_kwargs(
    *,
    source_id: int | str,
    ra_deg: float,
    dec_deg: float,
    band: str = GAIA_G_BAND,
    epoch: float | None = None,
) -> dict:
    """Builds keyword arguments for debug-provider synthetic VOTable emission.

    Args:
        source_id (int or str): Gaia DR3 source identifier.
        ra_deg (float): ICRS right ascension in degrees.
        dec_deg (float): ICRS declination in degrees.
        band (str): Photometric band code.
        epoch (float, optional): Folding epoch as MJD offset under ``JD_TO_MJD``.

    Returns:
        dict: Keyword arguments for ``write_vo_lightcurve``.
    """
    band = normalise_band(band)
    photcal = resolve_photcal(band)
    description = (
        f"Gaia DR3 epoch photometry template for source {source_id}. "
        f"Filter band: {band}. "
        f"``obs_time`` is Modified Julian Date (MJD = JD - {JD_TO_MJD}). "
        "This dataset is generated by the debug provider for UI development."
    )

    kwargs = {
        "table_name": f"GaiaDR3_{sanitize_filename(str(source_id))}_{band}",
        "filter_identifier": photcal[PHOTCAL_KEY_FILTER_IDENTIFIER],
        "filter_name": photcal[PHOTCAL_KEY_FILTER_NAME],
        "refposition": GAIA_REFPOSITION,
        "timescale": GAIA_TIMESCALE,
        "timeorigin": JD_TO_MJD,
        "votable_description": description,
        "table_description": description,
        "creator": GAIA_PIPELINE,
        "zero_point_flux": photcal[PHOTCAL_KEY_ZP_FLUX],
        "zero_point_flux_unit": photcal[PHOTCAL_KEY_ZP_FLUX_UNIT],
        "zero_point_ref_mag": photcal[PHOTCAL_KEY_ZP_MAG],
        "zero_point_ref_mag_unit": photcal[PHOTCAL_KEY_ZP_MAG_UNIT],
        "magnitude_system": photcal[PHOTCAL_KEY_MAG_SYS],
        "effective_wavelength": photcal[PHOTCAL_KEY_EFFECTIVE_WAVELENGTH],
        "effective_wavelength_unit": photcal[PHOTCAL_KEY_EFFECTIVE_WAVELENGTH_UNIT],
        "ra": ra_deg,
        "dec": dec_deg,
        "coosys_id": GAIA_COOSYS_ID,
        "coosys_system": GAIA_COOSYS_SYSTEM,
        "coosys_epoch": GAIA_COOSYS_EPOCH,
        "binary": True,
        "facility_name": FACILITY_NAME,
        "instrument_name": INSTRUMENT_NAME,
    }
    if epoch is not None:
        kwargs["epoch"] = float(epoch)
    return kwargs
