# What The Project Does

This project creates a repeatable replay of Fed-rate prediction questions.

For example, you can ask:

```text
As of 2026-04-30, what evidence was available for the June 2026 Fed decision?
```

The tool then:

1. Loads the event configuration.
2. Fetches or copies source data.
3. Stores raw files with hashes.
4. Normalizes the data into tables.
5. Builds a cutoff snapshot.
6. Runs audit checks.
7. Makes a simple forecast.
8. Scores the forecast if the event has resolved.
9. Writes reports and an evidence bundle.

## What It Produces

Each run writes:

- `run_manifest.json`: what sources were used and where they came from.
- `audit_report.md`: what quality checks passed or failed.
- `prediction_report.md`: what evidence was included, what was excluded, and what the forecast said.
- `scorecard.md`: model score, market score, and simple baseline score.
- `evidence_bundle.json`: machine-readable evidence for apps or AI tools.

## What It Is Not

It is not a trading bot. It is also not a claim that the simple forecast beats markets. The current forecast is deliberately simple. The main value is the reliable data replay.
