"""Multi-mission lightcurve search and fetch adapters.

Mission providers return catalogue tables from ``search_catalog`` and
calibrated VOTable bytes from ``fetch_lightcurve``. The Dash application
parses those bytes into ``VOLightCurve`` only at the UI boundary.
"""

from lc_discovery.base import (
    MissionArchiveMatch,
    MissionCapabilities,
    MissionLightcurveProvider,
)
from lc_discovery.api import fetch, search
from lc_discovery.registry import get_provider, list_missions

__all__ = [
    "MissionArchiveMatch",
    "MissionCapabilities",
    "MissionLightcurveProvider",
    "fetch",
    "get_provider",
    "list_missions",
    "search",
]
