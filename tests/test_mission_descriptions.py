"""Every mission description must tell agents what its search rows contain."""

from lc_discovery import list_missions


def test_every_description_has_a_search_row_columns_paragraph():
    for mission in list_missions():
        marker = "Search row columns:"
        assert marker in mission.description, mission.mission_id
        paragraph = mission.description.split(marker, 1)[1]
        assert "Empty" in paragraph, mission.mission_id
        assert "lc_key" in paragraph, mission.mission_id
