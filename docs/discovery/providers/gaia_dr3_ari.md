# Gaia DR3 ARI (`gaia_dr3_ari`)

Expands [schema.md](../schema.md).

## 1. Discovery

TAP `https://gaia.ari.uni-heidelberg.de/tap`, ADQL 2.0. Time bounds are not applied.

Source lookup:

```sql
SELECT TOP 1 gs.source_id, gs.ra, gs.dec, gs.phot_g_mean_mag, vcr.best_class_name
FROM gaiadr3.gaia_source AS gs
LEFT JOIN gaiadr3.vari_classifier_result AS vcr
ON gs.source_id = vcr.source_id
WHERE gs.has_epoch_photometry = 'True'
AND gs.source_id = <source_id>
ORDER BY random_index
```

Cone search (`radius_deg` is the cone radius in degrees; `TOP` is the catalogue row limit):

```sql
SELECT TOP <row_limit> gs.source_id, gs.ra, gs.dec, gs.phot_g_mean_mag, vcr.best_class_name
FROM gaiadr3.gaia_source AS gs
LEFT JOIN gaiadr3.vari_classifier_result AS vcr
ON gs.source_id = vcr.source_id
WHERE gs.has_epoch_photometry = 'True'
AND 1 = CONTAINS(POINT('ICRS', gs.ra, gs.dec),
CIRCLE('ICRS', <ra_deg>, <dec_deg>, <radius_deg>))
ORDER BY random_index
```

Each TAP row becomes three catalogue rows, one per band: Gaia G (`table_id` 0), Gaia BP (`table_id` 1), Gaia RP (`table_id` 2). The points are not in the TAP result.

## 2. Retrieval

`fetch_lightcurve` downloads

`https://gaia.ari.uni-heidelberg.de/timeseries/gaiadr3?sourceid=<source_id>`.

That product is one VOTable with the three band tables. The catalogue `table_id` selects one table.

## 3. What we change

The issued product is that one table. The other band tables are removed. The archive table name and description are kept.

Columns `source_id`, `band`, and `pf` are removed. `source_id` is already the TABLE parameter `source_id`. `band` is fixed by the selected table. `pf` is copied to a TABLE parameter `period` and the column is removed. These columns repeat the same value on every row, so dropping them saves space.

`mag` keeps the published flux zero point in Jy. `zeroPointReferenceMagnitude` is set to `0.0` mag.

`flux` and `flux_error` are given a separate photcal. The Jy flux zero point is replaced by `1` in the unit of the `flux` column (`s**-1`). The magnitude zero points on that photcal are from Riello et al. 2021, A&A 649, A3:

| Filter identifier | `zp_mag` |
|-------------------|----------|
| `GAIADR3.G` | `25.6874` mag |
| `GAIADR3.Gbp` | `25.3385` mag |
| `GAIADR3.Grp` | `24.7479` mag |

`flux_over_error` is left without a photcal. The `flux_error` column unit stays as published. The other columns of the selected table are kept.
