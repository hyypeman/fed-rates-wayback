# Fed Rate Wayback Machine

Fed Rate Wayback Machine is a small tool for replaying Fed-rate prediction questions as they looked at a past point in time.

The central question is:

```text
At this cutoff time, what was knowable, what was not knowable yet, and what forecast would the available evidence support?
```

## Start Here

| Page | What It Explains |
|---|---|
| [What the project does](What-the-project-does) | The product in plain English and what each run produces. |
| [How the pipeline works](How-the-pipeline-works) | The step-by-step flow from raw sources to reports. |
| [Data sources](Data-sources) | Why Polymarket, FRED/ALFRED, rates, Fed docs, and news are used. |
| [CLI usage](CLI-usage) | Commands for running replays, live mode, comparisons, and the API. |
| [Audit and reproducibility](Audit-and-reproducibility) | How the tool avoids future-data leakage and verifies repeatability. |
| [Limitations and roadmap](Limitations-and-roadmap) | What is built now, what is intentionally small, and what comes next. |

## Key Idea

Every piece of data has a `known_at` timestamp. When you run a replay with an `as_of` cutoff, the tool only uses records where:

```text
known_at <= as_of
```

That rule prevents future information from sneaking into a past forecast.

## Typical Workflow

```bash
frp run \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z
```

The run creates a manifest, a cutoff snapshot, an audit report, a prediction report, a scorecard, and an evidence bundle.

## Main Outputs

| Output | Purpose |
|---|---|
| `run_manifest.json` | Shows which sources were used and records hashes for raw files. |
| `audit_report.md` | Lists quality checks and possible issues. |
| `prediction_report.md` | Explains included evidence, excluded future evidence, and forecast probabilities. |
| `scorecard.md` | Compares the forecast with the final outcome and market benchmark when available. |
| `evidence_bundle.json` | Machine-readable evidence for apps or other tools. |
