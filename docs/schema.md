# Discovery schema

Project-wide process. Provider notes under `providers/` add only the
details of one provider. The rules below are the base. They grow when a
provider is reviewed. They are not a licence to change a product for a
reason that is not written in that provider's note.

## Objective

The package issues a light curve that is consistent with VO standards.
Many providers supply a looser product than that. The work of this
package is to reach the VO product without discarding a description that
is already adequate.

## Product

The issued product is a fully calibrated light curve in **VOTable bytes**.

Several photometry columns (flux, magnitude, background) are allowed. Each
target-photometry column that this package calibrates has a PhotCal GROUP.
Column roles are UCDs, not a forced `obs_time` / `phot` spelling.

The caller parses the VOTable and may choose one working series. That choice
is not this package’s fetch step. At each provider review, check the VOTable
this package issues.

## Catalogue extra columns (locked)

The core search table is a **closed** list of required and optional names
(see [mission_lightcurve_providers.md section 4](mission_lightcurve_providers.md)).
The contract does **not** grow TESS-shaped fields (`sector`, `author`,
`exptime`, “archive product”). Mission-specific facts must not be added to
that list.

A provider may declare **extra catalogue columns**. Default: **none**.

Each extra column has:

- a **field** id used as the table row key
- a **header** chosen by the provider (British English)
- a **value on every catalogue row** (string is enough)

Rules:

- Extra field ids must not duplicate a core required or optional name.
- Extra names are allowed on the catalogue table **only when declared**.
- The core schema does not interpret the values.
- `lc_key` is not a display column and is not an extra column.
- A caller that shows a results table draws the standard columns, then
  **appends** whatever that mission declared. It must not hard-code Sector,
  Author, or any other mission label.
- Declaration lives with the provider (capabilities / descriptor), so the
  table headers exist when the mission is selected, not because a cell
  happened to be filled.

TESS uses this hook for three extras: `Sector` (`16`), `Exp` (`120s`),
and `Author` (`SPOC`). That choice is TESS-only. See
[providers/tess.md](providers/tess.md).

## Working photometry series

An issued VOTable may contain several flux, magnitude, or background
columns. Choosing one working series is the caller's task, using the UCDs and
PhotCal groups in the document. Fetch must not collapse the VOTable to one
series.

## Process

### 1. Discover

Search returns catalogue rows. A row identifies one light curve. It does
not contain the points.

### 2. Retrieve

Fetch loads the product for one catalogue row.

### 3. Enrich

Enrich is the only step that may change the retrieved product.

Keep the original description and the original calibration wherever that
description already meets the VO product. Change the calibration only
when the published product does not. Every such change, and the reason
for it, is written in that provider's note: what changed, on which
column, the value, the unit, and the source. A change that is not in the
note is not made.
