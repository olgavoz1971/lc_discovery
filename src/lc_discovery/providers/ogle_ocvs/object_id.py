"""OGLE ``object_id`` parsing and Simbad cross-match normalisation."""

from __future__ import annotations

import re

from lc_discovery.base import MissionArchiveMatch
from skvo_veb.utils.simbad_resolver import SimbadResolveResult

_OGLE_LOOSE_NAME = re.compile(
    r"^\s*OGLE[\s\-]+([A-Za-z]+)[\s\-]+([A-Za-z]+)[\s\-]+(\d+)\s*$",
    re.IGNORECASE,
)


def normalize_ogle_object_id(text: str | None) -> str | None:
    """Normalises OGLE object identifiers to archive ``object_id`` form.

    Accepts canonical ids (``OGLE-SMC-ECL-05425``) and loose Simbad-style
    spellings (``OGLE SMC-ECL- 5425``) by collapsing separators and zero-padding
    the numeric suffix to five digits.

    Args:
        text (str, optional): Raw user, catalogue, or Simbad identifier.

    Returns:
        str or None: Canonical ``object_id`` when recognised.
    """
    if text is None:
        return None
    candidate = str(text).strip()
    if not candidate:
        return None

    match = _OGLE_LOOSE_NAME.match(candidate)
    if not match:
        collapsed = re.sub(r"[\s\-]+", "-", candidate).upper()
        if collapsed.startswith("OGLE-"):
            parts = collapsed.split("-")
            if len(parts) == 4 and parts[0] == "OGLE" and parts[3].isdigit():
                return f"OGLE-{parts[1]}-{parts[2]}-{int(parts[3]):05d}"
        return None

    survey, varclass, number = match.groups()
    return f"OGLE-{survey.upper()}-{varclass.upper()}-{int(number):05d}"


def pick_ogle_archive_id_from_simbad(
    simbad_result: SimbadResolveResult,
) -> MissionArchiveMatch | None:
    """Selects an OGLE ``object_id`` from Simbad cross-identifiers.

    Scans all Simbad identifiers for loose ``OGLE *-*`` forms and normalises the
    first match to the archive ``object_id`` spelling.

    Args:
        simbad_result (SimbadResolveResult): Shared Simbad resolve payload.

    Returns:
        MissionArchiveMatch or None: OGLE archive match when recognised.
    """
    candidates = list(simbad_result.identifiers)
    if simbad_result.main_id:
        candidates.insert(0, simbad_result.main_id)

    seen: set[str] = set()
    for identifier in candidates:
        if not identifier or "OGLE" not in str(identifier).upper():
            continue
        object_id = normalize_ogle_object_id(identifier)
        if object_id is None or object_id in seen:
            continue
        seen.add(object_id)
        return MissionArchiveMatch(
            archive_id=object_id,
            match_kind="ogle_object_id",
            matched_label=object_id,
        )
    return None
