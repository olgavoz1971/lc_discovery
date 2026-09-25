"""Mission provider registry for Lightcurve Discovery."""

from __future__ import annotations

import logging

from lc_discovery.base import MissionDescriptor, MissionLightcurveProvider
from lc_discovery.providers.asassn import AsassnProvider
from lc_discovery.providers.gaia_dr3_ari import GaiaDr3AriProvider
from lc_discovery.providers.gaia_dr3_aip import GaiaDr3AipProvider
from lc_discovery.providers.gaia_dr3_veb import GaiaDr3VebProvider
from lc_discovery.providers.ogle_ocvs import OgleOcvsProvider
from lc_discovery.providers.panstarrs1_dr2 import Panstarrs1Dr2Provider
from lc_discovery.providers.personal_ts import PersonalTsProvider
from lc_discovery.providers.upjs_ts import UpjsTsProvider
from lc_discovery.providers.ztf import ZtfDr24Provider
from skvo_veb.utils.my_tools import PipeException

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, MissionLightcurveProvider] = {
    AsassnProvider.mission_id: AsassnProvider(),
    GaiaDr3AriProvider.mission_id: GaiaDr3AriProvider(),
    GaiaDr3AipProvider.mission_id: GaiaDr3AipProvider(),
    GaiaDr3VebProvider.mission_id: GaiaDr3VebProvider(),
    OgleOcvsProvider.mission_id: OgleOcvsProvider(),
    PersonalTsProvider.mission_id: PersonalTsProvider(),
    UpjsTsProvider.mission_id: UpjsTsProvider(),
    ZtfDr24Provider.mission_id: ZtfDr24Provider(),
    Panstarrs1Dr2Provider.mission_id: Panstarrs1Dr2Provider(),
}


def get_provider(mission_id: str) -> MissionLightcurveProvider:
    """Returns a registered mission provider instance.

    Args:
        mission_id (str): Mission slug from the UI or catalog ``lc_key``.

    Returns:
        MissionLightcurveProvider: Provider for the requested mission.

    Raises:
        PipeException: If ``mission_id`` is unknown.
    """
    provider = PROVIDERS.get(mission_id)
    if provider is None:
        known = ", ".join(sorted(PROVIDERS)) or "(none)"
        raise PipeException(f"Unknown mission '{mission_id}'. Registered missions: {known}.")
    return provider


def list_missions() -> list[MissionDescriptor]:
    """Lists registered missions for UI selectors.

    Returns:
        list[MissionDescriptor]: Sorted mission metadata entries.
    """
    return sorted(
        (provider.descriptor() for provider in PROVIDERS.values()),
        key=lambda item: item.display_name.lower(),
    )
