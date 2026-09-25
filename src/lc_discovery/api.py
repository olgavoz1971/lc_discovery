"""Public search and fetch calls for the discovery package."""

from __future__ import annotations

from astropy.table import Table

from lc_discovery.lc_key import decode_lc_key
from lc_discovery.registry import get_provider


def search(mission_id: str, **kwargs) -> Table:
    """Searches one mission catalogue.

    Args:
        mission_id (str): Registered mission slug.
        **kwargs: Arguments of that mission's catalogue search (position,
            name, archive id, radius, time bounds).

    Returns:
        astropy.table.Table: Catalogue rows. Each row carries an opaque
        ``lc_key``.
    """
    return get_provider(mission_id).search_catalog(**kwargs)


def fetch(lc_key: str, *, force_refresh: bool = False) -> bytes:
    """Fetches one catalogue light curve.

    Args:
        lc_key (str): Opaque key from a catalogue row.
        force_refresh (bool): Accepted by missions. No shared fetch cache
            is wired in this package yet.

    Returns:
        bytes: Calibrated VOTable for the reviewed missions.

    Raises:
        ValueError: When the key or the mission is unknown, or the
            mission does not return VOTable bytes.
    """
    mission_id = decode_lc_key(lc_key)["mission_id"]
    payload = get_provider(mission_id).fetch_lightcurve(
        lc_key,
        force_refresh=force_refresh,
    )
    if not isinstance(payload, (bytes, bytearray)):
        raise ValueError(
            f"{mission_id}: fetch did not return VOTable bytes."
        )
    return bytes(payload)
