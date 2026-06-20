# CLI Usage

Install the package locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Run The Main Replay

```bash
frp run \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z
```

You can also use the event slug:

```bash
frp run \
  --event-slug fed-decision-june-2026 \
  --as-of 2026-04-30T20:00:00Z
```

## Verify Reproducibility

```bash
frp verify-repro \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z \
  --mode fixture
```

## Run Live FRED/ALFRED Mode

Put a FRED API key in `.env.local`:

```text
FRED_API_KEY=...
```

Then run:

```bash
frp run \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z \
  --source-mode live
```

The key is used for the API call. It is not written to generated artifacts.

## Compare Multiple Events And Horizons

```bash
frp compare \
  --configs-dir configs/events \
  --horizons T-30,T-14,T-7,T-3,T-1
```

This writes comparison reports to `outputs/comparison/`.

## Serve The Local API

```bash
frp serve --host 127.0.0.1 --port 8000
```

Useful endpoints:

- `/events`
- `/evidence?event_id=fomc_2026_06&as_of=2026-04-30T20:00:00Z`
- `/prediction?event_id=fomc_2026_06&as_of=2026-04-30T20:00:00Z`
- `/market-odds?event_id=fomc_2026_06&as_of=2026-04-30T20:00:00Z`
- `/audit/{snapshot_id}`
