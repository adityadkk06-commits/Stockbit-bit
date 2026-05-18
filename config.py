import os

# ─────────────────────────────────────────
# Telegram Bot Token (from environment)
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ─────────────────────────────────────────
# Indonesian Stock Universe
# IDX Blue-chip + liquid mid-cap tickers
# Add or remove tickers here freely
# ─────────────────────────────────────────
STOCK_UNIVERSE = [
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM",
    "ASII", "UNVR", "ICBP", "KLBF", "HMSP",
    "GOTO", "BREN", "AMMN", "MDKA", "ANTM",
    "PTBA", "ADRO", "INCO", "HRUM", "MBMA",
    "HUMI", "ITMG", "BYAN", "SMGR", "INDF",
    "CPIN", "JPFA", "MAPI", "LSIP", "AALI",
    "EXCL", "ISAT", "TOWR", "BFIN", "PGAS",
    "AKRA", "JSMR", "WIKA", "WSKT", "PTPP",
    "SIDO", "MYOR", "ULTJ", "GOOD", "STTP",
    "ACES", "MIKA", "HEAL", "SAME", "SIDO",
    "PNBN", "BDMN", "BJBR", "BJTM", "MEGA",
    "BMAS", "AGRO", "ARTO", "BRIS", "BTPS",
    "EMTK", "KOPI", "MNCN", "SCMA", "FILM",
    "SILO", "GGRM", "WIIM", "CLEO", "ADES",
    "INDS", "AUTO", "SMSM", "GJTL", "MASA",
    "MITI", "WIFI", "TFAS", "BUKA", "GOJEK",
    "NCKL", "NICL", "SBMA", "DEWA", "CUAN",
    "PGEO", "SMDR", "ASSA", "BIRD", "WEHA",
    "HERO", "RANC", "MPPA", "RALS", "MIDI",
    "KRAS", "TINS", "INDY", "BSSR", "FIRE",
]

# ─────────────────────────────────────────
# Screener Filter Settings
# Modify thresholds here easily
# ─────────────────────────────────────────

# BIG ACCUMULATION filter thresholds
BIG_ACCUM_FILTERS = {
    "min_value":          3_000_000_000,   # Min trade value (IDR)
    "max_price":          500,             # Max stock price
    "vol_surge_ratio":    1.3,             # Volume MA5 / Volume MA20
    "accum_dist_min":     25,              # Accumulation/Distribution min score (proxy)
}

# BSJP filter thresholds
BSJP_FILTERS = {
    "min_value":          10_000_000_000,  # Min trade value (IDR)
    "vol_vs_prev_ratio":  1.2,             # Volume > 1.2x previous
    "price_gain_ratio":   1.01,            # Price > 1.01x previous close
    "vol_vs_ma20_ratio":  2.0,             # Volume > 2x MA20
    "net_foreign_streak": 2,               # Consecutive net foreign buy days
}

# ARA HUNTER filter thresholds
ARA_FILTERS = {
    "min_value":          5_000_000_000,   # Min trade value (IDR)
    "price_gain_ratio":   1.05,            # Price > 1.05x previous close
    "vol_vs_prev_ratio":  0.2,             # Volume > 0.2x previous volume
}

# ─────────────────────────────────────────
# Result Settings
# ─────────────────────────────────────────
MAX_RESULTS = 10          # Show top N results
TP_PERCENT  = 0.05        # Take Profit: +5%
SL_PERCENT  = 0.03        # Stop Loss:   -3%

# yfinance download period & interval
DATA_PERIOD   = "3mo"     # Historical data period
DATA_INTERVAL = "1d"      # Candle interval
