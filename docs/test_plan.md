# Test Plan

## Automated Tests

Run:

```bash
pytest -q
```

Coverage:

| Test area | What it proves |
|---|---|
| Event validation | The resolved replay config has complete fixture artifacts and Polymarket outcome mapping. |
| Full replay | `fetch -> build -> snapshot -> audit -> predict -> score -> reports` completes end to end. |
| Future exclusion | Fed statement, post-cutoff news, and post-cutoff rates are excluded from prediction inputs. |
| Evidence bundle | JSON and Markdown bundles are generated and include rates, documents, prediction, score, and excluded evidence. |
| Fixture reproducibility | Two fixture replays produce identical snapshot hash, prediction input hash, Brier score, and audit status. |
| Live FRED connector | Live fetch code calls configured series, uses a key, and does not write the key to raw payloads or manifests. |
| SOFR/EFFR timing | SOFR and EFFR observations become knowable on the next business day, not at the observation timestamp. |
| Horizon comparison | Multi-event, multi-horizon comparison writes scorecards by event and horizon. |
| Live July config | Live Polymarket configs validate without requiring fixture token IDs to match a different event fixture. |
| API surface | `/events`, `/evidence`, and `/snapshot/{snapshot_id}` serve data from an existing run. |

## Manual Verification Commands

Fixture replay:

```bash
frp run \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z
```

Fixture reproducibility:

```bash
frp verify-repro \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z \
  --mode fixture
```

Live FRED/ALFRED capture:

```bash
frp run \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z \
  --source-mode live
```

Horizon comparison:

```bash
frp compare \
  --configs-dir configs/events \
  --horizons T-30,T-14,T-7,T-3,T-1
```

Evidence API:

```bash
frp serve --host 127.0.0.1 --port 8000
```

Then query:

```bash
curl "http://127.0.0.1:8000/evidence?event_id=fomc_2026_06&as_of=2026-04-30T20:00:00Z"
```

## Secret Check

Before committing or sharing generated live artifacts, confirm the FRED key is not present:

```bash
grep -R -q -F -- "$(cat .env.local)" data outputs && echo "secret found" || echo "no secret leak"
```

Do not commit `.env.local`, `data/`, or `outputs/`.

## Acceptance Criteria

- `pytest -q` passes.
- Fixture `frp verify-repro` passes.
- Live FRED/ALFRED run completes with the local `.env.local` key.
- Generated reports show included evidence, excluded future evidence, audit status, forecast probabilities, and score status.
- The live July lane returns `pending_resolution` rather than fake scoring.
