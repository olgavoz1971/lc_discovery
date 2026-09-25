"""Configuration and ADQL templates for Pan-STARRS1 DR2 MAST TAP."""

from __future__ import annotations

from dataclasses import dataclass

from lc_discovery.providers.panstarrs1_dr2.ps1_names import format_ps1_object_name
from lc_discovery.tap.adql import adql_top_limit_clause
from lc_discovery.tap.dialect import TapQueryDialect

PROVIDER_ID = "panstarrs1_dr2"
DISPLAY_NAME = "Pan-STARRS1 DR2"
EXPORT_PROFILE = PROVIDER_ID

TAP_URL = "https://mast.stsci.edu/vo-tap/api/v0.1/ps1dr2/"
TAP_QUERY_DIALECT = TapQueryDialect.ADQL_2_1
# MAST PS1 DR2 TAP rejects cones wider than 0.25 deg; stay slightly inside.
MAX_DISCOVERY_SEARCH_RADIUS_DEG = 0.24

MEAN_OBJECT_VIEW = "dbo.MeanObjectView"
DETECTION_TABLE = "dbo.Detection"
FILTER_TABLE = "dbo.Filter"

FACILITY_NAME = "Haleakala"
INSTRUMENT_NAME = "Pan-STARRS 1.8 m telescope"
PUBLICATION_BIBCODE = "2020ApJS..251....7F"
CREATOR = "Pan-STARRS1 DR2"

TIMESCALE = "tai"
REFPOSITION = "TOPOCENTER"
COOSYS_SYSTEM = "ICRS"
# Fallback only when a joined detection query lacks finite epochMean (should not happen).
COOSYS_EPOCH_FALLBACK = 2012.5
TIMEORIGIN_MJD = 2400000.5

AB_REFERENCE_FLUX_JY = 3631.0
MAG_SYSTEM = "AB"

MIN_PSF_QF_PERFECT = 0.9
MIN_PSF_FLUX = 0.0

DETECTION_PHOTOMETRY_TYPE = "PSF"
LOOKUP_ASSOCIATION_MAX_ARCSEC = 5.0
COOSYS_EPOCH_DECIMAL_PLACES = 1

DISCOVERY_CATALOG_PROVIDER_NOTE = "Mean PSF mag; n_det from MeanObjectView"
SURVEY_LABEL = "Pan-STARRS1 DR2"

MEAN_OBJECT_SELECT_COLUMNS = (
    "objID",
    "raMean",
    "decMean",
    "nDetections",
    "ng",
    "nr",
    "ni",
    "nz",
    "ny",
    "gMeanPSFMag",
    "rMeanPSFMag",
    "iMeanPSFMag",
    "zMeanPSFMag",
    "yMeanPSFMag",
)


@dataclass(frozen=True)
class Ps1BandSpec:
    """One Pan-STARRS1 DR2 filter exposed in MeanObjectView and Detection."""

    filter_name: str
    filter_identifier: str
    effective_wavelength_angstrom: float
    n_det_column: str
    mean_mag_column: str


PS1_BANDS: tuple[Ps1BandSpec, ...] = (
    Ps1BandSpec(
        filter_name="g",
        filter_identifier="PAN-STARRS/PS1.g",
        effective_wavelength_angstrom=4810.16,
        n_det_column="ng",
        mean_mag_column="gMeanPSFMag",
    ),
    Ps1BandSpec(
        filter_name="r",
        filter_identifier="PAN-STARRS/PS1.r",
        effective_wavelength_angstrom=6155.47,
        n_det_column="nr",
        mean_mag_column="rMeanPSFMag",
    ),
    Ps1BandSpec(
        filter_name="i",
        filter_identifier="PAN-STARRS/PS1.i",
        effective_wavelength_angstrom=7503.03,
        n_det_column="ni",
        mean_mag_column="iMeanPSFMag",
    ),
    Ps1BandSpec(
        filter_name="z",
        filter_identifier="PAN-STARRS/PS1.z",
        effective_wavelength_angstrom=8668.36,
        n_det_column="nz",
        mean_mag_column="zMeanPSFMag",
    ),
    Ps1BandSpec(
        filter_name="y",
        filter_identifier="PAN-STARRS/PS1.y",
        effective_wavelength_angstrom=9613.60,
        n_det_column="ny",
        mean_mag_column="yMeanPSFMag",
    ),
)

# Documented passbands without MeanObjectView epoch columns (metadata only).
PS1_EXTENDED_FILTER_METADATA: tuple[tuple[str, float], ...] = (
    ("PAN-STARRS/PS1.w", 5980.70),
    ("PAN-STARRS/PS1.open", 6431.87),
)


def band_spec_for_filter_name(filter_name: str) -> Ps1BandSpec:
    """Returns band metadata for a PS1 ``filterType`` / catalogue filter name.

    Args:
        filter_name (str): One of ``g``, ``r``, ``i``, ``z``, ``y`` (lowercase).

    Returns:
        Ps1BandSpec: Matching band specification.

    Raises:
        ValueError: When ``filter_name`` is unknown.
    """
    name = str(filter_name).strip().lower()
    for band in PS1_BANDS:
        if band.filter_name == name:
            return band
    raise ValueError(f"Unknown Pan-STARRS1 filter: {filter_name!r}.")


