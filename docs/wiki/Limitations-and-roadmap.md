# Limitations And Roadmap

## Current Limitations

- The checked-in dataset is small.
- Some event configs are examples that reuse fixture-style data. They test repeated scoring, not full event-specific forecasting quality.
- Live APIs can change behavior or become unavailable.
- Resolved Polymarket price history can be sparse.
- Public data sources may have usage limits.
- The simple forecast is a baseline, not an advanced prediction model.

## What The Project Already Proves

- Data can be fetched or copied into a raw store.
- Raw files can be hashed and traced.
- Economic and market data can be normalized into tables.
- A cutoff replay can exclude future information.
- Audit checks can run on every replay.
- Forecasts can be scored when the outcome is known.
- Unresolved events can be marked pending instead of scored too early.

## Next Improvements

1. Add more resolved Fed events with real event-specific raw artifacts.
2. Improve historical Polymarket price capture.
3. Add more official Fed documents.
4. Add release calendars for major economic reports.
5. Add better document duplicate detection.
6. Add stronger forecasting baselines after more events are available.

## When To Scale

The project should only move beyond local files and DuckDB when:

- More events are added.
- Raw artifacts are too large for local storage.
- Multiple people need to query the same data.
- Scheduled live ingestion becomes necessary.
