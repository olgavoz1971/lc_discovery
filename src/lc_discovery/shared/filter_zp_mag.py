"""Set a missing magnitude zero point from a provider's filter-identifier table."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from volightcurve import PhotCal, VOLightCurve

logger = logging.getLogger(__name__)


def assign_magnitude_zero_point(
    volc: VOLightCurve,
    *,
    display_name: str,
    zp_mag_by_filter_identifier: Mapping[str, float],
    zp_mag_unit: str,
) -> None:
    """Sets ``zp_mag`` from ``photDM:PhotometryFilter.identifier``.

    Applies only to magnitude columns of this product whose identifier is in
    the provider table and which have no magnitude zero point. The flux zero
    point is not changed. An identifier that is not listed is left unchanged.

    Args:
        volc (VOLightCurve): Parsed product of one provider.
        display_name (str): Provider label used in the log.
        zp_mag_by_filter_identifier (Mapping[str, float]): Magnitude zero
            point in ``zp_mag_unit``, keyed by filter identifier.
        zp_mag_unit (str): Unit of the magnitude zero point.
    """
    for name in volc.get_mag_colnames():
        photdm = volc.photdms.get(name)
        if photdm is None or photdm.filter is None or not photdm.filter.filter_id:
            continue
        filter_id = str(photdm.filter.filter_id).strip()
        if filter_id not in zp_mag_by_filter_identifier:
            logger.info(
                "%s no magnitude zero point row for filter identifier %s",
                display_name,
                filter_id,
            )
            continue
        existing = photdm.photcal
        if existing is not None and existing.zp_mag is not None:
            continue
        zp_flux = None if existing is None else existing.zp_flux
        zp_flux_unit = None
        if existing is not None and existing.zp_flux is not None:
            zp_flux_unit = existing._zp_flux_unit_text
        mag_sys = existing.mag_sys if existing is not None and existing.mag_sys else "Vega"
        photdm.photcal = PhotCal(
            zp_flux=zp_flux,
            zp_flux_unit=zp_flux_unit,
            zp_mag=zp_mag_by_filter_identifier[filter_id],
            zp_mag_unit=zp_mag_unit,
            mag_sys=mag_sys,
            photometry_filter=photdm.filter,
        )
        logger.info(
            "%s magnitude zero point %s %s for filter identifier %s on column %s",
            display_name,
            zp_mag_by_filter_identifier[filter_id],
            zp_mag_unit,
            filter_id,
            name,
        )


def replace_zero_points(
    volc: VOLightCurve,
    *,
    display_name: str,
    zp_mag_by_filter_identifier: Mapping[str, float],
    zp_mag_unit: str,
    zp_flux: float,
    zp_flux_unit: str,
    source: str,
) -> None:
    """Replaces flux and magnitude zero points for listed filter identifiers.

    A published flux zero point and its unit are discarded. Magnitude and
    flux columns that carry one of the listed identifiers are both updated.

    Args:
        volc (VOLightCurve): Parsed product of one provider.
        display_name (str): Provider label used in the log.
        zp_mag_by_filter_identifier (Mapping[str, float]): Magnitude zero
            point keyed by ``photDM:PhotometryFilter.identifier``.
        zp_mag_unit (str): Unit of the magnitude zero point.
        zp_flux (float): Replacement flux zero point.
        zp_flux_unit (str): Unit of ``zp_flux``.
        source (str): Reference for the magnitude zero points.
    """
    columns = list(dict.fromkeys([*volc.get_mag_colnames(), *volc.get_flux_colnames()]))
    for name in columns:
        photdm = volc.photdms.get(name)
        if photdm is None or photdm.filter is None or not photdm.filter.filter_id:
            continue
        filter_id = str(photdm.filter.filter_id).strip()
        if filter_id not in zp_mag_by_filter_identifier:
            continue
        existing = photdm.photcal
        mag_sys = existing.mag_sys if existing is not None and existing.mag_sys else "Vega"
        photdm.photcal = PhotCal(
            zp_flux=zp_flux,
            zp_flux_unit=zp_flux_unit,
            zp_mag=zp_mag_by_filter_identifier[filter_id],
            zp_mag_unit=zp_mag_unit,
            mag_sys=mag_sys,
            photometry_filter=photdm.filter,
        )
        logger.info(
            "%s replaced zero points filter=%s zp_flux=%s %s zp_mag=%s %s (%s) column=%s",
            display_name,
            filter_id,
            zp_flux,
            zp_flux_unit,
            zp_mag_by_filter_identifier[filter_id],
            zp_mag_unit,
            source,
            name,
        )
