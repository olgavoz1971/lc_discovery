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

The issued product is a fully calibrated light curve in VOTable format.

`volightcurve`, `CurveDash`, and `lc_bridge` belong to the Dash
application, not to this product. At each provider review, check the pass
from Lightcurve Discovery to the Dash application: the VOTable that
discovery issues, and what the application does with it after that.

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
