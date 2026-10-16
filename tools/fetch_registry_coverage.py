"""Developer tool: stores VO Registry coverage of a mission in its provider package.

Not part of the public API and not imported by the package. It asks a RegTAP service
(IVOA RegTAP 1.2, tables ``rr.stc_spatial``, ``rr.stc_temporal``, ``rr.stc_spectral``) for
the coverage of one registry record and writes a module ``registry_coverage.py`` next to the
provider, with the values and where they came from. The provider then imports the module.

Needs ``pyvo`` (not a dependency of the package). Run from the package root::

    python tools/fetch_registry_coverage.py upjs_ts ivo://astro.upjs/upjs_ts/q/ssa
    python tools/fetch_registry_coverage.py personal_ts ivo://astro.upjs/personal/q/ssa

Time limits are rounded outward to whole MJD days (start down, end up). Spectral limits
are kept as published, in joules. A part with no registry rows stops the tool with an
error; nothing is invented.

References:
    https://www.ivoa.net/documents/RegTAP/20241002/REC-RegTAP-1.2.html (sections 8.15 to 8.17)
    https://www.ivoa.net/documents/VODataService/20211102/REC-VODataService-1.2.html (section 3.2)
"""

from __future__ import annotations

import argparse
import logging
import math
from datetime import date
from pathlib import Path

import pyvo

logger = logging.getLogger(__name__)

REGTAP_URL = "http://reg.g-vo.org/tap"
PROVIDERS_DIR = Path(__file__).resolve().parents[1] / "src" / "lc_discovery" / "providers"


def _quote(ivoid: str) -> str:
    """Quotes an ivoid for ADQL.

    Args:
        ivoid (str): Registry identifier.

    Returns:
        str: ADQL string literal.
    """
    return "'" + ivoid.replace("'", "''") + "'"


def fetch_registry_coverage(ivoid: str, regtap_url: str = REGTAP_URL) -> dict:
    """Reads the spatial, temporal and spectral coverage of one registry record.

    Args:
        ivoid (str): Registry identifier, for example ``ivo://astro.upjs/upjs_ts/q/ssa``.
        regtap_url (str): TAP access URL of a RegTAP service.

    Returns:
        dict: ``spatial`` (MOC string), ``temporal`` (tuple of MJD pairs, rounded outward)
        and ``spectral`` (tuple of joule pairs).

    Raises:
        ValueError: When the record has no spatial, temporal or spectral rows, or
            more than one spatial row.
    """
    service = pyvo.dal.TAPService(regtap_url)
    where = f"ivoid = {_quote(ivoid)}"
    spatial = service.run_sync(
        f"SELECT coverage, ref_system_name FROM rr.stc_spatial WHERE {where}"
    ).to_table()
    temporal = service.run_sync(
        f"SELECT time_start, time_end FROM rr.stc_temporal WHERE {where}"
    ).to_table()
    spectral = service.run_sync(
        f"SELECT spectral_start, spectral_end FROM rr.stc_spectral WHERE {where}"
    ).to_table()
    for name, table in (("spatial", spatial), ("temporal", temporal), ("spectral", spectral)):
        if len(table) == 0:
            raise ValueError(f"{ivoid}: the registry has no {name} coverage rows at {regtap_url}.")
    if len(spatial) != 1:
        raise ValueError(f"{ivoid}: expected one spatial coverage row, got {len(spatial)}.")
    return {
        "spatial": str(spatial["coverage"][0]).strip(),
        "temporal": tuple(
            (float(math.floor(row["time_start"])), float(math.ceil(row["time_end"])))
            for row in temporal
        ),
        "spectral": tuple(
            (float(row["spectral_start"]), float(row["spectral_end"])) for row in spectral
        ),
    }


def render_module(ivoid: str, values: dict, regtap_url: str, retrieved: date) -> str:
    """Renders the source of a ``registry_coverage.py`` module.

    Args:
        ivoid (str): Registry identifier the values came from.
        values (dict): Result of :func:`fetch_registry_coverage`.
        regtap_url (str): RegTAP service that was asked.
        retrieved (date): Date of retrieval.

    Returns:
        str: Python source text.
    """
    chunks = []
    text = values["spatial"]
    while text:
        cut = text.rfind(" ", 0, 84) + 1 if len(text) > 84 else len(text)
        cut = cut or len(text)
        chunks.append(text[:cut])
        text = text[cut:]
    spatial = "\n".join(f'    "{chunk}"' for chunk in chunks)
    return (
        '"""Coverage of the mission as published in the VO Registry (stored once).\n\n'
        f"Record: {ivoid}\n"
        f"Asked: {regtap_url} (RegTAP), {retrieved.isoformat()}.\n"
        "Written by tools/fetch_registry_coverage.py; do not edit by hand. Time limits are\n"
        "rounded outward to whole MJD days; spectral limits are as published (joules).\n"
        '"""\n\n'
        f"REGISTRY_SPATIAL_MOC = (\n{spatial}\n)\n\n"
        f"REGISTRY_TEMPORAL = {values['temporal']!r}\n\n"
        f"REGISTRY_SPECTRAL = {values['spectral']!r}\n"
    )


def main() -> None:
    """Command-line entry point: fetches one record and writes the provider module."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("provider", help="Provider package name, for example upjs_ts.")
    parser.add_argument("ivoid", help="Registry identifier of the record.")
    parser.add_argument("--regtap", default=REGTAP_URL, help="RegTAP TAP URL.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    package = PROVIDERS_DIR / args.provider
    if not package.is_dir():
        raise SystemExit(f"No provider package {package}.")
    values = fetch_registry_coverage(args.ivoid, args.regtap)
    target = package / "registry_coverage.py"
    target.write_text(render_module(args.ivoid, values, args.regtap, date.today()))
    logger.info("Wrote %s", target)


if __name__ == "__main__":
    main()
