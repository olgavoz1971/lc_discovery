"""Agent helper: resolves a name or a position in Simbad into a main id and identifiers.

Not part of the public API and not imported by the package. It returns the same payload that
``lc_discovery.archive_id_from_identifiers`` needs (``SimbadResolveResult``: main id,
identifier list, ICRS position), so the result goes straight into a mission's id lookup.
Needs ``astroquery`` (extra ``scripts``). Run from the package root::

    python scripts/simbad_resolve.py name "AA And"
    python scripts/simbad_resolve.py position 359.54012 55.04742 --radius-arcsec 5

Behaviour:
    * Nothing is guessed. A name that Simbad does not know raises ``SimbadNotResolvedError``;
      there is no fallback to another name resolver.
    * A position search returns **all** Simbad objects inside the radius, nearest first, with
      their separations. The caller (or the user) decides which one is meant; this is
      especially important in crowded fields.
    * Network failures are raised as they are, not reported as "not found".
    * The helper uses astroquery's shared ``Simbad`` object and stays on its current mirror
      (by default the CDS server). It never tries another mirror by itself. The caller picks
      the mirror: in a process of its own, set ``Simbad.server`` to a host from
      ``astroquery.simbad.conf.servers_list`` before calling the functions, or give
      ``--server`` on the command line (it is set before any other access). The caller also
      imposes its own wall-clock limit (``Simbad.timeout`` does not stop a query that never
      answers; setting it contacts the current mirror, so set ``server`` first). See the
      ``lc-discovery`` skill, section "Simbad mirrors".
    * Command line exit codes: 0 answered; 3 the mirror answered and the name or position is
      unknown (``SimbadNotResolvedError``: do not ask another mirror); 4 the mirror did not
      answer (network failure: the caller may ask the next mirror); 1 any other error. A
      wall-clock limit from the caller (for example ``timeout 15 python ...``) ends with 124,
      which is also a failure of the mirror, not an answer.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass

from astropy import units as u
from astropy.coordinates import SkyCoord

from lc_discovery.simbad import SimbadResolveResult

logger = logging.getLogger(__name__)

DEFAULT_RADIUS_ARCSEC = 5.0
DEFAULT_MAX_CANDIDATES = 5


class SimbadNotResolvedError(ValueError):
    """Raised when Simbad has no object for the requested name or position."""


@dataclass(frozen=True)
class SimbadCandidate:
    """One Simbad object found around a position.

    Attributes:
        separation_arcsec: Distance from the searched position in arcseconds.
        result: Main id, identifiers and ICRS position of the object.
    """

    separation_arcsec: float
    result: SimbadResolveResult


def _column(table, *names: str):
    """Returns the first column of an Astropy table that matches a name, ignoring case.

    Args:
        table: Astropy table from astroquery.
        *names: Candidate column names.

    Returns:
        The matching column.

    Raises:
        KeyError: If no name matches.
    """
    index = {name.lower(): name for name in table.colnames}
    for name in names:
        if name.lower() in index:
            return table[index[name.lower()]]
    raise KeyError(f"none of {names} in Simbad columns {table.colnames}")


def _identifiers(simbad, main_id: str) -> tuple[str, ...]:
    """Reads the cross-identifiers of one Simbad object.

    Args:
        simbad: ``astroquery.simbad.Simbad`` instance.
        main_id: Simbad main identifier.

    Returns:
        Identifiers, main id first, without duplicates.

    Raises:
        SimbadNotResolvedError: If Simbad returns no identifiers for the main id.
    """
    table = simbad.query_objectids(main_id)
    if table is None or len(table) == 0:
        raise SimbadNotResolvedError(f"Simbad returned no identifiers for {main_id!r}")
    ids = [str(value) for value in _column(table, "id")]
    return tuple(dict.fromkeys([main_id, *ids]))


def resolve_simbad_name(name: str) -> SimbadResolveResult:
    """Resolves one object name in Simbad.

    Args:
        name: Any name or alias that Simbad knows.

    Returns:
        Main id, identifier list and ICRS position (degrees).

    Raises:
        ValueError: If the name is empty.
        SimbadNotResolvedError: If Simbad does not know the name.
    """
    from astroquery.simbad import Simbad

    query = str(name or "").strip()
    if not query:
        raise ValueError("Target name is empty")
    table = Simbad.query_object(query)
    if table is None or len(table) == 0:
        raise SimbadNotResolvedError(f"{query!r} is not resolved in Simbad")
    main_id = str(_column(table, "main_id")[0])
    coord = SkyCoord(
        ra=float(_column(table, "ra")[0]) * u.deg,
        dec=float(_column(table, "dec")[0]) * u.deg,
        frame="icrs",
    )
    logger.info("Simbad resolved %r to %r", query, main_id)
    return SimbadResolveResult(
        query_name=query,
        main_id=main_id,
        identifiers=_identifiers(Simbad, main_id),
        ra_deg=float(coord.ra.deg),
        dec_deg=float(coord.dec.deg),
    )


def find_simbad_objects(
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float = DEFAULT_RADIUS_ARCSEC,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> list[SimbadCandidate]:
    """Lists the Simbad objects around a position, nearest first.

    Args:
        ra_deg: ICRS right ascension in degrees.
        dec_deg: ICRS declination in degrees.
        radius_arcsec: Search radius in arcseconds.
        max_candidates: Largest number of objects to return with identifiers. If Simbad
            found more, the call fails instead of cutting the list silently.

    Returns:
        Candidates sorted by separation.

    Raises:
        SimbadNotResolvedError: If no object is inside the radius.
        ValueError: If more than ``max_candidates`` objects are inside the radius; reduce
            the radius or raise the limit.
    """
    from astroquery.simbad import Simbad

    centre = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg, frame="icrs")
    table = Simbad.query_region(centre, radius=radius_arcsec * u.arcsec)
    if table is None or len(table) == 0:
        raise SimbadNotResolvedError(
            f"no Simbad object within {radius_arcsec} arcsec of RA={ra_deg}, Dec={dec_deg}"
        )
    if len(table) > max_candidates:
        raise ValueError(
            f"{len(table)} Simbad objects within {radius_arcsec} arcsec; "
            f"reduce the radius or raise max_candidates ({max_candidates})"
        )
    mains = [str(value) for value in _column(table, "main_id")]
    ras = [float(value) for value in _column(table, "ra")]
    decs = [float(value) for value in _column(table, "dec")]
    found = []
    for main_id, ra, dec in zip(mains, ras, decs):
        position = SkyCoord(ra=ra * u.deg, dec=dec * u.deg, frame="icrs")
        separation = float(centre.separation(position).arcsec)
        payload = SimbadResolveResult(
            query_name=main_id,
            main_id=main_id,
            identifiers=_identifiers(Simbad, main_id),
            ra_deg=ra,
            dec_deg=dec,
        )
        found.append(SimbadCandidate(separation_arcsec=separation, result=payload))
    found.sort(key=lambda candidate: candidate.separation_arcsec)
    logger.info("Simbad found %d object(s) near RA=%s Dec=%s", len(found), ra_deg, dec_deg)
    return found


EXIT_ANSWERED = 0
EXIT_NOT_RESOLVED = 3
EXIT_NETWORK_FAILURE = 4


def _network_errors() -> tuple[type[BaseException], ...]:
    """Returns the exception types that mean "the mirror did not answer".

    Returns:
        Tuple of exception classes: ``OSError`` (covers ``requests`` connection and
        timeout errors) and the PyVO service error.
    """
    from pyvo.dal import DALServiceError

    return (OSError, DALServiceError)


def main(argv: list[str] | None = None) -> int:
    """Command line entry point: resolves a name or a position and writes JSON.

    Args:
        argv: Arguments without the program name; ``None`` reads ``sys.argv``.

    Returns:
        Exit code: 0 answered, 3 not found (the mirror answered), 4 network failure.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    parser.add_argument(
        "--server",
        default=None,
        help="Simbad mirror, one host of astroquery.simbad.conf.servers_list "
        "(set before any other access); default: astroquery's current mirror",
    )
    by_name = sub.add_parser("name", help="resolve a name")
    by_name.add_argument("name")
    by_position = sub.add_parser("position", help="list objects around a position")
    by_position.add_argument("ra_deg", type=float)
    by_position.add_argument("dec_deg", type=float)
    by_position.add_argument("--radius-arcsec", type=float, default=DEFAULT_RADIUS_ARCSEC)
    by_position.add_argument("--max-candidates", type=int, default=DEFAULT_MAX_CANDIDATES)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    from astroquery.simbad import Simbad

    if args.server is not None:
        Simbad.server = args.server
    logger.info("Simbad mirror: %s", Simbad.server)
    try:
        if args.command == "name":
            output = asdict(resolve_simbad_name(args.name))
        else:
            found = find_simbad_objects(
                args.ra_deg, args.dec_deg, args.radius_arcsec, args.max_candidates
            )
            output = [asdict(candidate) for candidate in found]
    except SimbadNotResolvedError as error:
        sys.stderr.write(f"Simbad ({Simbad.server}) answered: {error}\n")
        return EXIT_NOT_RESOLVED
    except _network_errors() as error:
        sys.stderr.write(f"Simbad ({Simbad.server}) did not answer: {error!r}\n")
        return EXIT_NETWORK_FAILURE
    sys.stdout.write(json.dumps(output, indent=2) + "\n")
    return EXIT_ANSWERED


if __name__ == "__main__":
    sys.exit(main())
