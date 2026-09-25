"""Build VO-standard lightcurves from prefetched Gaia AIP epoch photometry."""

from __future__ import annotations

import io
import logging

import numpy as np
from astropy import units as u
from astropy.table import Table

from lc_discovery.providers.gaia_dr3_aip import config
from lc_discovery.shared.photcal_error_link import (
    share_photcal_with_unlinked_errors,
)
from lc_discovery.providers.gaia_dr3_aip.epoch_photometry import extract_band_lightcurve
from lc_discovery.providers.gaia_dr3_aip.prefetch_store import load_epoch_photometry
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from volightcurve import VOLightCurve
from volightcurve.lightcurve import write_vo_lightcurve

logger = logging.getLogger(__name__)


def _build_epoch_table(
    *,
    time_mjd: np.ndarray,
    mag: np.ndarray,
    mag_err: np.ndarray,
) -> Table:
    """Creates an Astropy table for ``write_vo_lightcurve`` emission.

    Args:
        time_mjd (numpy.ndarray): Observation times in MJD.
        mag (numpy.ndarray): Vega magnitudes.
        mag_err (numpy.ndarray): Magnitude uncertainties in mag.

    Returns:
        astropy.table.Table: Table with ``obs_time``, ``mag``, and ``mag_err``.
    """
    table = Table()
    table["obs_time"] = time_mjd * u.d
    table["mag"] = mag * u.mag
    table["mag_err"] = mag_err * u.mag
    return table


def build_volightcurve_from_prefetch(
    *,
    source_id: int | str,
    band_code: str,
    ra_deg: float,
    dec_deg: float,
    filter_name: str,
) -> VOLightCurve:
    """Builds one Gaia passband ``VOLightCurve`` from prefetched epoch photometry.

    Args:
        source_id (int or str): Gaia DR3 source identifier.
        band_code (str): Gaia passband code (``G``, ``BP``, or ``RP``).
        ra_deg (float): ICRS right ascension in degrees.
        dec_deg (float): ICRS declination in degrees.
        filter_name (str): Human-readable filter label from the catalogue row.

    Returns:
        VOLightCurve: VO-standard magnitude-native lightcurve.

    Raises:
        PipeException: When prefetch data are missing or contain no valid epochs.
    """
    band = config.band_spec_for_code(band_code)
    epoch_payload = load_epoch_photometry(source_id)
    time_mjd, mag, mag_err = extract_band_lightcurve(epoch_payload, band_code=band.band_code)
    if len(time_mjd) == 0:
        raise PipeException(
            f"{config.DISPLAY_NAME}: source_id {source_id} has no valid epochs "
            f"in band {band.band_code}."
        )

    table = _build_epoch_table(time_mjd=time_mjd, mag=mag, mag_err=mag_err)
    period_days = epoch_payload.get("period_days")
    object_class = epoch_payload.get("object_class")
    description = (
        f"Gaia DR3 epoch photometry for source {source_id} "
        f"in {filter_name} from Gaia@AIP TAP ({config.EPOCH_PHOTOMETRY_TABLE})."
    )
    if object_class:
        description = f"{description} Class: {object_class}."
    buffer = io.BytesIO()
    period_param = None
    if period_days is not None:
        try:
            period_param = float(period_days)
        except (TypeError, ValueError):
            period_param = None
    write_vo_lightcurve(
        buffer,
        table,
        table_name=f"GaiaAIP_{sanitize_filename(str(source_id))}_{band.band_code}",
        filter_identifier=band.filter_identifier,
        filter_name=filter_name,
        refposition="BARYCENTER",
        timescale="TCB",
        timeorigin=JD_TO_MJD,
        votable_description=description,
        table_description=description,
        creator=config.DISPLAY_NAME,
        zero_point_flux=band.zp_flux_jy,
        zero_point_flux_unit="Jy",
        zero_point_ref_mag=config.GAIA_AIP_ZERO_POINT_REFERENCE_MAGNITUDE,
        zero_point_ref_mag_unit="mag",
        magnitude_system=config.GAIA_AIP_MAGNITUDE_SYSTEM,
        effective_wavelength=band.effective_wavelength_angstrom * 1e-10,
        effective_wavelength_unit="m",
        ra=float(ra_deg),
        dec=float(dec_deg),
        coosys_id="system",
        coosys_system="ICRS",
        coosys_epoch=2016.0,
        period=period_param,
        binary=False,
        facility_name=config.FACILITY_NAME,
        instrument_name=config.INSTRUMENT_NAME,
    )
    buffer.seek(0)
    volc = VOLightCurve(buffer)
    title = f"Gaia DR3 {source_id} in {filter_name} filter"
    volc.table.meta["name"] = title
    volc.table.meta["lightcurve_title"] = title
    volc.table.meta["facility_name"] = config.FACILITY_NAME
    volc.table.meta["instrument_name"] = config.INSTRUMENT_NAME
    if period_param is not None:
        volc.table.meta["period"] = period_param
    if object_class:
        volc.table.meta["object_class"] = str(object_class).strip()
    logger.debug(
        "%s built VOLightCurve source_id=%s band=%s n_points=%s",
        config.DISPLAY_NAME,
        source_id,
        band.band_code,
        len(volc),
    )
    share_photcal_with_unlinked_errors(volc)
    return volc
