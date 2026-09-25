"""Provider-native target resolution for OGLE OCVS."""

from __future__ import annotations

from lc_discovery.base import MissionArchiveMatch
from lc_discovery.providers.ogle_ocvs.object_id import normalize_ogle_object_id


def resolve_ogle_target_name(name: str) -> MissionArchiveMatch | None:
    """Normalises loose OGLE spellings to ``object_id`` before Simbad.

    Args:
        name (str): Raw Target field text from the UI.

    Returns:
        MissionArchiveMatch or None: OGLE archive match when recognised.
    """
    object_id = normalize_ogle_object_id(name)
    if object_id is None:
        return None
    return MissionArchiveMatch(
        archive_id=object_id,
        match_kind="ogle_object_id",
        matched_label=object_id,
    )
