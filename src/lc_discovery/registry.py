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
from lc_discovery.providers.tess import TessProvider
from lc_discovery.providers.upjs_ts import UpjsTsProvider
from lc_discovery.providers.ztf import ZtfDr24Provider

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, MissionLightcurveProvider] = {
    AsassnProvider.mission_id: AsassnProvider(),
    GaiaDr3AriProvider.mission_id: GaiaDr3AriProvider(),
    GaiaDr3AipProvider.mission_id: GaiaDr3AipProvider(),
    GaiaDr3VebProvider.mission_id: GaiaDr3VebProvider(),
    OgleOcvsProvider.mission_id: OgleOcvsProvider(),
    PersonalTsProvider.mission_id: PersonalTsProvider(),
    TessProvider.mission_id: TessProvider(),
    UpjsTsProvider.mission_id: UpjsTsProvider(),
    ZtfDr24Provider.mission_id: ZtfDr24Provider(),
    Panstarrs1Dr2Provider.mission_id: Panstarrs1Dr2Provider(),
}


def get_provider(mission_id: str) -> MissionLightcurveProvider:
    """Returns a registered mission provider instance.

    Args:
        mission_id (str): Mission slug from the caller or catalog ``lc_key``.

    Returns:
        MissionLightcurveProvider: Provider for the requested mission.

    Raises:
        ValueError: If ``mission_id`` is unknown.
    """
    provider = PROVIDERS.get(mission_id)
    if provider is None:
        known = ", ".join(sorted(PROVIDERS)) or "(none)"
        raise ValueError(f"Unknown mission '{mission_id}'. Registered missions: {known}.")
    return provider


def validate_mission_groups(descriptors: list[MissionDescriptor]) -> None:
    """Checks the data-group declarations of all missions together.

    Rules: within a group the ``group_rank`` of the non-subset members is
    unique, and a subset needs at least one non-subset member in its group.

    Args:
        descriptors (list[MissionDescriptor]): Descriptors of all missions.

    Raises:
        ValueError: When a rule is broken; the message names the group and
            the missions.
    """
    groups: dict[str, list[MissionDescriptor]] = {}
    for item in descriptors:
        groups.setdefault(item.data_group, []).append(item)
    for group, members in groups.items():
        full = [m for m in members if not m.is_subset]
        subsets = [m for m in members if m.is_subset]
        if subsets and not full:
            names = ", ".join(m.mission_id for m in subsets)
            raise ValueError(
                f"Data group '{group}': subset mission(s) {names} have no non-subset "
                "member in the same group."
            )
        seen: dict[int, str] = {}
        for member in full:
            if member.group_rank in seen:
                raise ValueError(
                    f"Data group '{group}': missions '{seen[member.group_rank]}' and "
                    f"'{member.mission_id}' have the same group_rank {member.group_rank}."
                )
            seen[member.group_rank] = member.mission_id


def list_missions() -> list[MissionDescriptor]:
    """Lists registered missions.

    Returns:
        list[MissionDescriptor]: Sorted mission metadata entries.

    Raises:
        ValueError: When a provider misses a mandatory attribute or the data
            groups are inconsistent.
    """
    descriptors = [provider.descriptor() for provider in PROVIDERS.values()]
    validate_mission_groups(descriptors)
    return sorted(descriptors, key=lambda item: item.display_name.lower())