def adql_escape_string(value: str) -> str:
    """Escapes a literal string for ADQL single-quoted strings.

    Args:
        value (str): Raw string.

    Returns:
        str: Escaped literal safe to embed in ADQL.
    """
    return str(value).replace("'", "''")


def _mean_object_select_clause() -> str:
    """Returns the discovery SELECT column list.

    Returns:
        str: Comma-separated column names.
    """
    return ", ".join(MEAN_OBJECT_SELECT_COLUMNS)


def adql_mean_objects_cone(
    *,
    ra_deg: float,
    dec_deg: float,
    radius_arcsec: float,
    row_limit: int | None = None,
) -> str:
    """Builds ADQL 2.1 cone search on ``MeanObjectView``.

    Args:
        ra_deg (float): Cone centre right ascension in degrees.
        dec_deg (float): Cone centre declination in degrees.
        radius_arcsec (float): Cone radius in arcseconds.
        row_limit (int, optional): ``TOP`` limit on unique mean objects.

    Returns:
        str: Complete ADQL query string.
    """
    radius_deg = float(radius_arcsec) / 3600.0
    ra = float(ra_deg)
    dec = float(dec_deg)
    top = adql_top_limit_clause(row_limit)
    geometry = (
        f"CONTAINS(POINT('ICRS', raMean, decMean), "
        f"CIRCLE('ICRS', {ra}, {dec}, {radius_deg})) = 1"
    )
    return (
        f"SELECT {top}{_mean_object_select_clause()} "
        f"FROM {MEAN_OBJECT_VIEW} "
        f"WHERE {geometry} "
        f"AND nDetections > 1 "
        f"ORDER BY randomId"
    )


def adql_mean_object_by_obj_id(obj_id: int) -> str:
    """Builds ADQL for direct ``objID`` lookup on ``MeanObjectView``.

    Args:
        obj_id (int): Pan-STARRS mean object identifier.

    Returns:
        str: Complete ADQL query string.
    """
    return (
        f"SELECT {_mean_object_select_clause()} "
        f"FROM {MEAN_OBJECT_VIEW} "
        f"WHERE objID = {int(obj_id)}"
    )


def adql_detection_lightcurve(*, obj_id: int, filter_name: str) -> str:
    """Builds ADQL for epoch photometry in one filter with mean-object epoch.

    Joins ``MeanObjectView`` so ``epochMean`` (MJD) is returned alongside
    detection epochs in one TAP request.

    Args:
        obj_id (int): Pan-STARRS mean object identifier.
        filter_name (str): ``Filter.filterType`` code (``g``, ``r``, …).

    Returns:
        str: Complete ADQL query string.
    """
    ftype = adql_escape_string(str(filter_name).strip().lower())
    return (
        f"SELECT d.objID, d.obsTime, d.psfFlux, d.psfFluxErr, d.psfQfPerfect, "
        f"m.epochMean "
        f"FROM {DETECTION_TABLE} AS d "
        f"NATURAL JOIN {FILTER_TABLE} AS f "
        f"INNER JOIN {MEAN_OBJECT_VIEW} AS m ON d.objID = m.objID "
        f"WHERE d.objID = {int(obj_id)} AND f.filterType = '{ftype}' "
        f"AND d.psfFlux > {MIN_PSF_FLUX} AND d.psfQfPerfect >= {MIN_PSF_QF_PERFECT} "
        f"ORDER BY d.obsTime"
    )


def detection_lightcurve_description(
    *,
    obj_id: int,
    filter_name: str,
    lookup_name: str | None = None,
) -> str:
    """Builds TABLE description text for a PS1 detection lightcurve.

    ``format_ps1_object_name`` labels the object (``PS1 <objID>``); the numeric
    ``objID`` is the archive primary key.

    Args:
        obj_id (int): Pan-STARRS mean object identifier.
        filter_name (str): Single-letter PS1 filter code.
        lookup_name (str, optional): Simbad or user label when association applies.

    Returns:
        str: VO TABLE description paragraph.
    """
    obj_label = format_ps1_object_name(obj_id)
    text = (
        f"Pan-STARRS1 DR2 {DETECTION_PHOTOMETRY_TYPE} photometry lightcurve for "
        f"{obj_label} (objID {int(obj_id)}), filter={filter_name}."
    )
    if lookup_name and str(lookup_name).strip():
        text = f"{text} Associated with lookup name {str(lookup_name).strip()}."
    return text


def photcal_dict_for_band(band: Ps1BandSpec) -> dict[str, object]:
    """Returns PhotCal-style metadata for one PS1 band.

    Args:
        band (Ps1BandSpec): Band specification.

    Returns:
        dict: Zero-point metadata for export and magnitude view.
    """
    return {
        "filterIdentifier": band.filter_identifier,
        "filterName": band.filter_name,
        "magnitudeSystem": MAG_SYSTEM,
        "zeroPointFlux": AB_REFERENCE_FLUX_JY,
        "zeroPointFluxUnit": "Jy",
        "zeroPointReferenceMagnitude": 0.0,
        "zeroPointReferenceMagnitudeUnit": "mag",
        "effectiveWavelength": band.effective_wavelength_angstrom * 1e-10,
        "effectiveWavelengthUnit": "m",
    }
