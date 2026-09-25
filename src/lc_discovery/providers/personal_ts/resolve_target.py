"""Provider-native target resolution for UPJS personal time series."""

from __future__ import annotations

import logging
import re

from lc_discovery.base import MissionArchiveMatch
from lc_discovery.providers.personal_ts import config
from lc_discovery.providers.personal_ts.cross_ident import (
    lookup_object_id_by_alias,
    lookup_object_id_by_object_id,
)
from lc_discovery.providers.personal_ts.object_id import normalize_personal_object_id

logger = logging.getLogger(__name__)


def target_name_candidates(text: str) -> list[str]:
    """Builds alias and ``object_id`` spellings to try for one user target.

    Args:
        text (str): Raw Target field text.

    Returns:
        list[str]: Unique candidate strings in search order.
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    candidates: list[str] = [raw]
    collapsed = re.sub(r"\s+", " ", raw)
    if collapsed not in candidates:
        candidates.append(collapsed)

    underscored = re.sub(r"\s+", "_", collapsed)
    if underscored not in candidates:
        candidates.append(underscored)

    parts = underscored.split("_")
    if len(parts) >= 2:
        titled = "_".join(
            (part[0].upper() + part[1:].lower()) if len(part) > 1 else part.upper()
            for part in parts
            if part
        )
        if titled not in candidates:
            candidates.append(titled)

    return candidates


def resolve_personal_target_name(name: str) -> MissionArchiveMatch | None:
    """Resolves a user target to a personal archive ``object_id`` before Simbad.

    Tries local spelling normalisation first, then semicolon-separated aliases
    from ``personal.objects.identifiers``.

    Args:
        name (str): Raw Target field text from the UI.

    Returns:
        MissionArchiveMatch or None: Personal archive match when recognised.
    """
    seen_object_ids: set[str] = set()
    seen_aliases: set[str] = set()

    for candidate in target_name_candidates(name):
        alias_key = candidate.casefold()
        if alias_key in seen_aliases:
            continue
        seen_aliases.add(alias_key)

        object_id = normalize_personal_object_id(candidate)
        if object_id is not None and object_id not in seen_object_ids:
            confirmed = lookup_object_id_by_object_id(object_id)
            if confirmed is not None:
                seen_object_ids.add(confirmed)
                return MissionArchiveMatch(
                    archive_id=confirmed,
                    match_kind="personal_object_id",
                    matched_label=candidate,
                )

        cross_match = lookup_object_id_by_alias(candidate)
        if cross_match is None:
            continue
        resolved_id, matched_label = cross_match
        if resolved_id in seen_object_ids:
            continue
        seen_object_ids.add(resolved_id)
        return MissionArchiveMatch(
            archive_id=resolved_id,
            match_kind="personal_cross_ident",
            matched_label=matched_label,
        )

    logger.debug("%s target resolution found no match for %r", config.DISPLAY_NAME, name)
    return None
