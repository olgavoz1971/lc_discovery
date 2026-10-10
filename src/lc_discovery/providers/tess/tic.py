"""TIC parsing shared by TESS archive discovery, analogous to Gaia ``source_id``."""

from __future__ import annotations

import re

from lc_discovery.base import MissionArchiveMatch
from lc_discovery.providers.tess import config
from lc_discovery.simbad import SimbadResolveResult

_TIC_PREFIX_PATTERN = re.compile(
    r"^\s*TIC\s*:?\s*(\d+)\s*$",
    re.IGNORECASE,
)
_TIC_BARE_PATTERN = re.compile(r"^\d{6,}$")


def parse_tic(text: str | None) -> int | None:
    """Parses a TIC number from a user or Simbad identifier string.

    Accepts ``TIC 159717514``, ``TIC:159717514``, and a bare integer of at
    least six digits.

    Args:
        text (str, optional): Raw identifier.

    Returns:
        int or None: TIC when recognised.
    """
    if text is None:
        return None
    candidate = str(text).strip()
    if not candidate:
        return None
    prefix_match = _TIC_PREFIX_PATTERN.match(candidate)
    if prefix_match:
        return int(prefix_match.group(1))
    compact = candidate.replace(" ", "")
    if _TIC_BARE_PATTERN.match(compact):
        return int(compact)
    return None


def mission_archive_match_for_tic(tic: int | str) -> MissionArchiveMatch:
    """Builds a provider archive match for a TIC.

    Args:
        tic (int or str): TESS Input Catalogue number.

    Returns:
        MissionArchiveMatch: Match payload for Discovery orchestration.
    """
    tic_int = int(tic)
    return MissionArchiveMatch(
        archive_id=str(tic_int),
        match_kind="tic",
        matched_label=config.format_tic_name(tic_int),
    )


def pick_tic_from_simbad(simbad_result: SimbadResolveResult) -> MissionArchiveMatch | None:
    """Selects a TIC from Simbad cross-identifiers.

    Args:
        simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

    Returns:
        MissionArchiveMatch or None: TIC match when an identifier is recognised.
    """
    for identifier in simbad_result.identifiers:
        tic = parse_tic(identifier)
        if tic is None:
            continue
        return mission_archive_match_for_tic(tic)
    return None
