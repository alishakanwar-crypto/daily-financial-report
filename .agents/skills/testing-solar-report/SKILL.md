---
name: testing-solar-report
description: Test the Solar Industry Report dashboard, report generation, recipient controls, exchange-rate refresh, and Fly deployment.
---

# Testing the Solar Industry Report

## Local setup

Activate the project virtual environment and start the app with isolated
databases so testing does not alter existing recipient or report state:

```bash
. venv/bin/activate
DB_PATH=/home/ubuntu/solar-test-artifacts/app.db \
SOLAR_DB_PATH=/home/ubuntu/solar-test-artifacts/solar.db \
SOLAR_REPORT_HOUR_IST=10 \
SOLAR_REPORT_MINUTE_IST=0 \
SOLAR_DEFAULT_RECIPIENTS=test@example.com \
BASE_URL=http://localhost:8000 \
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Keep all time assertions in `Asia/Kolkata` and use
`DD-MM-YYYY HH:mm:ss IST`.

## UI flow

Open `http://localhost:8000/solar/mailing-list`.

Verify:

1. The page promises immediate first delivery and shows `10:00 IST`.
2. Adding a recipient returns to the mailing-list dashboard with the immediate
   delivery status.
3. Pause changes the row status, action, and active/paused counts.
4. Resume reverses those changes.

Local SMTP might be unavailable. In that case, do not claim inbox delivery;
verify the UI locally and exercise the real SMTP path in the deployed
environment.

## Fresh USD/INR verification

Wrap `solar.data.prices._usd_inr_rate`, call `fetch_prices()` twice, and assert
the wrapper is called twice. The fetched date must be a completed trading day
formatted as `DD-MM-YYYY`. Avoid caching the rate between report runs.

## Fly verification

The production app is `daily-market-pulse`.

```bash
flyctl status --app daily-market-pulse
flyctl secrets list --app daily-market-pulse
curl -fsS https://daily-market-pulse.fly.dev/health
flyctl logs --app daily-market-pulse --no-tail
```

Fly secret values cannot be retrieved. If the dashboard `APP_SECRET` is not
available to Devin, verify the protected route returns 403 without a token,
test the UI locally, and run the production delivery helper through
`flyctl ssh console` using an explicitly approved recipient.

Confirm startup logs contain:

```text
Solar report scheduled at 10:00 IST daily
```

Confirm immediate production delivery logs:

```text
First Solar Industry Report sent to <recipient>
```

Treat SMTP acceptance and manual inbox receipt as separate assertions.

## Devin Secrets Needed

- `FLY_API_TOKEN`
- `OPENAI_API_KEY`

The Fly app must also have these deployed secrets:

- `APP_SECRET`
- `SMTP_USER`
- `SMTP_PASSWORD`
