"""Build VO-standard Pan-STARRS1 DR2 lightcurves from detection TAP tables."""

from __future__ import annotations

import io
import logging

import numpy as np
from astropy import units as u
from astropy.table import Table

from lc_discovery.providers.panstarrs1_dr2 import config
from lc_discovery.providers.panstarrs1_dr2.mean_object_epoch import (
    coosys_epoch_year_from_detection_table,
)
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from volightcurve import VOLightCurve
from volightcurve.lightcurve import write_vo_lightcurve

logger = logging.getLogger(__name__)


def _column_map(table: Table) -> dict[str, str]:
    """Builds lowercase column lookup for TAP detection results.

    Args:
        table (astropy.table.Table): Detection query result.

    Returns:
        dict: Lowercase to actual column names.
    """
    return {str(name).lower(): str(name) for name in table.colnames}


def _require_column(columns: dict[str, str], logical_name: str) -> str:
    """Resolves a required column name case-insensitively.

    Args:
        columns (dict): Column map from ``_column_map``.
        logical_name (str): Expected column name.

    Returns:
        str: Actual column name in the table.

    Raises:
        PipeException: When the column is missing.
    """
    actual = columns.get(logical_name.lower())
    if actual is None:
        raise PipeException(
            f"{config.DISPLAY_NAME}: detection table missing column {logical_name!r}."
        )
    return actual


def build_volightcurve_from_detections(
    detection_table: Table,
    *,
    obj_id: int,
    filter_name: str,
    ra_deg: float,
    dec_deg: float,
    object_name: str = "",
) -> VOLightCurve:
    """Serialises detection epochs into a flux-native ``VOLightCurve``.

    Args:
        detection_table (astropy.table.Table): TAP ``Detection`` rows.
        obj_id (int): Pan-STARRS mean object identifier.
        filter_name (str): PS1 filter ``g``, ``r``, ``i``, ``z``, or ``y``.
        ra_deg (float): ICRS right ascension in degrees (mean object).
        dec_deg (float): ICRS declination in degrees (mean object).
        object_name (str): Optional IAU name for descriptions.

    Returns:
        VOLightCurve: VO-standard lightcurve with flux in Jy and MJD (TAI).

    Raises:
        PipeException: When the table is empty or columns are invalid.
    """
    if detection_table is None or len(detection_table) == 0:
        raise PipeException(
            f"{config.DISPLAY_NAME}: no detection epochs for objID={obj_id} "
            f"filter={filter_name!r} after quality cuts."
        )

    band = config.band_spec_for_filter_name(filter_name)
    columns = _column_map(detection_table)
    coosys_epoch = coosys_epoch_year_from_detection_table(
        detection_table,
        column_map=columns,
    )
    time_col = _require_column(columns, "obsTime")
    flux_col = _require_column(columns, "psfFlux")
    err_col = _require_column(columns, "psfFluxErr")

    obs_mjd = np.asarray(detection_table[time_col], dtype=np.float64)
    flux_jy = np.asarray(detection_table[flux_col], dtype=np.float64)
    flux_err_jy = np.asarray(detection_table[err_col], dtype=np.float64)

    valid = (
        np.isfinite(obs_mjd)
        & np.isfinite(flux_jy)
        & np.isfinite(flux_err_jy)
        & (flux_jy > config.MIN_PSF_FLUX)
    )
    if not np.any(valid):
        raise PipeException(
            f"{config.DISPLAY_NAME}: no finite epochs for objID={obj_id} filter={filter_name!r}."
        )

    obs_mjd = obs_mjd[valid]
    flux_jy = flux_jy[valid]
    flux_err_jy = flux_err_jy[valid]

    obs_time = obs_mjd * u.d
    flux = flux_jy * u.Jy
    flux_err = flux_err_jy * u.Jy

    table = Table()
    table["obs_time"] = obs_time
    table["phot"] = flux
    table["flux_error"] = flux_err

    description = config.detection_lightcurve_description(
        obj_id=obj_id,
        filter_name=band.filter_name,
    )
    wavelength_m = band.effective_wavelength_angstrom * 1e-10

    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        table,
        table_name=sanitize_filename(f"PS1_{obj_id}_{band.filter_name}"),
        filter_identifier=band.filter_identifier,
        filter_name=band.filter_name,
        refposition=config.REFPOSITION,
        timescale=config.TIMESCALE,
        timeorigin=JD_TO_MJD,
        votable_description=description,
        table_description=description,
        creator=config.CREATOR,
        zero_point_flux=config.AB_REFERENCE_FLUX_JY,
        zero_point_flux_unit="Jy",
        zero_point_ref_mag=0.0,
        zero_point_ref_mag_unit="mag",
        magnitude_system=config.MAG_SYSTEM,
        effective_wavelength=wavelength_m,
        effective_wavelength_unit="m",
        ra=float(ra_deg),
        dec=float(dec_deg),
        binary=True,
        coosys_id="system",
        coosys_system=config.COOSYS_SYSTEM,
        coosys_epoch=coosys_epoch,
        publication_id=config.PUBLICATION_BIBCODE,
        facility_name=config.FACILITY_NAME,
        instrument_name=config.INSTRUMENT_NAME,
    )
    buffer.seek(0)
    volc = VOLightCurve(buffer)
    meta = volc.table.meta
    meta["obj_id"] = int(obj_id)
    meta["filter"] = band.filter_name
    meta["mission"] = config.PROVIDER_ID
    meta["facility_name"] = config.FACILITY_NAME
    meta["instrument_name"] = config.INSTRUMENT_NAME
    meta["publication_id"] = config.PUBLICATION_BIBCODE
    meta["bibcode"] = config.PUBLICATION_BIBCODE
    meta["photcal"] = config.photcal_dict_for_band(band)
    meta["coosys_epoch"] = coosys_epoch
    meta["table_description"] = description
    meta["description"] = description
    meta["lightcurve_title"] = description
    logger.info(
        "%s built VOLightCurve obj_id=%s filter=%s coosys_epoch=%.6f n_points=%s",
        config.DISPLAY_NAME,
        obj_id,
        band.filter_name,
        coosys_epoch,
        len(volc),
    )
    return volc
