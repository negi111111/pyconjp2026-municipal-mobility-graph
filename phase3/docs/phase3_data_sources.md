# Phase 3 data-source investigation

Status: **Phase 3 implementation baseline**. Climate and nearest Shinkansen
distance passed the adoption gates and are included as explicit features.
Housing, disaster, and nature remain outside the ranking boundary.

## Candidate sources

| Dataset | Provider | URL | Geographic granularity | Period | License / redistribution | National100 coverage | Decision |
|---|---|---|---|---|---|---|---|
| Housing and Land Survey / housing statistics | Statistics Bureau / e-Stat | https://www.e-stat.go.jp/stat-search?layout=datalist&metadata=1&data=1&toukei=00200522 | municipality/table-dependent | 2023 survey candidate | e-Stat terms; table-specific redistribution review required | **not verified** | Must verify exact rent/housing-cost table before adoption |
| 2020 normals, surface observations | Japan Meteorological Agency | https://www.data.jma.go.jp/obd/stats/data/mdrr/normal/ | observation station | 1991–2020 normals, current published revision | JMA public data terms; source notice and revision date retained | station coverage appears national; municipality matching pending | Priority A candidate |
| JMA surface monthly normals | Japan Meteorological Agency | https://www.data.jma.go.jp/obd/stats/data/mdrr/normal/2020/data/normal_surface.zip | observation station | 1991–2020 | JMA public data terms; ZIP digest pinned in the Phase 3 manifest | **100/100** nearest-station mappings | **Adopted** |
| JMA station index | Japan Meteorological Agency | https://www.data.jma.go.jp/obd/stats/data/mdrr/normal/2020/data/amedas_station_index.zip | observation station | 2020 normals edition | JMA public data terms | national station metadata | **Adopted as climate mapping input** |
| Railway / station geospatial data | Ministry of Land, Infrastructure, Transport and Tourism, National Land Numerical Information | https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N02-v2_3.html | station / line | N02-20 (2020) | MLIT dataset terms; ZIP digest pinned in the Phase 3 manifest | **100/100** nearest-station mappings | **Adopted for nearest Shinkansen distance only** |
| Hazard / flood / landslide data | MLIT hazard and National Land Numerical Information portals | https://disaportal.gsi.go.jp/ | hazard polygon / mesh | edition-dependent | dataset-specific public terms | likely broad, aggregation design not verified | Priority B feasibility study |
| Land use / natural park data | MLIT National Land Numerical Information | https://nlftp.mlit.go.jp/ksj/gml/datalist.html | polygon / mesh | edition-dependent | dataset-specific public terms | likely broad, city aggregation not verified | Priority B feasibility study |

## Adoption gates

### Housing

The standard ranking will use housing cost only if one official table has the
same definition and a non-missing value for all 100 cities. A partial table
will remain a documented data gap rather than being imputed from a national
average, an LLM, or a private real-estate site.

### Climate

The implementation candidate is a nearest or reviewed representative JMA
station. Each municipality record must retain:

```text
weather_station_id
weather_station_name
distance_km
period
```

Municipality values will not be copied from prefectural averages.

### Shinkansen

Only a station-level public dataset with coordinates, a reproducible edition,
and redistribution permission will be used. The initial feature is limited to
the nearest Shinkansen station and straight-line distance. Timetables,
transfers, GTFS, and travel time are out of scope.

### Disaster and nature

These are not automatically included. They require an explicit area/population
aggregation method; a city-hall point value is not a city-wide risk or nature
value.

## Provenance fields to add

Every adopted Phase 3 feature must preserve:

```text
feature_name
category
unit
year
period
source_dataset
source_url
retrieved_at
license
redistribution
geographic_granularity
direction
normalization
missing_reason
```

The generated feature table additionally preserves `retrieved_at`, `license`,
and `redistribution`; the source-archive digest and exact retrieval record are
in `data/provenance/phase3_download_manifest.json`.
