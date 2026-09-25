"""Gaia DR3 ``source_id`` parsing shared by discovery providers."""

from __future__ import annotations

import re

from lc_discovery.base import MissionArchiveMatch
from skvo_veb.utils.simbad_resolver import SimbadResolveResult

_GAIA_ID_PATTERN = re.compile(r"^\d{10,22}$")
_GAIA_PREFIX_PATTERN = re.compile(
    r"^\s*(?:Gaia\s*DR\s*3|GAIADR3)\s*([0-9]{10,22})\s*$",
    re.IGNORECASE,
)


def parse_gaia_source_id(text: str | None) -> int | None:
    """Parses a Gaia DR3 ``source_id`` from a user or Simbad identifier string.

    Args:
        text (str, optional): Raw identifier such as ``Gaia DR3 123…`` or digits.

    Returns:
        int or None: Gaia source id when recognised.
    """
    if text is None:
        return None
    candidate = str(text).strip()
    if not candidate:
        return None
    prefix_match = _GAIA_PREFIX_PATTERN.match(candidate)
    if prefix_match:
        return int(prefix_match.group(1))
    compact = candidate.replace(" ", "")
    if _GAIA_ID_PATTERN.match(compact):
        return int(compact)
    return None


def format_gaia_source_name(source_id: int | str) -> str:
    """Returns the standard Gaia DR3 catalogue label for a ``source_id``.

    Args:
        source_id (int or str): Gaia DR3 source identifier.

    Returns:
        str: Label such as ``Gaia DR3 1936512041221649536``.
    """
    return f"Gaia DR3 {source_id}"


def pick_gaia_archive_id_from_simbad(
    simbad_result: SimbadResolveResult,
) -> MissionArchiveMatch | None:
    """Selects a Gaia DR3 source id from Simbad cross-identifiers.

    Args:
        simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

    Returns:
        MissionArchiveMatch or None: Gaia archive match when an id is recognised.
    """
    for identifier in simbad_result.identifiers:
        source_id = parse_gaia_source_id(identifier)
        if source_id is None:
            continue
        label = format_gaia_source_name(source_id)
        return MissionArchiveMatch(
            archive_id=str(source_id),
            match_kind="gaia_source_id",
            matched_label=label,
        )
    return None
