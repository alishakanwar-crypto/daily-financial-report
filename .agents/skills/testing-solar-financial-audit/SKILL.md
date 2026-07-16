---
name: testing-solar-financial-audit
description: Test the Solar Industry Report formula editor, official-source audit, and generated PDF end-to-end.
---

# Testing the solar financial audit flow

## Devin Secrets Needed

- `OPENAI_API_KEY`: Optional for live AI summaries. The report has a fallback.
- `APP_SECRET`: Use a development-only value for the isolated local dashboard.
- SMTP secrets are not needed unless email delivery is explicitly in scope.

## Setup

1. Create isolated app and solar SQLite paths outside the repository.
2. Start the app with those paths, a development-only `APP_SECRET`, and
   `SOLAR_DEFAULT_RECIPIENTS=''`.
3. Confirm `/health` returns healthy before starting browser recording.
4. Use the token-protected `/solar` URL. Never display a production token.

## Formula safety and persistence

1. Open `/solar/formulas`.
2. Record the default expressions and IST timestamps.
3. Submit a function call such as `__import__('os')`.
4. Confirm a clear rejection message and confirm the previous expression remains.
5. Save a deterministic arithmetic-only test expression whose effect is easy to
   identify in the PDF.
6. Confirm the expression and a later IST timestamp persist after redirect.

## Report verification

1. Generate through the dashboard.
2. Wait for the report row to show `generated` or `sent`; do not infer completion
   solely from the initial redirect.
3. Chrome may download `Download latest` instead of opening it inline. Open the
   downloaded file in Chrome's PDF viewer when needed.
4. Verify:
   - The test expression changes FCF by the expected amount.
   - FCFF remains independently calculated.
   - Legitimate positive and negative results are preserved.
   - Statement, publication, and capture dates are visible.
   - Official-source, Yahoo-comparison, freshness, and discrepancy text appears.
   - Raw and normalized capex values and formula inputs are shown.
5. Click at least one official-source link and confirm the expected HTTPS host.

## Restore and final artifact

1. Restore the default formula through the UI.
2. Generate a new final PDF after restoration.
3. Verify PDF text and annotations with `pypdf`, including:
   - Expected formulas and cash-flow values.
   - The stale-source replacement message.
   - Every expected official filing URL.
   - A non-zero hyperlink count.
4. Confirm the database stores the restored default expression.

## Common runtime behavior

- `yfinance` might be rate-limited. The direct Yahoo fallbacks should still
  complete the report; document whether fallback execution occurred.
- An isolated run without SMTP can be valid for formula/source testing. Report
  email delivery as untested rather than failed.
- Keep test screenshots, the final PDF, and the annotated recording outside the
  repository so they are not committed with implementation code.
