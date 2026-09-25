"""Sky Patrol client factory (isolated for tests)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_skypatrol_client(*, verbose: bool = False):
    """Instantiates ``SkyPatrolClient`` from ``pyasassn``.

    Args:
        verbose (bool): Passed to the client when supported.

    Returns:
        SkyPatrolClient: Connected client.

    Raises:
        ImportError: When ``pyasassn`` is not installed.
    """
    try:
        from pyasassn.client import SkyPatrolClient
    except ImportError as exc:
        raise ImportError(
            "pyasassn is required for the ASAS-SN provider but is not installed."
        ) from exc
    return SkyPatrolClient(verbose=verbose)
