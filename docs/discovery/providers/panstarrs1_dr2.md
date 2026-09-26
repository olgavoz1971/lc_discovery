# Pan-STARRS1 DR2 (`panstarrs1_dr2`)

Expands [schema.md](../schema.md). Discovery and retrieval only. Enrichment is not reviewed here.

TAP `https://mast.stsci.edu/vo-tap/api/v0.1/ps1dr2/`, ADQL 2.1. Time bounds are not applied. The cone is limited to 0.24 degrees.

## 1. Discovery

`objID` lookup:

```sql
SELECT objID, raMean, decMean, nDetections, ng, nr, ni, nz, ny,
       gMeanPSFMag, rMeanPSFMag, iMeanPSFMag, zMeanPSFMag, yMeanPSFMag
FROM dbo.MeanObjectView
WHERE objID = <obj_id>
```

Cone search. `radius_deg` is the requested radius in degrees. `TOP` is the catalogue row limit.

```sql
SELECT TOP <row_limit> objID, raMean, decMean, nDetections, ng, nr, ni, nz, ny,
       gMeanPSFMag, rMeanPSFMag, iMeanPSFMag, zMeanPSFMag, yMeanPSFMag
FROM dbo.MeanObjectView
WHERE CONTAINS(POINT('ICRS', raMean, decMean),
               CIRCLE('ICRS', <ra_deg>, <dec_deg>, <radius_deg>)) = 1
  AND nDetections > 1
ORDER BY randomId
```

One mean-object row becomes one catalogue row per filter `g`, `r`, `i`, `z`, `y` whose count (`ng`, `nr`, `ni`, `nz`, `ny`) is at least 1. The points are not in this result. Filters `w` and `open` are not catalogued.

## 2. Retrieval

One TAP query for the catalogue `objID` and filter:

```sql
SELECT d.objID, d.obsTime, d.psfFlux, d.psfFluxErr, d.psfQfPerfect, m.epochMean
FROM dbo.Detection AS d
NATURAL JOIN dbo.Filter AS f
INNER JOIN dbo.MeanObjectView AS m ON d.objID = m.objID
WHERE d.objID = <obj_id>
  AND f.filterType = '<filter>'
  AND d.psfFlux > 0.0
  AND d.psfQfPerfect >= 0.9
ORDER BY d.obsTime
```

`obsTime` is MJD. `epochMean` is the mean detection epoch in MJD. It is the coordinate epoch (`COOSYS`), not a folding epoch. There is no folding `epoch` parameter.

The time scale is TAI and the reference position is topocentric. That comes from the MAST PS1 FAQ, "PS1 FAQ – Frequently asked questions", https://outerspace.stsci.edu/spaces/PANSTARRS/pages/298812205/PS1+FAQ+-+Frequently+asked+questions and from Flewelling et al., "The Pan-STARRS1 Database and Data Products", The Astrophysical Journal Supplement Series, Volume 251, Issue 1, id.7, 62 pp., bibcode 2020ApJS..251....7F.

## 3. What we change

The TAP result is a table of detections, not a light-curve VOTable. The issued product is one VOTable for the selected filter.

- Columns: `obsTime` becomes `obs_time`, `psfFlux` becomes `psf_flux`, `psfFluxErr` becomes `psf_flux_error`.
- A row is removed when `obsTime` is missing, or when `psfFlux` is missing. This table has no magnitude column. A missing `psfFluxErr` does not remove the row; that cell stays empty and shares the photcal.
- `obs_time` stays in MJD. `TIMESYS` time origin is `2400000.5`, timescale `tai`, reference position `TOPOCENTER`.
- `psf_flux` and `psf_flux_error` keep the downloaded numbers. The unit is `Jy`. One photcal group: magnitude system AB, flux zero point `3631` Jy, magnitude zero point `0.0` mag. Filter identifiers and effective wavelengths:

| Filter | Identifier | Wavelength |
| --- | --- | --- |
| `g` | `PAN-STARRS/PS1.g` | `4.81016e-7` m |
| `r` | `PAN-STARRS/PS1.r` | `6.15547e-7` m |
| `i` | `PAN-STARRS/PS1.i` | `7.50303e-7` m |
| `z` | `PAN-STARRS/PS1.z` | `8.66836e-7` m |
| `y` | `PAN-STARRS/PS1.y` | `9.61360e-7` m |

- The TAP table has no description, title, facility, instrument, or bibcode. The product adds them: facility `Haleakala`, instrument `Pan-STARRS 1.8 m telescope`, bibcode `2020ApJS..251....7F`. The description names the object, `objID`, and filter. The title is the object label and the filter.
