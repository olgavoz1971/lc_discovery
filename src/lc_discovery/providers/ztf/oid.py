"""Parse ZTF OID strings from Discovery target fields."""

from __future__ import annotations

import re

from lc_discovery.base import MissionArchiveMatch
from lc_discovery.providers.ztf import config

_ZTF_OID_PATTERN = re.compile(r"^\d{10,22}$")


def parse_ztf_oid(text: str | None) -> int | None:
    """Parses a ZTF OID from a digit-only target string.

    Args:
        text (str, optional): Raw identifier from the Target field.

    Returns:
        int or None: ZTF OID when recognised.
    """
    if text is None:
        return None
    candidate = str(text).strip().replace(" ", "")
    if not candidate:
        return None
    if _ZTF_OID_PATTERN.match(candidate):
        return int(candidate)
    return None


def mission_archive_match_for_oid(oid: int | str) -> MissionArchiveMatch:
    """Builds a provider archive match for a ZTF OID.

    Args:
        oid (int or str): ZTF object/lightcurve identifier.

    Returns:
        MissionArchiveMatch: Match payload for Discovery orchestration.
    """
    label = config.format_ztf_oid_name(oid)
    return MissionArchiveMatch(
        archive_id=str(int(oid)),
        match_kind="ztf_oid",
        matched_label=label,
    )
