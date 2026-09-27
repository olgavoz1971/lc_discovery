"""Public search and fetch calls for the discovery package."""

from __future__ import annotations

from collections.abc import Sequence

from astropy.table import Table

from lc_discovery.base import MissionArchiveMatch
from lc_discovery.lc_key import decode_lc_key
from lc_discovery.registry import get_provider
from lc_discovery.simbad import SimbadResolveResult


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


def resolve_target(mission_id: str, name: str) -> MissionArchiveMatch | None:
    """Maps a user name to a mission archive id without searching.

    Args:
        mission_id (str): Registered mission slug.
        name (str): Target text (object name or loose archive spelling).

    Returns:
        MissionArchiveMatch or None: Archive id when the mission recognises
        the name.

    Raises:
        ValueError: When ``mission_id`` is unknown.
    """
    return get_provider(mission_id).resolve_target_name(name)


def archive_id_from_identifiers(
    mission_id: str,
    identifiers: Sequence[str],
    *,
    query_name: str | None = None,
    main_id: str | None = None,
    ra_deg: float = 0.0,
    dec_deg: float = 0.0,
) -> MissionArchiveMatch | None:
    """Picks a mission archive id from Simbad-style identifier strings.

    Args:
        mission_id (str): Registered mission slug.
        identifiers (Sequence[str]): Cross-identifiers (Simbad ``ids``).
        query_name (str, optional): Name as submitted to Simbad.
        main_id (str, optional): Simbad main identifier. Defaults to the
            first identifier when omitted.
        ra_deg (float): ICRS right ascension in degrees. Unused by most
            missions; kept so the plugin sees a complete Simbad payload.
        dec_deg (float): ICRS declination in degrees.

    Returns:
        MissionArchiveMatch or None: Archive id when one identifier matches
        that mission.

    Raises:
        ValueError: When ``mission_id`` is unknown.
    """
    labels = tuple(str(item) for item in identifiers)
    resolved_main = main_id if main_id is not None else (labels[0] if labels else "")
    resolved_query = query_name if query_name is not None else resolved_main
    payload = SimbadResolveResult(
        query_name=resolved_query,
        main_id=resolved_main,
        identifiers=labels,
        ra_deg=float(ra_deg),
        dec_deg=float(dec_deg),
    )
    return get_provider(mission_id).pick_archive_id_from_simbad(payload)


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
