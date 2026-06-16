# 📊 Daily Market Pulse

Automated daily financial intelligence report delivered to your inbox as a beautiful, interactive PDF.

## What You Get

Every morning, a professionally designed PDF arrives in your inbox with **four segments**:

### 🇮🇳 Indian Markets
- **Nifty 50 & Sensex** index levels with daily/monthly/yearly changes
- **Top 15 Indian stocks** (Reliance, TCS, HDFC Bank, Infosys, etc.) with:
  - Market cap, open/close prices, previous day comparison
  - Monthly and yearly percentage changes
  - **Full DuPont Analysis**: ROE, net profit margin, asset turnover, equity multiplier, tax burden, interest burden, operating margin
- **Gold, Silver, Oil** prices in USD and INR ETFs with daily/monthly/yearly changes
- **5 AI-curated news articles** + 1 out-of-the-box piece
- AI-generated market summary with forward-looking outlook

### 🇺🇸 US Markets
- **S&P 500, NASDAQ, Dow Jones** with full change metrics
- **Top 15 US stocks** (Apple, Microsoft, NVIDIA, etc.) with identical metrics and DuPont ratios
- **5 curated US financial news** + AI summary

### 🌍 International Markets
- **FTSE 100** and global commodities (Brent, Natural Gas, Copper)
- Full commodities overview table
- **5 key international news articles** + global summary

### 📊 Deep Dive
- Each day spotlights **one Indian** and **one US** top company
- Annual financial statement highlights (revenue, net income, EBITDA, total assets, debt, free cash flow)
- Direct links to **BSE filings, SEC EDGAR 10-K** reports

## Smart Features

- **Weekend handling**: Skips tradable commodity prices on Sat/Sun; shows last trading day data
- **AI article filtering**: GPT-4o-mini ranks articles by market impact, investor relevance, depth, readership trends, and predictive value
- **No repeat articles**: SQLite-backed deduplication ensures you never see the same article twice
- **Mailing list management**: Simple web dashboard to add/remove/pause recipients
- **Manual trigger**: Generate and send a report instantly from the dashboard
- **Unsubscribe link**: Every email includes a one-click unsubscribe

## Setup Guide (Non-Technical)

### What You Need

| Item | Cost | How to Get It |
|------|------|---------------|
| **OpenAI API Key** | ~$0.02/day | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) → Create new key |
| **Gmail App Password** | Free | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) → Generate |
| **Fly.io Account** | Free tier works | [fly.io/app/sign-up](https://fly.io/app/sign-up) |

### Step-by-Step Deployment

#### 1. Clone & Configure

```bash
git clone https://github.com/alishakanwar-crypto/daily-financial-report.git
cd daily-financial-report
cp .env.example .env
```

Edit `.env` with your keys:
```
OPENAI_API_KEY=sk-...
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-gmail-app-password
```

#### 2. Run Locally (Optional)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Visit `http://localhost:8000` to manage the mailing list.

#### 3. Deploy to Fly.io

```bash
# Install Fly CLI (one-time)
curl -L https://fly.io/install.sh | sh

# Login and deploy
fly auth login
fly launch          # First time — creates the app
fly secrets set OPENAI_API_KEY="sk-..." SMTP_USER="you@gmail.com" SMTP_PASSWORD="your-app-password"
fly deploy

# Create persistent storage for the database
fly volumes create data --size 1 --region sin
fly deploy
```

Your app will be live at `https://daily-market-pulse.fly.dev`

#### 4. Add Yourself to the Mailing List

Visit `https://daily-market-pulse.fly.dev` and add your email address.

That's it! Reports will arrive daily at 7:00 AM IST by default.

### Customizing the Schedule

All scheduling uses IST (Asia/Kolkata). Edit `fly.toml` or set environment variables:
```bash
fly secrets set REPORT_HOUR_IST=7 REPORT_MINUTE_IST=0
```

### Customizing Stocks

Set custom stock lists via environment variables (JSON arrays):
```bash
fly secrets set INDIAN_STOCKS='["RELIANCE.NS","TCS.NS","HDFCBANK.NS"]'
fly secrets set US_STOCKS='["AAPL","MSFT","NVDA","AMZN"]'
```

## Architecture

```
daily-financial-report/
├── app/
│   ├── main.py              # FastAPI app + APScheduler
│   ├── config.py            # Env-based configuration
│   ├── database.py          # SQLite (recipients, dedup, logs)
│   ├── data/
│   │   ├── stocks.py        # yfinance stock + DuPont data
│   │   ├── commodities.py   # Gold, silver, oil, indices
│   │   └── financials.py    # Deep-dive company financials
│   ├── news/
│   │   ├── fetcher.py       # RSS feed aggregation
│   │   └── ai_filter.py     # GPT-4o-mini article ranking
│   ├── report/
│   │   ├── generator.py     # Data collection + PDF generation
│   │   ├── email_sender.py  # SMTP email with PDF attachment
│   │   └── templates/
│   │       └── report.html  # Jinja2 + WeasyPrint PDF template
│   ├── routes/
│   │   └── dashboard.py     # Web UI for mailing list mgmt
│   └── templates/
│       ├── dashboard.html   # Dashboard UI
│       └── unsubscribe.html # Unsubscribe page
├── Dockerfile
├── fly.toml
├── requirements.txt
└── .env.example
```

## Data Sources

- **Stock prices**: [Yahoo Finance](https://finance.yahoo.com) via `yfinance`
- **News**: RSS feeds from Financial Times, Wall Street Journal, Economic Times, Bloomberg, Reuters, CNBC, MoneyControl, LiveMint, BBC, The Guardian, and more
- **AI curation**: OpenAI GPT-4o-mini for article ranking and summarization
- **Financial statements**: Yahoo Finance annual data + links to SEC EDGAR and BSE India

## Security Notes

- API keys are stored as **environment variables**, never in code
- On Fly.io, use `fly secrets set` — secrets are encrypted at rest
- The dashboard has no authentication by default — add `APP_SECRET` and a middleware if exposing publicly
- All email communication uses TLS encryption

## License

MIT
