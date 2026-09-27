# ASAS-SN (`asassn`)

Expands [schema.md](../schema.md). Discovery and retrieval only. Enrichment is not reviewed here.

## 1. Discovery

Sky Patrol client `pyasassn.client.SkyPatrolClient`, catalogue `stellar_main`. Time bounds are not applied. The columns requested are `asas_sn_id`, `ra_deg`, `dec_deg`, `pstarrs_g_mag`. `download=False`.

Gaia id lookup:

```text
query_list([<gaia_id>], id_col="gaia_id", catalog="stellar_main",
           cols=["asas_sn_id", "ra_deg", "dec_deg", "pstarrs_g_mag"],
           download=False)
```

A target name that is not a Gaia id uses `simbad_lookup(<name>, download=False)`, then the same `query_list` with `id_col="asas_sn_id"`.

Cone search (`radius` is in arcseconds):

```text
cone_search(<ra_deg>, <dec_deg>, <radius>, units="arcsec",
            catalog="stellar_main",
            cols=["asas_sn_id", "ra_deg", "dec_deg", "pstarrs_g_mag"],
            download=False)
```

Each metadata row becomes two catalogue rows, `g` and `V`. The catalogue does not say which of those filters the source has. The points are not in this result.

## 2. Retrieval

`fetch_lightcurve` downloads every band for that `asas_sn_id`, then keeps the catalogue band:

```text
query_list([<asas_sn_id>], id_col="asas_sn_id", catalog="stellar_main",
           download=True)
```

The photometry table is filtered with `phot_filter = 'g'` or `phot_filter = 'V'`. Columns kept are `jd`, `flux`, `flux_err`, and `camera` when that column is present. A row is removed when `jd` or `flux` is missing. A missing `flux_err` does not remove the row.

Folding epoch and period are auxiliary. They come from:

```sql
SELECT epoch, period FROM aavsovsx WHERE asas_sn_id = <asas_sn_id> LIMIT 1
```

If that query fails or returns nothing, epoch and period stay empty.

The object's sky position is loaded again from `stellar_main` (`query_list`, `id_col="asas_sn_id"`, columns `ra_deg` and `dec_deg`, `download=False`). That is the source position already returned at discovery, not the cone centre. The fetch key holds only `asas_sn_id` and `band`, so retrieval does not read the catalogue row. Agreed: this second query repeats coordinates the catalogue row already has.

## 3. What we change

Sky Patrol returns a photometry table, not a VOTable. The plugin writes one VOTable for the selected band and returns those bytes.

- Columns stay `jd`, `flux`, `flux_err`, and `camera` when the download has it.
- A row is removed when `jd` or `flux` is missing. A missing `flux_err` is an empty cell and shares the photcal group.
- `flux` and `flux_err` are divided by 1000. The column unit is `Jy`. The download unit is mJy.
- One photcal group. `g` uses `SLOAN/SDSS.g`, AB, flux zero point `3631` Jy, wavelength `467.2e-9` m. `V` uses `Generic/Johnson.V`, Vega, flux zero point `3836.3` Jy, wavelength `546.8e-9` m. Magnitude zero point `0.0` mag on both.
- Time numbers stay in `jd`. Timescale `UTC`, reference position `HELIOCENTER`, time origin `0`.
- Table name is `ASAS-SN <asas_sn_id> <filter identifier>`. There is no archive table name. No description is added.
- `asas_sn_id`, and `ra` and `dec` when the second lookup returns them, are table parameters. `period` and `epoch` are table parameters only when `aavsovsx` returns them. `epoch` has `ref="ts"`, the same TIMESYS as `jd`. The value stays a full JD, matching `timeorigin` `0`.
