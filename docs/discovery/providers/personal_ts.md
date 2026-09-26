# Personal collections (`personal_ts`)

Expands [schema.md](../schema.md).

## 1. Discovery

TAP `https://skvo.science.upjs.sk/tap`, ADQL 2.1.

Object lookup:

```sql
SELECT object_id, accref, ssa_bandpass, ssa_targname, ssa_targclass,
       ssa_location, ssa_length, ssa_collection, t_min, t_max, mean_mag
FROM personal.ts_ssa
WHERE object_id = '<object_id>'
```

Cone search. `radius_deg` is the requested radius in degrees. `TOP` is the catalogue row limit.

```sql
SELECT TOP <row_limit> object_id, accref, ssa_bandpass, ssa_targname, ssa_targclass,
       ssa_location, ssa_length, ssa_collection, t_min, t_max, mean_mag
FROM personal.ts_ssa
WHERE 1 = CONTAINS(ssa_location, CIRCLE(<ra_deg>, <dec_deg>, <radius_deg>))
```

When a time window is set, both queries add `AND t_min > <time_start_mjd>` and `AND t_max < <time_end_mjd>`. Either bound may be absent.

A name is resolved on `personal.objects` before the SSA lookup. That query does not return the light curve.

```sql
SELECT object_id, identifiers
FROM personal.objects
WHERE object_id = '<object_id>'
```

```sql
SELECT object_id, identifiers
FROM personal.objects
WHERE identifiers LIKE '%<fragment>%'
```

## 2. Retrieval

The points are not in the TAP result. Retrieval downloads the `accref` URL from the selected SSA row.

## 3. What we change

Every product of this provider. The magnitude zero point is `0.0` mag when
the file has none and `photDM:PhotometryFilter.identifier` is one of
`Generic/Bessell.U`, `Generic/Bessell.B`, `Generic/Bessell.V`,
`Generic/Bessell.R`, `Generic/Bessell.I`, `Palomar/Arp1961.103aO_atm`.
Any other identifier is left unchanged. A magnitude zero point the archive
already published is left as it is. The flux zero point stays as published.
The archive table name, description, and column names are kept.

When the product has one photcal group, an error column that does not
already reference a photcal receives that group's id. If the group has no
id, the id `photcal` is set so the reference can be written. An error
column the archive already linked is left as it is. Several photcal groups
are left unlinked.

When a folding `epoch` parameter is present, its published value stays.
That value is MJD, the same origin as the time column (`timeorigin`
`2400000.5`). It receives `ref="ts"`.
