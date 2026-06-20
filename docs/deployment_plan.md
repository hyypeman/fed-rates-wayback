# Deployment Plan

The current product is intentionally local-first. That is the right shape for this release because the acceptance bar is reproducibility and auditability, not uptime.

## Current Deployment: Local Reviewer Package

Use this for a local review:

```bash
python -m pip install -e ".[dev]"
frp run --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z
frp verify-repro --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z --mode fixture
```

Artifacts:

- Checked in: configs, fixtures, source code, tests, docs.
- Generated and ignored: `data/`, `outputs/`, `.env.local`.

This is the strongest reproducibility mode because no network or secret is required.

## Optional Local API

Start:

```bash
frp serve --host 127.0.0.1 --port 8000
```

The API reads local generated runs. It is useful for demos and agent integration, but it is not required for fixture reproducibility.

## Container Shape

A minimal container would:

1. Install the package.
2. Mount a writable volume for `data/` and `outputs/`.
3. Inject `FRED_API_KEY` only as a runtime environment variable.
4. Run `frp serve`.

Suggested runtime command:

```bash
frp serve --host 0.0.0.0 --port 8000
```

Do not bake `.env.local`, generated raw data, or generated reports into the image.

## Production Shape If The Project Continues

| Layer | Local release | Production candidate |
|---|---|---|
| Raw artifacts | Local `data/raw` | Object storage with immutable paths and hash metadata |
| Manifests | Local JSON | Manifest table plus signed raw-artifact hashes |
| Normalized tables | Local DuckDB | DuckDB/Parquet lake, MotherDuck, or warehouse depending size |
| Reports | Local Markdown/JSON | Stored run artifacts plus lightweight dashboard |
| API | FastAPI local service | Deployed FastAPI service with auth and run registry |
| Secrets | `.env.local` | Secret manager/runtime env vars |
| Scheduling | Manual CLI | Scheduled ingestion jobs by event and horizon |

## Operational Rules

- Fixture replay remains the release gate.
- Live connectors can refresh raw artifacts, but promoted fixtures should be reviewed and hashed.
- Every external source must have `source_url`, `source_query`, `retrieved_at`, `license_class`, and `sha256`.
- Every query that returns evidence must require `as_of`.
- No production score should be reported for unresolved events; use `pending_resolution`.

## Go/No-Go To Deploy Beyond Local

Go if:

- Fixture reproducibility remains stable.
- Live connectors do not leak secrets into raw payloads or manifests.
- At least 3-5 resolved events have real retrievable market history or a documented fallback.
- Source terms allow storage and internal analysis.

No-go or re-scope if:

- Resolved Polymarket history is not retrievable enough for benchmarking.
- Source terms prevent storing raw artifacts.
- Point-in-time metadata is missing for key series.
- Audit failures require manual cleanup on most runs.
