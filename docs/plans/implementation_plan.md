# Implementation Plan

This project builds a local replay tool for Fed-rate prediction questions. The goal is simple:

1. Pick a Fed decision event.
2. Pick a cutoff time.
3. Gather only facts that were knowable at that cutoff.
4. Build a small dataset with source links and hashes.
5. Run audit checks.
6. Produce a forecast and compare it with market odds and the final outcome.

## Why This Shape

Prediction work is only useful if the historical data is honest. If a forecast made "as of April 30" accidentally sees a news article or economic release from May, the result is invalid. The main design choice is therefore:

```text
Every record must say when it became knowable.
Every replay must filter records with known_at <= as_of.
```

## Current Build

- A command-line tool named `frp`.
- Event config files in `configs/events/`.
- Small checked-in fixtures in `fixtures/`.
- A DuckDB database created for each run.
- Markdown and JSON reports in `outputs/`.
- A local API served by `frp serve`.

## Main Data Flow

```text
source files or APIs
  -> raw artifacts with hashes
  -> normalized DuckDB tables
  -> cutoff snapshot
  -> audit report
  -> forecast
  -> scorecard and evidence bundle
```

## What Is Intentionally Small

The checked-in dataset is small on purpose. It is meant to prove the full path from raw source to audited forecast, not to claim a production-grade forecasting edge.

## Acceptance Checklist

- `pytest -q` passes.
- `frp verify-repro` passes in fixture mode.
- Live FRED/ALFRED mode can run with `FRED_API_KEY`.
- Generated reports explain included and excluded evidence.
- Unresolved future events return `pending_resolution` instead of a fake score.
