# Requirements Coverage

This matrix maps the project's reliability goals to the implementation in this repository.

## Core Deliverables

| Requirement | Built artifact | Verification |
|---|---|---|
| Reproducible end-to-end pipeline on a real-source-shaped slice | `frp run --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z` | `frp verify-repro --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z --mode fixture` |
| Pull in, store, clean, provenance, audit, final dataset | `fetch`, `build`, `snapshot`, `audit`, `predict`, `score`, and report rendering | `pytest -q` and generated `outputs/<run_id>/` reports |
| Raw artifact preservation | `data/raw/<run_id>/` plus `data/manifests/<run_id>.json` with hashes and source metadata | Manifest SHA-256 fields and ignored generated raw store |
| Structured storage | DuckDB database under `data/processed/<run_id>/fed_wayback.duckdb` | Core tests and manual SQL inspection |
| Provenance for every normalized row | `raw_artifact_id`, `source_url`, `source_query`, `license_class`, `content_hash`, `known_at`, `pipeline_version` | Audit checks and `tests/test_pipeline.py` |
| Re-running yields same reviewer output | Fixture replay compares snapshot hash, prediction input hash, Brier score, and audit status | `frp verify-repro ... --mode fixture` |
| Audit/QA method | `audit_report.md/json` checks leakage, provenance, duplicate artifact hashes, grouped-market normalization, PII, and a leakage canary | `frp audit --run-id <run_id>` |
| Go/no-go criteria | `go_no_go.md` generated for every run | `frp run ...` |
| "What could this predict?" map | `predictable_questions_map.md` generated for every run | `frp run ...` |

## Extended Deliverables

| Stretch target | Built artifact | Verification |
|---|---|---|
| Predict-the-past demo | April 30, 2026 cutoff predicts the June 2026 Fed decision from pre-cutoff facts | `prediction_report.md`, `scorecard.md` |
| Hide future data | Snapshot excludes rows with `known_at > as_of`; future Fed docs/news/rates are stored but excluded | `tests/test_pipeline.py` |
| Score against real outcome | `scorecard.md` reports model, Polymarket, and always-hold Brier scores for resolved replay events | `frp score --run-id <run_id>` |
| Resolve one Polymarket-style question | Outcome mapping is pinned by normalized outcome and Yes token ID; Polymarket odds are benchmark-only | `frp validate-event ...` |
| Horizon scoring | `frp compare --horizons T-30,T-14,T-7,T-3,T-1` writes comparison scorecards | `tests/test_pipeline.py::test_compare_events_writes_horizon_scorecards` |
| Agent-readable access | Local FastAPI app exposes events, evidence, snapshots, market odds, predictions, and audits | `frp serve`, API test coverage |
| Live forward forecast | July 2026 event config can fetch live FRED/ALFRED and live Polymarket, then withhold scoring until resolution | `configs/events/fomc_2026_07_live.yaml` |

## Data Sources

| Source family | Status |
|---|---|
| Polymarket Gamma/CLOB-shaped data | Fixture-backed for reproducible replay; live Gamma fetch implemented for configs with `live_polymarket.enabled`. CLOB history fallback remains a source-risk item. |
| FRED/ALFRED | Fixture-backed by default; live FRED API fetching is implemented with `--source-mode live` using `FRED_API_KEY`. Realtime parameters are used for ALFRED-style as-of selection. |
| Rates/yields | Fixture and live FRED support for `DGS2`, `DGS10`, `T10YIE`, `SOFR`, and `EFFR`; SOFR/EFFR are aligned to next-business-day publication timing. |
| Federal Reserve official docs | Fixture-backed official document demo with known times, hashes, and future cutoff exclusion. Full live Fed-document crawler/NLP is planned for a later version. |
| GDELT/news | Fixture-backed messy-source slice included in the pipeline and audit. Live GDELT crawling is a scale-up connector, not required for byte-stable replay. |

## Risk Coverage

| Risk | Mitigation |
|---|---|
| Data leakage | `known_at <= as_of`, excluded-future examples, publication-time logic, and leakage canary. |
| Reproducibility drift | Fixture mode is the hard gate; live mode records fresh payloads but is not expected to be byte-identical. |
| Licensing/usage limits | `license_class` is attached to artifacts and normalized rows; source terms remain an explicit go/no-go input before scaling. |
| Sparse or missing market prices | Event validation checks token mappings and prices; scoring marks Polymarket unavailable if no cutoff odds exist. |
| Messy text and dedup | Duplicate raw artifact hashes and PII-like text are audit warnings; richer near-duplicate clustering is a scale-up item. |
| PII | Audit scans document text for email-like PII patterns. |
| Storage/compute cost | V1 is local files and DuckDB; deployment plan moves raw artifacts to object storage and query tables to a managed database only when needed. |

## Honest Boundary

The current product is fully built as a trustworthy replay substrate. The remaining work is not a missing core feature; it is scale and source-access expansion:

- Replace fixture-backed comparison events with per-event live-recorded Polymarket and official-source history.
- Add full Fed document crawler, statement diffs, minutes, speeches, and NLP features.
- Add CME/futures/OIS baselines if licensed or public access is available.
- Add live GDELT ingestion at larger scale with stronger dedup and source-policy handling.
- Calibrate a stronger forecasting model after enough resolved events exist.
