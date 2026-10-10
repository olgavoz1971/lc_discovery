"""Multi-mission lightcurve search and fetch adapters.

Applications import ``list_missions``, ``search``, ``resolve_target``,
``archive_id_from_identifiers``, ``fetch`` and ``purge_cache``. Mission plugins are not
part of this surface.
"""

from lc_discovery.api import (
    archive_id_from_identifiers,
    fetch,
    purge_cache,
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
    "purge_cache",
    "resolve_target",
    "search",
]
