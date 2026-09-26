# OGLE OCVS (`ogle_ocvs`)

Expands [schema.md](../schema.md).

## 1. Discovery

TAP `https://skvo.science.upjs.sk/tap`, ADQL 2.1.

Object lookup:

```sql
SELECT object_id, accref, ssa_dstitle, ssa_bandpass, ssa_targname, ssa_targclass,
       ssa_location, ssa_length, ssa_collection, t_min, t_max, mean_mag
FROM ogle.ts_ssa
WHERE object_id = '<object_id>'
```

Cone search. `radius_deg` is the requested radius in degrees. `TOP` is the catalogue row limit.

```sql
SELECT TOP <row_limit> object_id, accref, ssa_dstitle, ssa_bandpass, ssa_targname,
       ssa_targclass, ssa_location, ssa_length, ssa_collection, t_min, t_max, mean_mag
FROM ogle.ts_ssa
WHERE 1 = CONTAINS(ssa_location, CIRCLE(<ra_deg>, <dec_deg>, <radius_deg>))
```

When a time window is set, both queries add `AND t_min > <time_start_mjd>` and `AND t_max < <time_end_mjd>`. Either bound may be absent.

## 2. Retrieval

The points are not in the TAP result. Retrieval downloads the `accref` URL from the selected SSA row.

## 3. What we change

The archive table name, description, and column names are kept. The
published flux zero point is kept.

When `photDM:PhotometryFilter.identifier` is one of the identifiers below
and the photcal group has no magnitude zero point, `zeroPointReferenceMagnitude`
is set to `0.0` mag. A magnitude zero point the archive already published
is left as it is. An identifier that is not listed is left unchanged.

| Filter identifier | `zp_mag` |
|-------------------|----------|
| `Generic/Bessell.U` | `0.0` mag |
| `Generic/Bessell.B` | `0.0` mag |
| `Generic/Bessell.V` | `0.0` mag |
| `Generic/Bessell.R` | `0.0` mag |
| `Generic/Bessell.I` | `0.0` mag |

Facility is set to `Las Campanas` and instrument to `Warsaw 1.3m Telescope`,
from this provider's config. The archive product does not carry those names.

When the product has one photcal group, an error column that does not
already reference a photcal receives that group's id. If the group has no
id, the id `photcal` is set so the reference can be written. An error
column the archive already linked is left as it is. Several photcal groups
are left unlinked.

The folding `epoch` parameter keeps its published MJD value, the same
origin as the time column (`timeorigin` `2400000.5`). It receives `ref="ts"`.
