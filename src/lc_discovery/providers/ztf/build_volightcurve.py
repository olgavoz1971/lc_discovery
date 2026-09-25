"""Build VO-standard ZTF lightcurves from ``ztfquery`` epoch tables."""

from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd
from astropy import units as u
from astropy.table import Table

from lc_discovery.providers.ztf import config
from skvo_veb.utils.lc_config import JD_TO_MJD
from skvo_veb.utils.my_tools import PipeException, sanitize_filename
from volightcurve import VOLightCurve
from volightcurve.lightcurve import assign_photometry_column_semantics, write_vo_lightcurve

logger = logging.getLogger(__name__)


def _select_time_column(frame: pd.DataFrame) -> tuple[str, float]:
    """Selects ``hjd`` or ``hmjd`` and the matching VO ``timeorigin``.

    Args:
        frame (pandas.DataFrame): Raw epoch table.

    Returns:
        tuple[str, float]: Column name and ``TIMESYS/@timeorigin``.

    Raises:
        PipeException: When no supported time column exists.
    """
    if "hjd" in frame.columns:
        return "hjd", 0.0
    if "hmjd" in frame.columns:
        return "hmjd", JD_TO_MJD
    raise PipeException(
        f"{config.DISPLAY_NAME}: epoch table must contain hjd or hmjd time column."
    )


def build_volightcurve_from_epochs(
    frame: pd.DataFrame,
    *,
    oid: int | str,
    filtercode: str,
    ra_deg: float | None = None,
    dec_deg: float | None = None,
) -> VOLightCurve:
    """Serialises ZTF epochs into a magnitude-native ``VOLightCurve``.

    Args:
        frame (pandas.DataFrame): Columns ``mag``, ``magerr``, and ``hjd`` or ``hmjd``.
        oid (int or str): ZTF OID written into epoch ``label`` values.
        filtercode (str): IRSA filter code for PhotCal metadata.
        ra_deg (float, optional): ICRS right ascension in degrees.
        dec_deg (float, optional): ICRS declination in degrees.

    Returns:
        VOLightCurve: VO-standard lightcurve.

    Raises:
        PipeException: When required columns are missing or empty.
    """
    if frame is None or len(frame) == 0:
        raise PipeException(f"{config.DISPLAY_NAME}: empty epoch table for oid={oid}.")

    for col in ("mag", "magerr"):
        if col not in frame.columns:
            raise PipeException(
                f"{config.DISPLAY_NAME}: epoch table missing required column {col!r}."
            )

    time_col, timeorigin = _select_time_column(frame)
    band = config.band_spec_for_filtercode(filtercode)
    oid_int = int(oid)
    oid_label = str(oid_int)

    obs_time = np.asarray(frame[time_col], dtype=np.float64)
    mag = np.asarray(frame["mag"], dtype=np.float64)
    magerr = np.asarray(frame["magerr"], dtype=np.float64)

    valid = np.isfinite(obs_time) & np.isfinite(mag) & np.isfinite(magerr)
    if not np.any(valid):
        raise PipeException(
            f"{config.DISPLAY_NAME}: no finite epochs for oid={oid_int}."
        )
    obs_time = obs_time[valid]
    mag = mag[valid]
    magerr = magerr[valid]

    table = Table()
    table["obs_time"] = obs_time * u.d
    table["mag"] = mag * u.mag
    table["mag_err"] = magerr * u.mag
    table["label"] = [oid_label] * len(mag)

    assign_photometry_column_semantics(table, phot_col="mag", error_col="mag_err", force_magnitude=True)

    wavelength_m = band.effective_wavelength_angstrom * 1e-10
    description = (
        f"ZTF DR24 lightcurve OID {oid_int} in {band.filter_name} "
        f"(filtercode={band.filtercode!r})."
    )
    buffer = io.BytesIO()
    write_vo_lightcurve(
        buffer,
        table,
        table_name=f"ZTF_{sanitize_filename(str(oid_int))}_{band.filtercode}",
        filter_identifier=band.filter_identifier,
        filter_name=band.filter_name,
        refposition=config.ZTF_REFPOSITION,
        timescale=config.ZTF_TIMESCALE,
        timeorigin=timeorigin,
        votable_description=description,
        table_description=description,
        creator=config.ZTF_PIPELINE,
        zero_point_flux=band.zp_flux_jy,
        zero_point_flux_unit="Jy",
        zero_point_ref_mag=0.0,
        zero_point_ref_mag_unit="mag",
        magnitude_system=band.mag_sys,
        effective_wavelength=wavelength_m,
        effective_wavelength_unit="m",
        ra=float(ra_deg) if ra_deg is not None else None,
        dec=float(dec_deg) if dec_deg is not None else None,
        binary=True,
        coosys_id="system",
        coosys_system="ICRS",
        publication_id=config.PUBLICATION_BIBCODE,
        facility_name=config.FACILITY_NAME,
        instrument_name=config.INSTRUMENT_NAME,
    )
    buffer.seek(0)
    volc = VOLightCurve(buffer)
    meta = volc.table.meta
    meta["ztf_oid"] = oid_int
    meta["filtercode"] = band.filtercode
    meta["mission"] = config.PROVIDER_ID
    meta["facility_name"] = config.FACILITY_NAME
    meta["instrument_name"] = config.INSTRUMENT_NAME
    meta["publication_id"] = config.PUBLICATION_BIBCODE
    meta["bibcode"] = config.PUBLICATION_BIBCODE
    meta["photcal"] = config.photcal_dict_for_filtercode(band.filtercode)
    logger.info(
        "%s built VOLightCurve oid=%s filter=%s n_points=%s time_col=%s",
        config.DISPLAY_NAME,
        oid_int,
        band.filtercode,
        len(volc),
        time_col,
    )
    return volc
