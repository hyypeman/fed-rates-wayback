# Event Configuration Guide

An event config is the pinned contract for one replay. It tells `frp` what event is being predicted, which cutoff to use by default, how Polymarket outcomes map into normalized labels, which artifacts to fetch, and how to score the result.

Use `--event-config` when you want exact reproducibility:

```bash
frp run --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z
```

Use `--event-slug` when you want the CLI to find the matching config:

```bash
frp run --event-slug fed-decision-june-2026 --as-of 2026-04-30T20:00:00Z
```

## Required Fields

| Field | Meaning |
|---|---|
| `event_id` | Stable local ID used in run IDs and output paths. |
| `event_slug` | Human/source-facing slug, usually the Polymarket event slug. |
| `title` | Display title in reports and API responses. |
| `evaluation_mode` | `resolved_replay` for scoreable past events or `live_forecast` for unresolved events. |
| `target_meeting_start` / `target_meeting_end` | FOMC meeting dates. Horizon cutoffs are computed from `target_meeting_end`. |
| `as_of_default` | Default cutoff timestamp. Every evidence query is anchored to an as-of time. |
| `final_outcome` | One normalized outcome for resolved events; `null` for live forecasts. |
| `fixture_dir` | Checked-in fixture folder for deterministic replay. |
| `fixture_captured_at` | Stable capture time used by fixture mode. |
| `source_bundle` | Source families expected for the event. |
| `normalized_outcomes` | Mapping from canonical labels to market slugs and Yes token IDs. |
| `artifacts` | Raw artifacts to fetch/copy, with source URL, query, license class, and media type. |

## Normalized Outcomes

Every event maps into the same labels:

```text
no_change
hike_25
cut_25
hike_50_plus
cut_50_plus
other_or_unmapped
```

`other_or_unmapped` is a safety bucket. It prevents silent failures when source wording or market structure does not fit the expected labels.

## Live FRED/ALFRED

Add `live_alfred` when live mode should fetch fresh FRED/ALFRED data:

```yaml
live_alfred:
  observation_start: "2026-03-01"
  observation_end: "2026-04-30"
  realtime_start: "2026-03-01"
  series_groups:
    alfred_observations:
      - DFEDTARU
      - DFEDTARL
      - FEDFUNDS
      - UNRATE
      - PAYEMS
      - CPIAUCSL
    rates_observations:
      - DGS2
      - DGS10
      - T10YIE
      - SOFR
      - EFFR
```

Live mode reads `FRED_API_KEY` from `.env.local` or the environment:

```bash
frp run --event-config configs/events/fomc_2026_06.yaml --as-of 2026-04-30T20:00:00Z --source-mode live
```

The key is only used for requests. It is not written to manifests or raw payloads.

## Live Polymarket

Add `live_polymarket.enabled: true` for unresolved/live market configs:

```yaml
live_polymarket:
  enabled: true
```

When enabled, `frp fetch --source-mode live` calls the Polymarket Gamma event endpoint for the configured slug and maps markets into normalized outcomes. The July 2026 config uses this path and marks scoring as `pending_resolution`.

## Fixture Mode Versus Live Mode

| Mode | Use | Reproducibility |
|---|---|---|
| `fixture` | Reviewer demo, tests, byte-stable replay | Deterministic |
| `live` | Fresh FRED/ALFRED or live Polymarket capture | Records raw payloads, but values can drift over time |

Fixture mode is the acceptance gate. Live mode proves the connectors and creates new raw artifacts that can later be promoted into fixtures.

## Adding A New Resolved Event

1. Create `configs/events/<event_id>.yaml`.
2. Pin `evaluation_mode: resolved_replay`.
3. Fill `target_meeting_start`, `target_meeting_end`, `as_of_default`, and `final_outcome`.
4. Map each Polymarket Yes token ID under `normalized_outcomes`.
5. Record raw artifacts into a fixture folder.
6. Run `frp validate-event`.
7. Run `frp verify-repro`.
8. Add it to `frp compare` only after the artifact history is real enough for the claim being made.
