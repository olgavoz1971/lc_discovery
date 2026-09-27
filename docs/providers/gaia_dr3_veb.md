# Gaia DR3 VEB (`gaia_dr3_veb`)

Expands [schema.md](../schema.md). Not yet reviewed against the contract.

## 1. Discovery

TAP `https://skvo.science.upjs.sk/tap`, ADQL 2.1.

Source lookup:

```sql
SELECT accref, ssa_bandpass, ssa_dstitle, ssa_targname, ssa_targclass,
       ssa_location, ssa_length, ssa_creator, ssa_collection, t_min, t_max
FROM gaiadr3_eb.ts_ssa
WHERE source_id = <source_id>
```

Cone search. `radius_deg` is the requested radius in degrees. `TOP` is the catalogue row limit.

```sql
SELECT TOP <row_limit> accref, ssa_bandpass, ssa_dstitle, ssa_targname, ssa_targclass,
       ssa_location, ssa_length, ssa_creator, ssa_collection, t_min, t_max
FROM gaiadr3_eb.ts_ssa
WHERE 1 = CONTAINS(ssa_location, CIRCLE(<ra_deg>, <dec_deg>, <radius_deg>))
```

When a time window is set, both queries add `AND t_min > <time_start_mjd>` and `AND t_max < <time_end_mjd>`. Either bound may be absent.

## 2. Retrieval

The points are not in the TAP result. Retrieval downloads the `accref` URL from the selected SSA row.

## 3. What we change

The flux column is in electron/s (`s**-1`). The file carries a flux zero
point in Jy. That value and its unit are discarded for the filters below.
The flux zero point is set to `1` `s**-1`. The magnitude zero points are
from Riello et al. 2021, A&A 649, A3 (2021A&A...649A...3R):

| Filter identifier | `zp_mag` |
|-------------------|----------|
| `GAIA/GAIA3.G` | `25.6874` mag |
| `GAIA/GAIA3.Gbp` | `25.3385` mag |
| `GAIA/GAIA3.Grp` | `24.7479` mag |

The archive table name and description are kept. Facility is set to
`Gaia` and instrument to `Gaia`, from this provider's config. The
archive product does not carry those names.

An error column that does not already reference a photcal receives the
photcal of the single magnitude or flux column that has one. An error
column the archive already linked is left as it is.

The folding `epoch` parameter keeps its published value, already
`JD-2455197.5` like the time column. It receives `ref="ts"`.
