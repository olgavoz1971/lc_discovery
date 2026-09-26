# Gaia DR3 AIP (`gaia_dr3_aip`)

Expands [schema.md](../schema.md).

## 1. Discovery

TAP `https://gaia.aip.de/tap`, ADQL 2.0. Time bounds are not applied.

Source lookup:

```sql
SELECT gs.source_id, gs.ra, gs.dec, gs.phot_g_mean_mag, vcr.best_class_name
FROM gaiadr3.gaia_source_lite AS gs
LEFT JOIN gaiadr3.vari_classifier_result AS vcr
ON gs.source_id = vcr.source_id
WHERE gs.source_id = <source_id> AND gs.has_epoch_photometry = 'True'
```

Cone search (`radius_deg` is the cone radius in degrees; `TOP` is the catalogue row limit):

```sql
SELECT TOP <row_limit> gs.source_id, gs.ra, gs.dec, gs.phot_g_mean_mag, vcr.best_class_name
FROM gaiadr3.gaia_source_lite AS gs
LEFT JOIN gaiadr3.vari_classifier_result AS vcr
ON gs.source_id = vcr.source_id
WHERE gs.has_epoch_photometry = 'True'
AND 1 = CONTAINS(POINT('ICRS', gs.ra, gs.dec),
CIRCLE('ICRS', <ra_deg>, <dec_deg>, <radius_deg>))
ORDER BY gs.random_index
```

Each TAP row becomes three catalogue rows: Gaia G, Gaia BP, and Gaia RP. The points are not in this result.

## 2. Retrieval

`fetch_lightcurve` runs this query on the same TAP service:

```sql
SELECT source_id, g_transit_time, g_transit_flux_over_error, g_transit_mag,
       g_transit_n_obs, bp_obs_time, bp_flux_over_error, bp_mag,
       rp_obs_time, rp_flux_over_error, rp_mag
FROM gaiadr3.epoch_photometry
WHERE source_id IN (<source_id>)
```

The catalogue band selects one time column and one magnitude column from that row.

## 3. What we change

The issued product is one band. The arrays of that band are expanded into one row per epoch, in the published order. A row is removed when its time or its magnitude is NaN. A NaN flux-over-error does not remove the row; that magnitude error stays empty. The other bands' columns are removed.

The band prefix is removed from the column names: `g_transit_time` becomes `transit_time`, `g_transit_mag` becomes `transit_mag`, `g_transit_flux_over_error` becomes `transit_flux_over`, and `g_transit_n_obs` becomes `transit_n_obs`. BP and RP follow the same rule, so `bp_obs_time` becomes `obs_time` and `bp_mag` becomes `mag`.

`source_id` is copied to a TABLE parameter and the column is removed. It is one value for the whole product, so the column is dropped to save space. The time numbers stay in days.

The TABLE name is set to `Gaia DR3 <source_id> <filter identifier>`. The TAP job name is replaced because it does not carry the source or the filter.

`mag_error` is added from the flux-over-error column by Pogson error propagation, `σ_m = (2.5 / ln(10)) / (F / σ_F)`. A non-positive or non-finite ratio is left empty.

The magnitude column receives a photcal. The magnitude zero point is `0.0` mag. The flux zero point and the filter parameters are the short values from the Filter Profile Service, as printed on the reference light curves:

| Filter identifier | `zp_flux` | Effective wavelength |
|-------------------|-----------|----------------------|
| `GAIA/GAIA3.G` | `3228.75` Jy | `5.82e-7` m |
| `GAIA/GAIA3.Gbp` | `3552.01` Jy | `5.04e-7` m |
| `GAIA/GAIA3.Grp` | `2554.95` Jy | `7.62e-7` m |

The magnitude system is Vega. There is no flux column in this product, so no flux photcal is added.
