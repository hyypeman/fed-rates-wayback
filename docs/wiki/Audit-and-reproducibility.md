# Audit And Reproducibility

The project is built around two promises:

1. A past replay should not see future information.
2. The checked-in fixture replay should produce the same result when run again.

## Future Information Check

Every usable record has a `known_at` timestamp. The snapshot step only includes records that were knowable at the cutoff:

```text
known_at <= as_of
```

The report also shows examples of records that were excluded because they were too late.

## Raw Artifact Hashes

Raw source files are hashed. A hash is like a fingerprint for a file. If the file changes, the hash changes.

The manifest records these hashes so a user can trace each table row back to the source artifact that produced it.

## Fixture Mode

Fixture mode uses checked-in example data. It is the most reproducible mode because it does not need the network.

Run:

```bash
frp verify-repro \
  --event-config configs/events/fomc_2026_06.yaml \
  --as-of 2026-04-30T20:00:00Z \
  --mode fixture
```

## Live Mode

Live mode calls external APIs. It records fresh raw payloads, so it is useful for refreshing evidence. It is not expected to be byte-for-byte identical across time because live sources can change.

## Audit Checks

The audit currently checks:

- Future data leakage.
- Missing raw-artifact provenance.
- Duplicate raw artifact hashes.
- Possible personal information in document text.
- Market-price normalization warnings.
- A synthetic leakage canary.

The leakage canary is a deliberate test record. It proves the audit would notice future data if it appeared in the included snapshot.
