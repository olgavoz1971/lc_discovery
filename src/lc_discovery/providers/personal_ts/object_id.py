"""Normalise personal time-series archive object identifiers."""

from __future__ import annotations

import re

from lc_discovery.base import MissionArchiveMatch
from skvo_veb.utils.simbad_resolver import SimbadResolveResult

_PERSONAL_OBJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]*$")


def normalize_personal_object_id(text: str) -> str | None:
    """Normalises UI or Simbad text to a personal ``object_id`` when possible.

    Personal archive ids commonly use underscores instead of spaces
    (e.g. ``AY_Lac`` for Simbad ``AY Lac``).

    Args:
        text (str): Raw object identifier or target name.

    Returns:
        str or None: Canonical personal object id, or ``None`` when unrecognised.
    """
    candidate = str(text or "").strip()
    if not candidate:
        return None

    underscored = re.sub(r"\s+", "_", candidate)
    if _PERSONAL_OBJECT_ID_PATTERN.match(underscored):
        return underscored
    return None


def pick_personal_archive_id_from_simbad(
    simbad_result: SimbadResolveResult,
) -> MissionArchiveMatch | None:
    """Selects a personal ``object_id`` from Simbad identifiers.

    Args:
        simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

    Returns:
        MissionArchiveMatch or None: Personal archive match when recognised.
    """
    candidates = [simbad_result.main_id, *(simbad_result.identifiers or [])]
    seen: set[str] = set()
    for name in candidates:
        object_id = normalize_personal_object_id(name)
        if object_id is None or object_id in seen:
            continue
        seen.add(object_id)
        return MissionArchiveMatch(
            archive_id=object_id,
            match_kind="personal_object_id",
            matched_label=object_id,
        )
    return None
