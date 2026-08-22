# Data licenses and attribution

This file covers data used by the Phase 1 pipeline. It is not legal advice. The
official dataset page and terms linked below are authoritative. The source edition,
actual retrieval time, byte size, and SHA-256 digest of each downloaded file are
recorded in `data/provenance/download_manifest.json`.

The project software license does not replace or relicense the source datasets.
When raw or processed data is redistributed, keep this file, `sources.yml`, the
download manifest, attribution, processing notice, and source limitations together.

## SSDSE-A-2026

- Provider: National Statistics Center, Japan
- Dataset: [SSDSE-Municipalities (SSDSE-A)](https://www.nstac.go.jp/use/literacy/ssdse/)
- Terms: [National Statistics Center site policy](https://www.nstac.go.jp/info/site-policy/)
- Terms summary: the site rule conforms to the Government Standard Terms of Use
  2.0, permits commercial reuse, and is compatible with CC BY 4.0. Attribution is
  required, and edited material must be identified as edited.
- Redistribution: raw numeric data and processed subsets may be redistributed with
  attribution; processed output must also say that this project transformed it.
- Required attribution for this project:

  > Source: National Statistics Center, SSDSE-Municipalities (SSDSE-A),
  > https://www.nstac.go.jp/use/literacy/ssdse/; processed by this project.

The source page separately excludes logos and specifically identified content from
the general reuse rule. Those assets are not part of this project dataset.

## 2020 Population Census commuting and school OD

- Provider: Statistics Bureau of Japan; distributed by e-Stat
- Dataset: [2020 Population Census Table 3 file list](https://www.e-stat.go.jp/stat-search/files?cycle=0&layout=datalist&page=1&tclass1=000001136469&tclass2val=0&toukei=00200521&tstat=000001136464)
- Terms: [e-Stat Terms of Use](https://www.e-stat.go.jp/terms-of-use)
- Terms summary: reproduction, public transmission, and adaptation are permitted,
  including commercial use. The rule is compatible with CC BY 4.0. The terms also
  state that numerical data and simple tables are not copyrightable content.
- Redistribution: raw workbooks and processed OD tables may be redistributed with
  source attribution and an explicit processing notice.
- Required attribution for this project:

  > Source: 2020 Population Census results, Statistics Bureau of Japan,
  > Government Statistics Portal Site (e-Stat); processed by this project.

Phase 1 pins six e-Stat `statInfId` values: `000032214257` (Shimane),
`000032214260` (Okayama), `000032214263` (Hiroshima), `000032214266`
(Yamaguchi), `000032214272` (Kagawa), and `000032214275` (Ehime). See
`sources.yml` for each direct download URL.

## National Land Numerical Information P05-22

- Provider: Ministry of Land, Infrastructure, Transport and Tourism (MLIT), Japan
- Dataset: [Municipal Offices and Public Meeting Facilities, P05-22](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-P05-v3_0.html)
- Terms: [National Land Numerical Information site terms](https://nlftp.mlit.go.jp/ksj/other/agreement.html)
- Terms summary: the dataset page marks the data as open data under the applicable
  rule. The current linked site rule applies the Public Data License 1.0 unless a
  separate notice says otherwise. Attribution and an additional processing notice
  are required for edited data.
- Redistribution: permitted with attribution, processing notice, the source-page
  limitations, and any identified third-party-rights notice.
- Required attribution for this project:

  > Source: National Land Numerical Information (Municipal Offices and Public
  > Meeting Facilities, P05-22), MLIT; processed by this project.

P05-22 is a 2022 snapshot. The provider notes that the original materials may not
contain every facility. Phase 1 uses a main municipal office as a reproducible
representative point; it is not a population centre.

## National Land Numerical Information C28-21

- Provider: Ministry of Land, Infrastructure, Transport and Tourism (MLIT), Japan
- Dataset: [Airport Data, C28-21](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-C28-2021.html)
- Terms: [legacy National Land Numerical Information terms](https://nlftp.mlit.go.jp/ksj/other/agreement_02.html)
- Terms summary: C28-21 is marked **commercial use permitted**. Under the linked
  legacy terms this includes redistribution of copies when source and processor are
  shown. The license, incompleteness, precision, and fitness limitations must be
  passed on to downstream users.
- Redistribution: raw and transformed C28-21 data may be redistributed with the
  required attribution, processing notice, license notice, and limitations.
- Required attribution for this project:

  > Source: National Land Numerical Information (Airport Data, C28-21), MLIT;
  > processed by this project.

C28-21 represents airport status at 2021-12-31 and may contain spatial and temporal
error. Phase 1 distances use the C28 airport reference point, which is not necessarily
the terminal entrance, rail station, or road-access point.

## 2025 Airport Management Status Report

- Provider: Civil Aviation Bureau, Ministry of Land, Infrastructure, Transport and
  Tourism (MLIT), Japan
- Dataset: [Airport Management Status](https://www.mlit.go.jp/koku/15_bf_000185.html)
- Terms: [MLIT site policy](https://www.mlit.go.jp/link.html)
- Terms summary: unless a separate rights notice applies, MLIT content is available
  under the Public Data License 1.0. Attribute the source and identify processing.
- Redistribution: the source workbook and extracted airport passenger totals may be
  redistributed with attribution and a processing notice, subject to any separately
  identified third-party rights.
- Required attribution for this project:

  > Source: Airport Management Status Report, Civil Aviation Bureau, MLIT;
  > processed by this project.

The source reporting year is preserved from the workbook. Passenger counts are
joined to the older C28-21 airport geometry only after a reviewed one-to-one airport
name match; differing reference dates are not concealed.

## Derived data

Derived municipality, OD, airport, accessibility, graph, similarity, centrality, and
community files combine the sources above. A derived file must retain machine-readable
source identifiers or an adjacent provenance record. It must not imply that the
National Statistics Center, Statistics Bureau, e-Stat, or MLIT produced or endorsed
the project's transformations, rankings, communities, or narrative answers.

Phase 1 does not collect Wikipedia data, does not use a GraphRAG corpus, does not
include route counts or road/rail travel time, and does not create a fixed
`livability_score`. LLM-generated statements are not source data and must never be
stored or redistributed as project facts.
