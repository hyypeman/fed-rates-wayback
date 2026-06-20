# How The Pipeline Works

The pipeline has six stages.

## 1. Configure The Event

An event config says which Fed decision to analyze, which cutoff to use, which Polymarket outcomes map to which labels, and which source files or APIs belong to the run.

Example:

```bash
frp run --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z
```

## 2. Fetch Raw Data

`frp fetch` copies checked-in fixture data or calls live APIs. It writes raw artifacts and a manifest.

The manifest records:

- Source URL.
- Source query.
- Retrieval time.
- License class.
- File hash.

## 3. Build Tables

`frp build` loads the raw files into DuckDB tables. DuckDB is a small local database that is easy to inspect and works well for this kind of project.

## 4. Create A Cutoff Snapshot

`frp snapshot` applies the core rule:

```text
known_at <= as_of
```

Records after the cutoff are not deleted. They are kept as excluded future evidence so the report can show what was intentionally hidden.

## 5. Audit The Dataset

`frp audit` checks for problems such as:

- Future records included by mistake.
- Missing source links.
- Duplicate raw files.
- Possible personal information in document text.
- Market prices that need normalization.

## 6. Predict And Score

`frp predict` runs a simple rules-based forecast.

`frp score` compares that forecast with the final outcome if the event has resolved. If the event is still live, the score is marked `pending_resolution`.
