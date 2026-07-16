---
name: testing-solar-report
description: Test the Indian solar report generation and source-audit flow end-to-end.
---

# Testing the Solar Report

Use this skill after changes to market adapters, filing data, formulas, report rendering, news qualification, or dashboard generation.

## Devin Secrets Needed

- `APP_SECRET`: dashboard token. For isolated local tests, use a throwaway local value rather than a production token.
- `OPENAI_API_KEY`: optional. Leave unset to verify the deterministic fallback and honest “not assessed” labels.
- SMTP secrets: not needed when testing with zero recipients. Only use them for an explicitly approved email-delivery test.

## Safe Local Setup

1. Use a new SQLite path outside the production data directory.
2. Set `SOLAR_DEFAULT_RECIPIENTS=''` so no email can be sent.
3. Set `BASE_URL=http://localhost:8000`.
4. Start the application with the project virtual environment.
5. Confirm the valid local token returns HTTP 200 and an invalid token returns HTTP 403.
6. Confirm the isolated database has zero recipients before generating.

Example environment shape:

```bash
APP_SECRET='<local-test-token>' \
SOLAR_DB_PATH="$HOME/solar-ui-test.db" \
SOLAR_DEFAULT_RECIPIENTS='' \
OPENAI_API_KEY='' \
BASE_URL=http://localhost:8000 \
venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## UI Test Flow

1. Open `/solar?token=<local-test-token>`.
2. Verify “No recipients yet” and “No reports yet” on a fresh database.
3. Click **Generate report now**.
4. Verify the “Report generation started” banner.
5. Wait for PDF generation to finish, then refresh the dashboard.
6. Verify the report row status is `generated`, not `sent`.
7. Click **Download latest** and open the generated PDF.

## Accuracy Assertions

Verify the generated PDF contains:

- All active tracked companies.
- Latest completed trading date selected in IST.
- Nasdaq official historical prices for RNW.
- BSE official historical prices for Indian tickers.
- Official FBIL USD/INR source, or an explicit unavailable state without substitution.
- Open, close, average, high, low, and volume.
- Daily OHLC, weekly/five-session, and yearly charts with official-source labels.
- Financial-statement values only from linked official company, SEC, NSE, or BSE filings.
- Raw filed values and separately normalized INR values.
- Filing period, scope, statement location, validation status, and clickable source URL per field.
- ROE, ROA, and asset turnover using average opening/closing balances when comparative balances exist.
- FCF formula and input values, preserving negative results.
- FCFF formula and every required input; if inputs are missing, `N/A` plus a specific reason.
- News relevance scores at or above the configured threshold.
- No fabricated fallback impact score when AI is unavailable.
- No Yahoo/yfinance wording or links in financial or market sections.

## Hyperlink Audit

Extract PDF annotations and inspect every URI. Financial links should resolve to official filings; market links should resolve to official exchange/ticker endpoints; FX should resolve to FBIL. Open at least one filing in the browser and cross-check one displayed figure against the filing text.

## Evidence

- Record the dashboard-to-PDF UI flow with structured annotations.
- Capture full-screen screenshots of:
  - the generated dashboard row;
  - the market monitor;
  - daily/weekly/yearly charts;
  - official statement comparison and source audit;
  - news relevance badges;
  - one live official filing.
- Write `test-report.md` with pass/fail/untested assertions and inline screenshots.
- For an open PR, post one concise runtime-test comment with embedded visual evidence and the Devin session link.

## Common Pitfalls

- A background server may still be running older code; restart it after confirming the current commit.
- Do not use the production database or recipient list.
- Browser download routes may force attachment download; use a local `file://` URL only for visual PDF inspection after verifying the UI download works.
- PDF text extraction can insert line breaks; normalize whitespace for exact-phrase checks.
- A missing official input must remain unavailable; do not convert missing values to zero merely to produce a ratio.
