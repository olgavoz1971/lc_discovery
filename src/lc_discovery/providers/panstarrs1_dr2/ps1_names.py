"""Pan-STARRS catalogue identifier parsing for discovery lookups."""

from __future__ import annotations

import re

from lc_discovery.base import MissionArchiveMatch

_OBJID_DIGITS_PATTERN = re.compile(r"^\d+$")
_OBJID_LONG_DIGITS_PATTERN = re.compile(r"^\d{10,}$")
_PS1_OBJID_PREFIX_PATTERN = re.compile(
    r"^\s*(?:Pan[-\s]?STARRS(?:\s*1)?|PS1|PS1DR2)\s*([0-9]{10,})\s*$",
    re.IGNORECASE,
)


_PS1_OBJECT_LABEL_PREFIX = "PS1"


def format_ps1_object_name(obj_id: int | str) -> str:
    """Returns the catalogue display label for a Pan-STARRS mean object.

    Args:
        obj_id (int or str): Pan-STARRS ``objID`` (may arrive as numpy scalar or str).

    Returns:
        str: Human-readable label such as ``PS1 165243463579570976`` for AgGrid
        ``object_name`` and lightcurve titles.
    """
    # Normalise to a plain integer: TAP may return int64; lc_key may store str digits.
    canonical_id = int(obj_id)
    return f"{_PS1_OBJECT_LABEL_PREFIX} {canonical_id}"


def parse_ps1_obj_id(text: str | None) -> int | None:
    """Parses a Pan-STARRS ``objID`` from user or archive text.

    Accepts bare long digit strings (Gaia-style direct id entry), optional
    ``PS1`` / ``Pan-STARRS`` prefixes, and compact all-digit ids after
    whitespace removal. ``PS`` IAU names are not queried (unindexed).

    Args:
        text (str, optional): Raw identifier string.

    Returns:
        int or None: Object id when recognised as a numeric Pan-STARRS id.
    """
    if text is None:
        return None
    candidate = str(text).strip()
    if not candidate:
        return None

    prefix_match = _PS1_OBJID_PREFIX_PATTERN.match(candidate)
    if prefix_match:
        try:
            return int(prefix_match.group(1))
        except ValueError:
            return None

    compact = candidate.replace(" ", "")
    if _OBJID_LONG_DIGITS_PATTERN.match(compact):
        try:
            return int(compact)
        except ValueError:
            return None

    if _OBJID_DIGITS_PATTERN.match(compact):
        try:
            value = int(compact)
        except ValueError:
            return None
        if value >= 10**9:
            return value
    return None


def mission_archive_match_for_obj_id(obj_id: int) -> MissionArchiveMatch:
    """Builds a provider archive match for a numeric ``objID``.

    Args:
        obj_id (int): Pan-STARRS mean object identifier.

    Returns:
        MissionArchiveMatch: Match payload for direct catalogue lookup.
    """
    label = format_ps1_object_name(obj_id)
    return MissionArchiveMatch(
        archive_id=str(obj_id),
        match_kind="ps1_obj_id",
        matched_label=label,
    )
