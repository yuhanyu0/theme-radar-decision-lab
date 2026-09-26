# ETN 2026Q2 shadow-case sources

Frozen case as-of: **2026-09-26T03:53:00Z**.

This file records the evidence used to construct the first Repricing Graph shadow case.
It is not a claim that the case has alpha. The case deliberately remains
`RESEARCHING` because the company-guidance reality interval overlaps the observed
sell-side consensus.

## 1. Eaton Q2 2026 primary disclosure

SEC Exhibit 99:
https://www.sec.gov/Archives/edgar/data/1551182/000155118226000027/etn06302026exhibit99.htm

Company-hosted release:
https://www.eaton.com/us/en-us/company/news-insights/news-releases/2026/eaton-reports-record-second-quarter-2026-results.html

Relevant disclosed facts:

- FY2026 adjusted EPS guidance: **$13.40-$13.60**.
- Electrical Americas Q2 organic sales growth: **18%**.
- Electrical Americas rolling twelve-month orders: **+41% organically**.
- Electrical Americas backlog: **+33% YoY** at June 2026.
- Company described broad end-market strength; DataCenter_Infra remains the external
  Theme scaffold rather than a claim that all Electrical Americas demand is data-center demand.

The `available_at` value in the YAML is conservatively set to the end of the filing day,
not to an inferred intraday publication time.

## 2. FY2026 sell-side consensus snapshot

StockAnalysis forecast page:
https://stockanalysis.com/stocks/etn/forecast/

Observed during case construction at **2026-09-26T03:52:00Z**. The page stated
"Last updated: Sep 25, 2026" and listed FY2026 EPS forecasts:

- average: **13.55**
- low: **13.25**
- high: **14.12**

The page identifies S&P Global Market Intelligence and TipRanks as data sources.
This is recorded as a sell-side consensus snapshot, not company guidance and not a
strict historical consensus database.

## 3. Next earnings/guidance window

TipRanks:
https://www.tipranks.com/stocks/etn/earnings

Observed during case construction at **2026-09-26T03:52:00Z**. It listed
**Nov 3, 2026** as the estimated Q3 earnings date and explicitly marked it TBA/not confirmed,
noting that the date is estimated from prior reporting schedules.

Therefore the case stores this only as `ESTIMATED_NOT_CONFIRMED`. A later company-confirmed
date must be archived as a new catalyst revision; it must not rewrite this frozen case.

## Scope limitation

The current shadow case does not estimate an elasticity from Electrical Americas orders or
backlog into adjusted EPS. It therefore does not convert strong demand evidence into an
invented earnings number. Its Reality estimate is the company's explicit FY2026 adjusted EPS
guidance interval. The resulting expectation gap versus the observed 13.55 consensus crosses
zero; this is intentional and is why the first real case is not yet a trade candidate.
