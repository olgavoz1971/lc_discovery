"""Share a photometry column's PhotCal with its error column when unlinked.

Remote products sometimes already point the error FIELD at the photcal
GROUP. This step does nothing in that case.
"""

from __future__ import annotations

import logging

from volightcurve import PhotDM, VOLightCurve

logger = logging.getLogger(__name__)


def _photcal_present(volc: VOLightCurve, column: str) -> bool:
    """True when the column already has a PhotCal.

    Args:
        volc (VOLightCurve): Retrieved product.
        column (str): Table column name.

    Returns:
        bool: Whether ``photdms[column].photcal`` is set.
    """
    photdm = volc.photdms.get(column)
    return photdm is not None and photdm.photcal is not None


def _share_one_parent(volc: VOLightCurve, parents: list[str], errors: list[str]) -> None:
    """Copies one parent's PhotCal onto error columns that have none.

    Several parents that already have a PhotCal are left alone. There is no
    reliable error-to-column link in that case.

    Args:
        volc (VOLightCurve): Retrieved product.
        parents (list[str]): Magnitude or flux column names.
        errors (list[str]): Matching error column names.
    """
    linked = [name for name in parents if _photcal_present(volc, name)]
    if len(linked) != 1:
        return
    source = volc.photdms[linked[0]]
    for name in errors:
        if _photcal_present(volc, name):
            continue
        current = volc.photdms.get(name)
        if current is None:
            volc.photdms[name] = PhotDM(
                photcal=source.photcal,
                photometry_filter=source.filter,
            )
        else:
            current.photcal = source.photcal
        logger.info(
            "Linked error column %s to the photcal of %s",
            name,
            linked[0],
        )


def share_photcal_with_unlinked_errors(volc: VOLightCurve) -> None:
    """Gives each unlinked error column the PhotCal of its one photometry column.

    Magnitude errors follow the single magnitude column that already has a
    PhotCal. Flux errors follow the single flux column that already has one.
    An error column that already has a PhotCal is not changed.

    Args:
        volc (VOLightCurve): Retrieved product, mutated in place.
    """
    _share_one_parent(volc, volc.get_mag_colnames(), volc.get_mag_error_colnames())
    _share_one_parent(volc, volc.get_flux_colnames(), volc.get_flux_error_colnames())
