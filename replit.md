# Telegram IHSG Scanner Bot

AI-powered Telegram bot for scanning the Indonesian Stock Exchange (IDX).

## Stack
- **Language:** Python 3.11+
- **Bot framework:** python-telegram-bot 21.6
- **Data source:** Yahoo Finance v8 REST API (direct, no yfinance)
- **Data processing:** pandas, numpy, ta

## Project structure

| File | Purpose |
|------|---------|
| `main.py` | Bot entry point, message handlers, formatters |
| `config.py` | All tuneable constants (universe, filter thresholds) |
| `fetcher.py` | Concurrent Yahoo Finance downloader with 60s cache + query2 fallback |
| `screener.py` | Original screeners: BIG ACCUMULATION, BSJP, ARA HUNTER |
| `multi_screener.py` | Advanced screeners: BSJP Multi, Hybrid Trend, Scalping Harian, Swing Night GW |
| `top_gainer.py` | TOP GAINER HUNTER screener |
| `utils.py` | Shared numeric helpers (`_f`, `_ratio`) |

## How to run

Set the `TELEGRAM_BOT_TOKEN` secret in Replit Secrets, then start the workflow:

```
python main.py
```

The bot runs in polling mode by default.  
Set `WEBHOOK_URL` environment variable to switch to webhook mode (e.g. on a deployed server).

## Commands
- `/start` — welcome message + keyboard
- `/help` — screener guide
- `/status` — current market status and active auto-mode

## Screeners

### Keyboard buttons
| Button | Screener | Key criteria |
|--------|----------|-------------|
| 🔥 BIG ACCUMULATION | Bandar accumulation | A/D > 25, price < 500, vol surge |
| 📈 BSJP | Smart money | Vol > 2× MA20, gain > 1%, MA20 > MA50 |
| 🚀 ARA HUNTER | Near-ARA stocks | Gain > 5%, close > open, above MA5 |
| 🏆 TOP GAINER HUNTER | Top gainers | Gain > 2%, vol ratio > 1.5×, breakout |
| 📊 MULTI SCREENER | Sub-menu | See below |

### Multi screener sub-options
| Button | Description |
|--------|-------------|
| 🤖 AUTO | Time-based auto-selection (WIB) |
| 📈 MS:BSJP | RSI 45-70, MACD, Vol > 1.5× MA20 |
| 📊 MS:HYBRID TREND | ADX > 20, 3-day vol increase, MA20 > MA50 |
| ⚡ MS:SCALPING HARIAN | Vol > 10M, gain 3-15%, price > VWAP +1% |
| 🌙 MS:SWING NIGHT | Value > 5B IDR, ADX > 20, optimal 14:30–16:00 WIB |

## Auto Mode Schedule (WIB)
- 09:15–11:00 → ⚡ Scalping Harian
- 11:00–13:00 → 📈 BSJP Smart Money
- 13:00–14:30 → 📊 Hybrid Trend
- 14:30–16:00 → 🌙 Swing Night GW
- 16:00–16:30 → 📊 Hybrid Trend

## Required secrets
| Secret | Description |
|--------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |

## User preferences
- Keep existing screener filter logic intact unless explicitly asked to change it
- Indonesian language for bot messages
