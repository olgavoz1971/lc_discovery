"""Build VO-standard ASAS-SN lightcurves from Sky Patrol photometry."""

from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.table import Table

from lc_discovery.providers.asassn import config
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from volightcurve import VOLightCurve
from volightcurve.lightcurve import write_vo_lightcurve

logger = logging.getLogger(__name__)


def _optional_camera_labels(band_table: pd.DataFrame) -> np.ndarray | None:
    """Maps Sky Patrol ``camera`` values to VOTable ``label`` strings when available.

    Args:
        band_table (pandas.DataFrame): Band slice from ``slice_band_photometry``.

    Returns:
        numpy.ndarray or None: Per-epoch label strings, or ``None`` when ``camera``
        is absent or entirely null/empty (photometry is still built without labels).
    """
    if "camera" not in band_table.columns:
        return None
    series = band_table["camera"]
    if series.isna().all():
        logger.debug(
            "%s: camera column present but all null; omitting epoch labels.",
            config.DISPLAY_NAME,
        )
        return None
    labels: list[str] = []
    any_non_empty = False
    for value in series:
        if pd.isna(value):
            labels.append("")
            continue
        text = str(value).strip()
        if text:
            any_non_empty = True
        labels.append(text)
    if not any_non_empty:
        logger.debug(
            "%s: camera column has no usable values; omitting epoch labels.",
            config.DISPLAY_NAME,
        )
        return None
    return np.asarray(labels, dtype=str)


def build_volightcurve_from_band_table(
    band_table: pd.DataFrame,
    *,
    asas_sn_id: int | str,
    band_code: str,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
    epoch_jd: float | None = None,
    period_days: float | None = None,
) -> VOLightCurve:
    """Serialises one band slice into a flux-native ``VOLightCurve``.

    Args:
        band_table (pandas.DataFrame): Columns ``jd``, ``flux``, ``flux_err`` (mJy);
            optional ``camera`` (Sky Patrol CCD/instrument code per epoch) becomes
            VOTable ``label`` when present and non-empty.
        asas_sn_id (int or str): Sky Patrol source identifier.
        band_code (str): ``g`` or ``V``.
        ra_deg (float, optional): ICRS right ascension in degrees.
        dec_deg (float, optional): ICRS declination in degrees.
        epoch_jd (float, optional): Folding epoch in Julian Date.
        period_days (float, optional): Variability period in days.

    Returns:
        VOLightCurve: VO-standard lightcurve with Heliocentric Julian times.

    Raises:
        PipeException: When the input table is empty or invalid.
    """
    if band_table is None or len(band_table) == 0:
        raise PipeException(f"{config.DISPLAY_NAME}: empty band table for build.")

    band = config.band_spec_for_code(band_code)
    jd = np.asarray(band_table["jd"], dtype=np.float64)
    flux_mjy = np.asarray(band_table["flux"], dtype=np.float64)
    flux_err_mjy = np.asarray(band_table["flux_err"], dtype=np.float64)
    camera_labels = _optional_camera_labels(band_table)

    obs_time_mjd = (jd - JD_TO_MJD) * u.d
    flux_jy = (flux_mjy * 1e-3) * u.Jy
    flux_err_jy = (flux_err_mjy * 1e-3) * u.Jy

    table = Table()
    table["obs_time"] = obs_time_mjd
    table["phot"] = flux_jy
    table["flux_error"] = flux_err_jy
    if camera_labels is not None:
        table["label"] = camera_labels

    sid = int(asas_sn_id)
    description = (
        f"ASAS-SN Sky Patrol lightcurve for asas_sn_id {sid} "
        f"in {band.filter_name} (phot_filter={band.band_code!r})."
    )
    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        table,
        table_name=f"ASASSN_{sanitize_filename(str(sid))}_{band.band_code}",
        filter_identifier=band.filter_identifier,
        filter_name=band.filter_name,
        refposition=config.ASASSN_REFPOSITION,
        timescale=config.ASASSN_TIMESCALE,
        timeorigin=JD_TO_MJD,
        votable_description=description,
        table_description=description,
        creator=config.ASASSN_PIPELINE,
        zero_point_flux=band.zp_flux_jy,
        zero_point_flux_unit="Jy",
        zero_point_ref_mag=0.0,
        zero_point_ref_mag_unit="mag",
        magnitude_system=band.mag_sys,
        effective_wavelength=band.effective_wavelength_m,
        effective_wavelength_unit="m",
        ra=float(ra_deg) if ra_deg is not None else None,
        dec=float(dec_deg) if dec_deg is not None else None,
        period=period_days,
        epoch=epoch_jd,
        binary=True,
        coosys_id="system",
        coosys_system="ICRS",
    )
    buffer.seek(0)
    volc = VOLightCurve(buffer)
    meta = volc.table.meta
    meta["asas_sn_id"] = sid
    meta["band"] = band.band_code
    meta["calibration_catalog"] = band.calibration_catalog
    meta["mission"] = config.PROVIDER_ID
    if period_days is not None:
        meta["period"] = float(period_days)
    if epoch_jd is not None:
        meta["epoch"] = float(epoch_jd)
    logger.info(
        "%s built VOLightCurve asas_sn_id=%s band=%s n_points=%s",
        config.DISPLAY_NAME,
        sid,
        band.band_code,
        len(volc),
    )
    return volc
