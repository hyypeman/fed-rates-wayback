# Roadmap

## Version 1: Local Replay Tool

Built now:

- Reproducible fixture replay.
- Live FRED/ALFRED fetches.
- Live Polymarket event fetches for configured live events.
- Source hashes and provenance.
- Cutoff filtering with `known_at <= as_of`.
- Audit reports.
- Simple forecast and scorecards.
- Evidence API.

## Version 1.5: Better Real-Event Coverage

Next useful improvements:

- Replace fixture-backed comparison examples with real per-event raw artifacts.
- Add more resolved Fed decision markets.
- Record historical Polymarket prices more robustly.
- Add a clearer command for promoting a live run into a reviewed fixture.

## Version 2: Stronger Forecast Inputs

Useful additions once the replay base is stable:

- More Fed documents, including statements, minutes, speeches, and press conferences.
- More rate-market data, such as futures or swaps if accessible.
- Release calendars for CPI, payrolls, PCE, and other major economic reports.
- Better news ingestion and duplicate detection.

## Version 3: Shared Service

If the project grows beyond local use:

- Store raw artifacts in object storage.
- Store normalized tables in a shared database or query engine.
- Add authentication to the API.
- Schedule regular source refreshes.
- Track model versions and forecast results across many events.

## Main Open Limitations

- The checked-in dataset is intentionally small.
- Some comparison configs reuse the same fixture shape, so they test the harness rather than prove event-specific forecasting quality.
- Live source availability can change.
- Polymarket history may be sparse for resolved events.
- Public sources can have usage limits or terms that affect redistribution.
