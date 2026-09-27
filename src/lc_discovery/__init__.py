"""Multi-mission lightcurve search and fetch adapters.

Applications import ``list_missions``, ``search``, ``resolve_target``,
``archive_id_from_identifiers``, and ``fetch``. Mission plugins are not
part of this surface. The Dash application parses ``fetch`` bytes into
``VOLightCurve`` only at the UI boundary.
"""

from lc_discovery.api import (
    archive_id_from_identifiers,
    fetch,
    resolve_target,
    search,
)
from lc_discovery.base import MissionArchiveMatch
from lc_discovery.registry import list_missions

__all__ = [
    "MissionArchiveMatch",
    "archive_id_from_identifiers",
    "fetch",
    "list_missions",
    "resolve_target",
    "search",
]
