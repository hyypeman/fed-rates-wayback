# Data Sources

The project uses a small set of public or public-like sources. Each source has a specific job.

## Polymarket

Used for:

- Prediction market question metadata.
- Outcome labels.
- Token IDs.
- Market odds.

Why it was picked:

Polymarket gives a public market benchmark. The tool does not use Polymarket odds as forecast input. It uses them later as a comparison point.

## FRED And ALFRED

Used for:

- Fed target-rate range.
- Effective federal funds rate.
- Inflation.
- Unemployment.
- Payrolls.
- Other macroeconomic series.

Why they were picked:

FRED is easy to access, and ALFRED provides historical versions of economic data. That matters because economic data can be revised after first publication. A replay should use the version that was available at the cutoff time, not a later revision.

## Rates And Yields

Used for:

- 2-year Treasury yield: `DGS2`.
- 10-year Treasury yield: `DGS10`.
- 10-year breakeven inflation: `T10YIE`.
- SOFR.
- Effective federal funds rate: `EFFR`.

Why they were picked:

Fed decisions are about the economy, but they are also about what markets expect the Fed to do. Rates and yields are compact signals of those expectations.

SOFR and EFFR are handled carefully because they are published for the prior business day. The tool records when those values became knowable.

## Federal Reserve Documents

Used for:

- Official statements.
- Implementation notes.
- Resolution evidence after a Fed decision.

Why they were picked:

Federal Reserve pages are the official source for the actual policy decision and official communication.

## GDELT Or News Fixtures

Used for:

- A small text/news example.
- Testing source provenance for messy text.
- Testing future-evidence exclusion.

Why it was picked:

News data is messier than structured economic data. Including a tiny news slice proves that the audit path can handle document-like sources without making the first version too broad.

## Source Handling Rule

Every source artifact should have:

- A source URL.
- A source query.
- A retrieval time.
- A license class.
- A file hash.
- A `known_at` time for each usable record.
