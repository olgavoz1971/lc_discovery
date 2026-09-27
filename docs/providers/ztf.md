# ZTF DR24 (`ztf_dr24`)

Expands [schema.md](../schema.md). Discovery and retrieval only. Enrichment is not reviewed here.

Discovery uses IRSA TAP through `astroquery.ipac.irsa.Irsa.query_tap`, table `ztf_objects_dr24`. Time bounds are not applied. The cone is limited to 1 degree.

## 1. Discovery

OID lookup:

```sql
SELECT oid, ra, dec, filtercode, nobsrel, meanmag
FROM ztf_objects_dr24
WHERE oid = <oid>
```

Cone search. `radius_deg` is the requested radius in degrees. The query has no `TOP`. Rows are truncated in Python after the service returns.

```sql
SELECT oid, ra, dec, filtercode, nobsrel, meanmag
FROM ztf_objects_dr24
WHERE CONTAINS(POINT('ICRS', ra, dec),
               CIRCLE('ICRS', <ra_deg>, <dec_deg>, <radius_deg>)) = 1
```

A row with `nobsrel` missing, not numeric, or not greater than 0 is omitted. Each remaining TAP row is one catalogue row. The filter is `filtercode` (`zg`, `zr`, or `zi`). The points are not in this result. The fetch key stores `oid` only.

## 2. Retrieval

The catalogue row already has `filtercode`, `ra`, and `dec`. Retrieval does not read them. It asks IRSA for that OID a second time, with the same query as the discovery OID lookup:

```sql
SELECT oid, ra, dec, filtercode, nobsrel, meanmag
FROM ztf_objects_dr24
WHERE oid = <oid>
```

`filtercode`, `ra`, and `dec` are taken from the first row of that result. An OID can have more than one filter, so this first row may not be the filter of the catalogue row that was opened.

The points come from a separate download, `ztfquery.lightcurve.LCQuery.from_id(<oid>)`. That is not an ADQL query. The default keeps every epoch. The other quality, `bad_catflags`, drops an epoch when `catflags` has bit 15 set (mask `32768`).

The download columns, from the CSV header, are `oid`, `expid`, `hjd`, `mjd`, `mag`, `magerr`, `catflags`, `filtercode`, `ra`, `dec`, `chi`, `sharp`, `filefracday`, `field`, `ccdid`, `qid`, `limitmag`, `magzp`, `magzprms`, `clrcoeff`, `clrcounc`, `exptime`, `airmass`, `programid`. There is no `hmjd` column.

## 3. What we change

The issued light curve keeps one time column: `hjd` when the download has it, otherwise `hmjd`. A row is removed when that time or `mag` is missing. A missing `magerr` stays an empty `mag_err` cell.

`magerr` is written as `mag_err`. `catflags` is written as `catflag`. The other kept names are unchanged. The download is the IRSA VOTable. Each kept column copies the `ucd`, unit, datatype, and description from the IRSA FIELD of the source column. Those values are not set in this plugin. `hmjd` is not in that file, so a `hmjd` column has no UCD and no description unless IRSA supplies them.

`mag` and `mag_err` share the photcal group. Filter identifiers are `Palomar/ZTF.g`, `Palomar/ZTF.r`, and `Palomar/ZTF.i`. Magnitude system AB, flux zero point `3631` Jy, magnitude zero point `0.0` mag.
