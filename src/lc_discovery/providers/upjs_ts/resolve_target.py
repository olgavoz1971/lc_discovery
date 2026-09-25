"""Provider-native target resolution for UPJŠ time series."""

from __future__ import annotations

import logging

from lc_discovery.base import MissionArchiveMatch
from lc_discovery.shared.gaia_dr3_source_id import parse_gaia_source_id
from lc_discovery.providers.upjs_ts import config
from lc_discovery.providers.upjs_ts.cross_ident import (
    lookup_object_id_by_simbad_name,
    lookup_object_id_by_vsx_name,
)

logger = logging.getLogger(__name__)


def resolve_upjs_target_name(name: str) -> MissionArchiveMatch | None:
    """Resolves non-Gaia target text via ``upjs_ts.objects`` before Simbad.

    Gaia DR3 identifiers are handled by direct ``ssa_targname`` catalogue search;
    this helper covers Simbad and VSX names from the local objects table only.

    Args:
        name (str): Raw Target field text from the UI.

    Returns:
        MissionArchiveMatch or None: UPJŠ archive match when recognised.
    """
    query_name = str(name or "").strip()
    if not query_name:
        return None

    if parse_gaia_source_id(query_name) is not None:
        return None

    for match_kind, lookup in (
        ("upjs_simbad_name", lookup_object_id_by_simbad_name),
        ("upjs_vsx_name", lookup_object_id_by_vsx_name),
    ):
        match = lookup(query_name)
        if match is None:
            continue
        object_id, matched_label = match
        return MissionArchiveMatch(
            archive_id=object_id,
            match_kind=match_kind,
            matched_label=matched_label,
        )

    logger.debug("%s target resolution found no match for %r", config.DISPLAY_NAME, name)
    return None
