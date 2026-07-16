---
name: testing-solar-report
description: Test the Solar Industry Report admin dashboards, generated PDF, mailing controls, topic filters, and listing lifecycle end-to-end.
---

# Testing the Solar Industry Report

## Devin Secrets Needed

- `OPENAI_API_KEY`: Needed to verify live AI-ranked news summaries.
- `SMTP_USER` and `SMTP_PASSWORD`: Needed only when verifying real email delivery.
- `APP_SECRET`: Needed to access deployed production admin routes.
- `FLY_API_TOKEN`: Needed only for deployment and production-log checks.

## Local authentication and safety

- The default local `APP_SECRET=change-me-in-production` disables token enforcement.
- Use a fresh `SOLAR_DB_PATH` so UI mutations do not touch production or another test run.
- Set `SOLAR_DEFAULT_RECIPIENTS=''` and leave SMTP unset unless delivery is explicitly in scope.
- Without SMTP, a successful generated report is logged as `generated` with `SMTP not configured`.

## Start an isolated server

```bash
source venv/bin/activate
env \
  DB_PATH=/home/ubuntu/solar-test-artifacts/app.db \
  SOLAR_DB_PATH=/home/ubuntu/solar-test-artifacts/solar.db \
  BASE_URL=http://localhost:8011 \
  SOLAR_DEFAULT_RECIPIENTS='' \
  uvicorn app.main:app --host 0.0.0.0 --port 8011
```

Open `http://127.0.0.1:8011/solar` in Chrome.

## Core UI paths

- `/solar`: report generation, report history, mailing summary
- `/solar/mailing-list`: recipient add, Pause, Resume
- `/solar/companies`: add, remove, restore, and inspect listing checks
- `/solar/topics`: search presets, activate/deactivate, add/delete custom topics
- `/solar/download/latest`: downloads the newest generated PDF as an attachment

## Company and topic runtime checks

1. Add an NSE company without `.NS`; verify the saved ticker includes `.NS`.
2. Remove and restore it; verify counts and statuses update without deleting the row.
3. Search for a preset topic and activate it.
4. Add a custom topic and verify both `Custom` and `Included`.
5. Trigger report generation from `/solar`.
6. Refresh after completion; verify the report row uses `DD-MM-YYYY HH:mm:ss IST`.
7. Download the PDF and open `data/solar_reports/solar_industry_report_YYYY-MM-DD.pdf` in Chrome.
8. Verify selected topics appear only in the separate `Supplementary Intelligence` section.

## Automatic-delisting test

- First confirm a ticker currently returns Yahoo's explicit `No data found, symbol may be delisted` response. A previously delisted ticker might stop producing that exact response later.
- Seed that tracked company at `possible_delisting` with `consecutive_failures=2`.
- Trigger one report through the UI.
- Verify the registry changes it to `Auto Delisted`, shows 3 explicit failures, and offers Restore.
- Verify the generated PDF excludes it.
- Ordinary connection errors or rate limits must not increment the explicit-failure count.

## PDF evidence

- Capture the cover tracking line to prove active-company membership.
- Capture the government section followed by the supplementary section to prove separation.
- Use Chrome PDF search to verify an auto-delisted company has zero matches.
- `Download latest` downloads rather than automatically opening the PDF, so open the generated file manually for visual inspection.

## Useful verification commands

```bash
source venv/bin/activate
python -m compileall -q app solar
ruff check solar
```

The repository environment blueprint already installs `requirements.txt` and documents the normal Uvicorn startup command.
