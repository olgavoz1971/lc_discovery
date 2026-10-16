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
            "pyasassn is required for the ASAS-SN provider but is not installed. Install "
            "the maintainer's fork (the upstream package is not enough: it cannot run in "
            "daemonic Celery workers and fails with ZeroDivisionError when the archive "
            "reports no lightcurve servers): "
            "pip install 'skypatrol @ git+https://github.com/olgavoz1971/skypatrol.git@master' "
            "or pip install -e '.[asassn]'."
        ) from exc
    return SkyPatrolClient(verbose=verbose)
