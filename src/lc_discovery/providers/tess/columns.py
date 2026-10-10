"""TESS archive flux and background columns issued in Discovery VOTables.

Column roles for the reviewed TESS pipelines. A caller may import this
module as plain data. Kepler rows are omitted: this provider searches ``mission='TESS'``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

CALIBRATION_PHYSICAL = "physical"
CALIBRATION_NORMALIZED_CATALOG = "normalized_catalog"

ZP_MAG_TESSMAG = "TESSMAG"
ZP_MAG_GAIAMAG = "GAIAMAG"


@dataclass(frozen=True)
class FluxColumnSpec:
    """Photometry flux / flux-error pair for one pipeline sector range."""

    flux_col: str
    flux_err_col: Optional[str]
    calibration: str
    zp_mag_source: Optional[str]
    sector_min: Optional[int] = None
    sector_max: Optional[int] = None
    notes: str = ""


@dataclass(frozen=True)
class BackgroundColumnSpec:
    """Per-cadence background column delivered with a pipeline product."""

    bkg_col: str
    bkg_err_col: Optional[str]
    unit_type: str
    notes: str = ""


class UnknownPipelineError(RuntimeError):
    """Raised when the author/pipeline is not in the registry."""


FLUX_COLUMN_REGISTRY: dict[str, list[FluxColumnSpec]] = {
    "SPOC": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX",
            flux_err_col="PDCSAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Systematics-corrected aperture photometry, e-/s.",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Uncorrected aperture photometry, e-/s.",
        ),
    ],
    "TESS-SPOC": [
        FluxColumnSpec(
            flux_col="PDCSAP_FLUX",
            flux_err_col="PDCSAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Same convention as SPOC PDCSAP_FLUX; e-/s.",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Same convention as SPOC SAP_FLUX; e-/s.",
        ),
    ],
    "QLP": [
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_TESSMAG,
            sector_min=1,
            sector_max=55,
            notes="Un-detrended flux, dimensionless, catalogue-anchored.",
        ),
        FluxColumnSpec(
            flux_col="KSPSAP_FLUX",
            flux_err_col="KSPSAP_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_TESSMAG,
            sector_min=1,
            sector_max=55,
            notes="Detrended flux (Lightkurve default for QLP S1–55).",
        ),
        FluxColumnSpec(
            flux_col="SAP_FLUX",
            flux_err_col="SAP_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_TESSMAG,
            sector_min=56,
            sector_max=None,
            notes="Un-detrended flux, dimensionless (S56+).",
        ),
        FluxColumnSpec(
            flux_col="DET_FLUX",
            flux_err_col="DET_FLUX_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_TESSMAG,
            sector_min=56,
            sector_max=None,
            notes="Detrended flux (Lightkurve default for QLP S56+).",
        ),
        FluxColumnSpec(
            flux_col="SYS_RM_FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_TESSMAG,
            sector_min=56,
            sector_max=None,
            notes="Systematics removed; no dedicated error column.",
        ),
    ],
    "TARS": [
        FluxColumnSpec(
            flux_col="FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_TESSMAG,
            notes="CPM-corrected normalised FFI flux; dimensionless; no error column.",
        ),
    ],
    "TASOC": [
        FluxColumnSpec(
            flux_col="FLUX_CORR",
            flux_err_col="FLUX_CORR_ERR",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=None,
            notes="CBV-corrected residual; FITS unit ppm, stored as dimensionless.",
        ),
        FluxColumnSpec(
            flux_col="FLUX_RAW",
            flux_err_col="FLUX_RAW_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Raw aperture photometry, e-/s. No 20.44 instrument pair.",
        ),
    ],
    "TGLC": [
        FluxColumnSpec(
            flux_col="cal_psf_flux",
            flux_err_col="cal_psf_flux_err",
            calibration=CALIBRATION_NORMALIZED_CATALOG,
            zp_mag_source=ZP_MAG_GAIAMAG,
            notes="PSF-fit flux calibrated against Gaia photometry.",
        ),
    ],
    "GSFC-ELEANOR-LITE": [
        FluxColumnSpec(
            flux_col="CORR_FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Systematics-corrected aperture photometry, e-/s. No 20.44.",
        ),
        FluxColumnSpec(
            flux_col="RAW_FLUX",
            flux_err_col="FLUX_ERR",
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="Uncorrected aperture photometry; FLUX_ERR applies to RAW_FLUX.",
        ),
        FluxColumnSpec(
            flux_col="PCA_FLUX",
            flux_err_col=None,
            calibration=CALIBRATION_PHYSICAL,
            zp_mag_source=None,
            notes="PCA-detrended flux; no dedicated error column.",
        ),
    ],
}

BACKGROUND_COLUMN_REGISTRY: dict[str, BackgroundColumnSpec] = {
    "SPOC": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Sky/aperture background, e-/s.",
    ),
    "TESS-SPOC": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Sky/aperture background, e-/s.",
    ),
    "QLP": BackgroundColumnSpec(
        bkg_col="SAP_BKG",
        bkg_err_col="SAP_BKG_ERR",
        unit_type=CALIBRATION_NORMALIZED_CATALOG,
        notes="Difference-imaging background; dimensionless, may be negative.",
    ),
    "TASOC": BackgroundColumnSpec(
        bkg_col="FLUX_BKG",
        bkg_err_col="FLUX_BKG_ERR",
        unit_type=CALIBRATION_PHYSICAL,
        notes="Background level, e-/s. Error column optional.",
    ),
    "GSFC-ELEANOR-LITE": BackgroundColumnSpec(
        bkg_col="FLUX_BKG",
        bkg_err_col=None,
        unit_type=CALIBRATION_PHYSICAL,
        notes="Per-cadence background; e-/s heritage via Lightkurve reader.",
    ),
}


def normalize_lc_column(name: str) -> str:
    """Normalises a column name to lowercase Lightkurve convention.

    Args:
        name (str): Registry or FITS column name.

    Returns:
        str: Lowercase column name.
    """
    return str(name).strip().lower()


def parse_sector_from_mission_label(mission_label: str) -> int | None:
    """Extracts a TESS sector number from a MAST/Lightkurve mission label.

    Args:
        mission_label (str): Row ``mission`` field, e.g. ``TESS Sector 16``.

    Returns:
        int or None: Parsed sector number.
    """
    if not mission_label:
        return None
    match = re.search(r"Sector\s+(\d+)", str(mission_label), re.IGNORECASE)
    return int(match.group(1)) if match else None


def _sector_ok(spec: FluxColumnSpec, sector: Optional[int]) -> bool:
    """Returns whether a flux spec applies to the given sector.

    Args:
        spec (FluxColumnSpec): Registry entry.
        sector (int, optional): TESS sector.

    Returns:
        bool: True when the sector is in range or unrestricted.
    """
    if sector is None:
        return True
    if spec.sector_min is not None and sector < spec.sector_min:
        return False
    if spec.sector_max is not None and sector > spec.sector_max:
        return False
    return True


def list_photometry_specs(author: str, sector: Optional[int] = None) -> list[FluxColumnSpec]:
    """Lists registry photometry specs for an author and optional sector.

    Args:
        author (str): Pipeline author tag.
        sector (int, optional): TESS sector number.

    Returns:
        list[FluxColumnSpec]: Matching registry entries in declaration order.

    Raises:
        UnknownPipelineError: When ``author`` is absent from the registry.
    """
    if author not in FLUX_COLUMN_REGISTRY:
        raise UnknownPipelineError(
            f"Pipeline/author '{author}' is not in the TESS archive registry. "
            f"Known pipelines: {sorted(FLUX_COLUMN_REGISTRY)}."
        )
    return [spec for spec in FLUX_COLUMN_REGISTRY[author] if _sector_ok(spec, sector)]


ROLE_TIME = "time"
ROLE_FLUX = "flux"
ROLE_ERROR = "error"
ROLE_BACKGROUND = "background"
ROLE_BACKGROUND_ERROR = "background_error"


def is_known_author(author: str) -> bool:
    """Returns whether ``author`` is in the reviewed flux registry.

    Args:
        author (str): Pipeline author tag.

    Returns:
        bool: True when photometry specs exist for this author.
    """
    return str(author).strip() in FLUX_COLUMN_REGISTRY


def known_role_names() -> dict[str, set[str]]:
    """Returns column names per role, collected from all registered authors.

    Args:
        None.

    Returns:
        dict[str, set[str]]: Lowercase names for time, flux, error,
        background, and background error.
    """
    flux: set[str] = set()
    error: set[str] = set()
    background: set[str] = set()
    background_error: set[str] = set()
    for specs in FLUX_COLUMN_REGISTRY.values():
        for spec in specs:
            flux.add(normalize_lc_column(spec.flux_col))
            if spec.flux_err_col:
                error.add(normalize_lc_column(spec.flux_err_col))
    for spec in BACKGROUND_COLUMN_REGISTRY.values():
        background.add(normalize_lc_column(spec.bkg_col))
        if spec.bkg_err_col:
            background_error.add(normalize_lc_column(spec.bkg_err_col))
    return {
        ROLE_TIME: {"time"},
        ROLE_FLUX: flux,
        ROLE_ERROR: error,
        ROLE_BACKGROUND: background,
        ROLE_BACKGROUND_ERROR: background_error,
    }


def background_role_for_name(name: str) -> str | None:
    """Classifies a column name as background or background error.

    Only background is recognised by name. Flux and error roles of unknown
    authors come from Lightkurve's own ``flux`` / ``flux_err`` declaration.

    Args:
        name (str): Column name from the downloaded product.

    Returns:
        str or None: ``ROLE_BACKGROUND``, ``ROLE_BACKGROUND_ERROR``, or ``None``.
    """
    key = normalize_lc_column(name)
    roles = known_role_names()
    if key in roles[ROLE_BACKGROUND_ERROR]:
        return ROLE_BACKGROUND_ERROR
    if key in roles[ROLE_BACKGROUND]:
        return ROLE_BACKGROUND
    return None


def is_spoc_family_flux_unit(unit) -> bool:
    """Returns whether a unit is electron s-1 or counts per second.

    SPOC / TESS-SPOC store photoelectrons per second (``electron s-1``,
    ``e-/s``). Unknown authors also treat counts per second as that family.

    Args:
        unit: Lightkurve/Astropy unit or unit string.

    Returns:
        bool: True when 20.44 may be attached to a flux-role column.
    """
    if unit is None:
        return False
    compact = str(unit).lower().replace(" ", "").replace("⁻", "-")
    if "electron" in compact and ("s-1" in compact or "/s" in compact):
        return True
    if any(token in compact for token in ("e-/s", "e/s", "es-1")):
        return True
    if ("count" in compact or compact.startswith("ct")) and (
        "s-1" in compact or "/s" in compact
    ):
        return True
    return False


def get_background_spec(author: str) -> BackgroundColumnSpec | None:
    """Returns the background column spec for a pipeline, if any.

    Args:
        author (str): Pipeline author tag from Lightkurve.

    Returns:
        BackgroundColumnSpec or None: Background metadata when registered.
    """
    return BACKGROUND_COLUMN_REGISTRY.get(author)


def list_present_photometry_specs(
    author: str,
    sector: Optional[int],
    colnames: Sequence[str],
) -> list[FluxColumnSpec]:
    """Lists photometry specs whose flux column is present in the product.

    Args:
        author (str): Pipeline author tag.
        sector (int, optional): TESS sector number.
        colnames (Sequence[str]): Column names on the downloaded light curve.

    Returns:
        list[FluxColumnSpec]: Specs whose flux column exists.

    Raises:
        UnknownPipelineError: When ``author`` is absent from the registry.
    """
    present = {normalize_lc_column(name) for name in colnames}
    return [
        spec
        for spec in list_photometry_specs(author, sector)
        if normalize_lc_column(spec.flux_col) in present
    ]
