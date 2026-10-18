"""Agent helper: finds a variable star in the AAVSO VSX index and returns its position.

Not part of the public API and not imported by the package. Use it when Simbad cannot
resolve the name of a variable star (for example ``TCP J23580961+5502508``). VSX gives the
position; a Simbad cone search at that position then gives a Simbad name and identifiers
(see ``.cursor/skills/lc-discovery/SKILL.md``, section "Variable stars that Simbad does not
know").

Run from the package root::

    python scripts/vsx_resolve.py "TCP J23580961+5502508"

Notes:
    * Endpoint: ``https://vsx.aavso.org/index.php?view=api.object&ident=<name>``. It answers
      with XML (JSON is unreliable). An unknown name gives an empty ``<VSXObject/>``.
    * The server has bot protection: send one request at a time and do not loop over long
      lists. No contact address is sent.
    * The list of other names exists only on the HTML detail page and is not read here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass

import requests

logger = logging.getLogger(__name__)

VSX_URL = "https://vsx.aavso.org/index.php"
USER_AGENT = "lc_discovery"
TIMEOUT_SECONDS = 20


class VsxNotResolvedError(ValueError):
    """Raised when VSX does not know the requested name."""


@dataclass(frozen=True)
class VsxObject:
    """One VSX record.

    Attributes:
        name: VSX designation.
        oid: VSX object id.
        auid: AAVSO unique id, if present.
        ra_deg: Right ascension, J2000, degrees.
        dec_deg: Declination, J2000, degrees.
        variability_type: VSX variability type, if present.
        period_days: Period in days, if present.
        epoch_jd: Epoch of maximum or minimum as a Julian Date number, if
            present. VSX documents it as HJD, but old entries may be JD or BJD
            and the API gives no time-system label.
        max_mag: Brightest magnitude text (with band), if present.
        min_mag: Faintest magnitude text (with band), if present.
        spectral_type: Spectral type, if present.
        constellation: Constellation abbreviation, if present.
        detail_url: VSX detail page of the object.
    """

    name: str
    oid: str
    auid: str | None
    ra_deg: float
    dec_deg: float
    variability_type: str | None
    period_days: float | None
    epoch_jd: float | None
    max_mag: str | None
    min_mag: str | None
    spectral_type: str | None
    constellation: str | None
    detail_url: str


def parse_vsx_xml(identifier: str, xml_text: str) -> VsxObject:
    """Parses the answer of the VSX ``api.object`` view.

    Args:
        identifier: The name that was requested (for the error message).
        xml_text: Response body.

    Returns:
        The parsed record.

    Raises:
        VsxNotResolvedError: If VSX returned an empty record.
        ValueError: If the XML is not a VSX record or has no OID or coordinates.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise ValueError(f"VSX answer for {identifier!r} is not XML: {error}") from error
    if root.tag != "VSXObject":
        raise ValueError(f"VSX answer for {identifier!r} has unexpected root <{root.tag}>")
    if len(root) == 0:
        raise VsxNotResolvedError(f"{identifier!r} is not resolved in VSX")

    def text(tag: str) -> str | None:
        element = root.find(tag)
        if element is None or element.text is None or not element.text.strip():
            return None
        return element.text.strip()

    def number(tag: str) -> float | None:
        value = text(tag)
        return None if value is None else float(value)

    oid, ra, dec, name = text("OID"), number("RA2000"), number("Declination2000"), text("Name")
    if oid is None or ra is None or dec is None or name is None:
        raise ValueError(f"VSX record for {identifier!r} lacks name, OID or coordinates")
    return VsxObject(
        name=name,
        oid=oid,
        auid=text("AUID"),
        ra_deg=ra,
        dec_deg=dec,
        variability_type=text("VariabilityType"),
        period_days=number("Period"),
        epoch_jd=number("Epoch"),
        max_mag=text("MaxMag"),
        min_mag=text("MinMag"),
        spectral_type=text("SpectralType"),
        constellation=text("Constellation"),
        detail_url=f"{VSX_URL}?view=detail.top&oid={oid}",
    )


def resolve_vsx(identifier: str) -> VsxObject:
    """Asks VSX for one variable star.

    Args:
        identifier: Any designation known to VSX, including transient names such as
            ``TCP J23580961+5502508``.

    Returns:
        The VSX record with the J2000 position.

    Raises:
        VsxNotResolvedError: If VSX does not know the name.
        requests.HTTPError: If the server answers with an error status.
        ValueError: If the answer cannot be read.
    """
    response = requests.get(
        VSX_URL,
        params={"view": "api.object", "ident": identifier},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    logger.debug("VSX answered %d bytes for %r", len(response.content), identifier)
    return parse_vsx_xml(identifier, response.text)


def main() -> None:
    """Command line entry point: resolves one name and writes the record as JSON."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("identifier", help="variable star name known to VSX")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    sys.stdout.write(json.dumps(asdict(resolve_vsx(args.identifier)), indent=2) + "\n")


if __name__ == "__main__":
    main()
