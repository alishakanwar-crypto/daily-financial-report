---
name: testing-official-financial-sources
description: Test the solar report's official-statement sourcing, INR normalization, source-link validation, and financial formula audit in a generated PDF.
---

# Testing Official Financial Sources

Use this workflow when financial-source registries, ratios, FCF/FCFF formulas, link validation, or the PDF financial tables change.

## Devin Secrets Needed

- None for a focused deterministic financial PDF render.
- `OPENAI_API_KEY` only for full live news-analysis generation.
- `SMTP_USER` and `SMTP_PASSWORD` only for actual email-delivery testing.
- `APP_SECRET` only for authenticated dashboard/browser testing.

## Setup

```bash
source venv/bin/activate
```

The focused financial test should bypass OpenAI/news/SMTP and build report data directly from:

- `solar.config.DEFAULT_COMPANIES`
- `solar.data.ratios._company_ratios`
- `solar.report.generator.render_report_html`

Render with WeasyPrint, then inspect the PDF with PyMuPDF (`fitz`) for text and embedded links.

## High-value assertions

1. Every configured listed company has an official registry row and `financial_currency == "INR"`.
2. Known source-unit conversions remain exact:
   - INR crore × `10,000,000`
   - INR lakh × `100,000`
   - INR million × `1,000,000`
3. Missing official inputs remain `None`/`N/A`; never infer zero or use Yahoo.
4. FCF uses `operating_cf - capex`, with capex normalized to a positive outflow.
5. FCFF uses `operating_cf + interest_expense * (1 - tax_rate) - capex`.
6. Every displayed calculated metric has formula, input values, source URLs, result, and unit.
7. PDF URLs returning HTML are `invalid`; official 401/403/429 responses are `blocked`, not silently valid.
8. The generated PDF embeds links to official sources and contains no Yahoo URL as a statement source.

## Visual inspection

Open the PDF in Chrome's built-in viewer and inspect:

- Official Statement Comparison
- Liquidity, Leverage & Efficiency
- Cash Flow Quality
- Company source-audit cards
- Formula & Input Ledger
- Official-only disclaimer

Record the browser inspection with structured annotations. Capture full-screen screenshots of the comparison, validation cards, and formula ledger.

## Standard checks

```bash
source venv/bin/activate
ruff check solar tests
python -m compileall -q solar tests
python -m unittest discover -s tests -v
git diff --check
```

When an exact document is blocked or invalid, verify that the report visibly explains the status and provides a stable official landing-page fallback. Do not treat automated-access blocking as proof that the filing itself is dead.
