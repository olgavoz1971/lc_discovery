"""Tests for the data-group declarations (same data, subsets) of the missions."""

from __future__ import annotations

import pytest

from lc_discovery import list_missions
from lc_discovery.base import MissionCapabilities, MissionDescriptor, MissionLightcurveProvider
from lc_discovery.coverage import MissionCoverage
from lc_discovery.registry import validate_mission_groups


def _descriptor(mission_id: str, group: str, *, subset: bool = False, rank: int = 1):
    """Builds a descriptor for group checks.

    Args:
        mission_id (str): Mission slug.
        group (str): Data group id.
        subset (bool): Whether the mission is a subset of the group.
        rank (int): Rank among non-subset members.

    Returns:
        MissionDescriptor: Descriptor with the given group fields.
    """
    return MissionDescriptor(
        mission_id=mission_id,
        display_name=mission_id,
        export_profile="test",
        capabilities=MissionCapabilities(),
        description="test",
        data_group=group,
        is_subset=subset,
        subset_description="part of it" if subset else "",
        group_rank=rank,
    )


class _Provider(MissionLightcurveProvider):
    """Minimal provider; tests set the group attributes on subclasses."""

    mission_id = "dummy"
    display_name = "Dummy"
    export_profile = "test"
    capabilities = MissionCapabilities()
    description = "A dummy mission."
    coverage = MissionCoverage(spatial=None, temporal=None, spectral=None, waveband=None)

    def search_catalog(self, **kwargs):
        raise NotImplementedError

    def fetch_lightcurve(self, lc_key, **kwargs):
        raise NotImplementedError


def _provider(**attributes):
    """Creates a dummy provider with the given class attributes.

    Args:
        **attributes: Class attributes to set (group fields).

    Returns:
        MissionLightcurveProvider: Provider instance.
    """
    return type("Dummy", (_Provider,), attributes)()


GOOD = dict(data_group="g", is_subset=False, subset_description="", group_rank=1)


def test_registered_missions_declare_valid_groups():
    missions = {m.mission_id: m for m in list_missions()}
    ari, aip, veb = (missions[k] for k in ("gaia_dr3_ari", "gaia_dr3_aip", "gaia_dr3_veb"))
    assert ari.data_group == aip.data_group == veb.data_group
    assert (ari.is_subset, aip.is_subset, veb.is_subset) == (False, False, True)
    assert ari.group_rank < aip.group_rank
    assert veb.subset_description.strip()
    assert missions["tess"].data_group == "tess"


def test_descriptor_requires_group_attributes():
    for name in ("data_group", "is_subset", "subset_description", "group_rank"):
        attributes = {k: v for k, v in GOOD.items() if k != name}
        with pytest.raises(ValueError, match=name):
            _provider(**attributes).descriptor()


def test_descriptor_subset_needs_description():
    with pytest.raises(ValueError, match="subset_description"):
        _provider(**{**GOOD, "is_subset": True}).descriptor()


def test_descriptor_non_subset_must_not_describe_subset():
    with pytest.raises(ValueError, match="must be empty"):
        _provider(**{**GOOD, "subset_description": "x"}).descriptor()


@pytest.mark.parametrize("rank", [0, -1, 1.5, True, "1"])
def test_descriptor_rejects_bad_rank(rank):
    with pytest.raises(ValueError, match="group_rank"):
        _provider(**{**GOOD, "group_rank": rank}).descriptor()


def test_descriptor_rejects_empty_group():
    with pytest.raises(ValueError, match="data_group"):
        _provider(**{**GOOD, "data_group": " "}).descriptor()


def test_groups_reject_duplicate_rank():
    items = [_descriptor("a", "g", rank=1), _descriptor("b", "g", rank=1)]
    with pytest.raises(ValueError, match="same group_rank"):
        validate_mission_groups(items)


def test_groups_reject_subset_without_parent():
    with pytest.raises(ValueError, match="no non-subset member"):
        validate_mission_groups([_descriptor("a", "g", subset=True)])


def test_groups_accept_mirrors_and_subset():
    validate_mission_groups(
        [
            _descriptor("a", "g", rank=1),
            _descriptor("b", "g", rank=2),
            _descriptor("c", "g", subset=True),
            _descriptor("d", "other"),
        ]
    )
