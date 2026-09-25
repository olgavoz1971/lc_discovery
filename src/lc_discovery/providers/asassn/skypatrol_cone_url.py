"""Workarounds for ASAS-SN Sky Patrol HTTP API quirks."""

from __future__ import annotations

# The Hawaii ``lookup_cone`` path template embeds RA/Dec in the URL segment
# ``..._ra{ra}_dec{dec}``. Live tests (2026-08) show HTTP 500 when either
# coordinate is exactly 0.0 (e.g. ``_dec0.0``), while 1e-8 deg offsets succeed.
# Offset is far below any discovery cone radius used in this app.
_SKYPATROL_LOOKUP_ZERO_EPS_DEG = 1e-8


def skypatrol_cone_centre_for_lookup_url(
    ra_deg: float,
    dec_deg: float,
) -> tuple[float, float]:
    """Returns RA/Dec safe for Sky Patrol ``lookup_cone`` URL paths.

    Args:
        ra_deg (float): Cone centre right ascension in degrees.
        dec_deg (float): Cone centre declination in degrees.

    Returns:
        tuple[float, float]: ``(ra_deg, dec_deg)`` with exact zeros replaced by
        a tiny offset so the archive path parser accepts the request.
    """
    ra = float(ra_deg)
    dec = float(dec_deg)
    eps = _SKYPATROL_LOOKUP_ZERO_EPS_DEG
    if ra == 0.0:
        ra = eps
    if dec == 0.0:
        dec = eps
    return ra, dec
