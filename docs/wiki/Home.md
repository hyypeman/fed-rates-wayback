# Fed Rate Wayback Machine Wiki

Fed Rate Wayback Machine is a small tool for replaying Fed-rate prediction questions as they looked at a past point in time.

The central question is:

```text
At this cutoff time, what was knowable, what was not knowable yet, and what forecast would the available evidence support?
```

## Start Here

- [What the project does](What-the-project-does.md)
- [How the pipeline works](How-the-pipeline-works.md)
- [Data sources](Data-sources.md)
- [How to use the CLI](CLI-usage.md)
- [Audit and reproducibility](Audit-and-reproducibility.md)
- [Limitations and roadmap](Limitations-and-roadmap.md)

## Key Idea

Every piece of data has a `known_at` timestamp. When you run a replay with an `as_of` cutoff, the tool only uses records where:

```text
known_at <= as_of
```

That rule prevents future information from sneaking into a past forecast.
