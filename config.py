import os

# ─────────────────────────────────────────
# Telegram Bot Token (from environment)
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ─────────────────────────────────────────
# Indonesian Stock Universe — IDX
# Covers blue-chip, mid-cap and liquid small-caps.
# Add / remove tickers freely (no .JK suffix needed here).
# ─────────────────────────────────────────
STOCK_UNIVERSE = sorted(set([
    # LQ45 / IDX30 core
    "BBCA", "BBRI", "BMRI", "BBNI", "TLKM",
    "ASII", "UNVR", "ICBP", "KLBF", "HMSP",
    "GOTO", "BREN", "AMMN", "MDKA", "ANTM",
    "PTBA", "ADRO", "INCO", "HRUM", "MBMA",
    "HUMI", "ITMG", "BYAN", "SMGR", "INDF",
    "CPIN", "JPFA", "MAPI", "LSIP", "AALI",
    "EXCL", "ISAT", "TOWR", "BFIN", "PGAS",
    "AKRA", "JSMR", "WIKA", "WSKT", "PTPP",
    "MYOR", "ULTJ", "GOOD", "STTP",
    "ACES", "MIKA", "HEAL", "SAME", "SIDO",
    "PNBN", "BDMN", "BJBR", "BJTM", "MEGA",
    "BMAS", "AGRO", "ARTO", "BRIS", "BTPS",
    "EMTK", "MNCN", "SCMA", "FILM",
    "SILO", "GGRM", "WIIM", "CLEO", "ADES",
    "INDS", "AUTO", "SMSM", "GJTL", "MASA",
    "NCKL", "DEWA", "CUAN",
    "PGEO", "SMDR", "ASSA", "BIRD", "WEHA",
    "HERO", "RANC", "MPPA", "RALS", "MIDI",
    "KRAS", "TINS", "INDY", "BSSR", "FIRE",
    # Extended liquid mid-caps
    "AMRT", "ERAA", "MIKA", "HEAL", "SILO",
    "TSPC", "KAEF", "DVLA", "PYFA", "MERK",
    "MTDL", "MLPL", "RELI", "LINK", "BTEL",
    "FREN", "TBIG", "SUPR", "OBMD",
    "UNTR", "HEXA", "TURI", "MPMX", "NMST",
    "NIKL", "DKFT", "ANTM", "PSAB", "GTBO",
    "MITI", "WIFI", "TFAS", "BUKA",
    "SBMA", "SMCB", "WTON", "ADHI", "NRCA",
    "ACST", "TOTL", "DGIK", "PBSA",
    "BWPT", "SGRO", "TBLA", "PALM", "SSMS",
    "DSFI", "CPRO", "MAIN", "MBTO", "SMBR",
    "KDSI", "TRST", "IGAR", "IMPC", "IPOL",
    "TKIM", "INKP", "ALDO", "FASW", "SPMA",
    "INAI", "KRAS", "NIKL", "LION", "LMSH",
    "BAJA", "GDST", "ISSP", "JKSW",
    "GJTL", "SMSM", "NIPS", "PRAS", "BOLT",
    "GMFI", "GIAA", "CMPP", "HATM",
    "TPMA", "MBSS", "BULL", "HITS", "INDX",
    "LPKR", "BSDE", "CTRA", "PWON", "SMRA",
    "APLN", "DILD", "EMDE", "GPRA", "KIJA",
    "MKPI", "MTLA", "PLIN", "PUDP", "RDTX",
    "ROCK", "RODA", "SMCB", "APLN",
    "LPPF", "MCAS", "MAPI", "RALS", "TELE",
    "CSAP", "KOIN", "GOLD", "ATIC",
    "MLBI", "DLTA", "FOOD", "CEKA", "BUDI",
    "AISA", "CAMP", "KEJU", "SKLT", "STTP",
    "TGKA", "WMUU",
    "PGAS", "AKRA", "MEDC", "ELSA", "APEX",
    "ENRG", "ESSA", "RUIS",
    "WEGE", "IDPR", "MTPS",
    "KBLI", "VOKS", "SCCO", "JECC",
    "ASRI", "BEST", "DMAS", "JRPT", "KOTA",
    "PANI", "SATU",
    "BBKP", "BGTG", "BINA", "BMRI", "BNBA",
    "BNGA", "BNII", "BPII", "BSIM", "MCOR",
    "NISP", "NOBU", "PNBS", "SDRA", "TRIM",
    "VRNA",
    "ABMM", "DSSA", "GEMS", "GTBO", "ITMG",
    "MYOH", "PKPK", "PTRO", "SMMT",
    "BTEL", "CENT", "DATA", "JAST",
    "MTIX", "SRSN", "TALF", "UNIC",
    "AMFG", "ARNA", "KIAS", "MLIA", "TOTO",
    "GGRM", "RMBA", "WIIM",
    "ASDM", "ASMI", "LPGI", "MREI", "PNIN",
    "ASRM", "JMAS",
    "CMNP", "META", "NELY", "PTIS",
    "TGRA", "WICO",
]))

# ─────────────────────────────────────────
# Download settings
# ─────────────────────────────────────────
DATA_PERIOD       = "6mo"   # Historical data period (longer = more MA50 data)
DATA_INTERVAL     = "1d"    # Candle interval
MIN_ROWS          = 55      # Minimum candle rows needed (covers MA50)
BATCH_SIZE        = 50      # Tickers per yfinance batch download
RETRY_ATTEMPTS    = 2       # Retries on failed individual download
RETRY_DELAY_SEC   = 1.5     # Seconds between retries

# ─────────────────────────────────────────
# Screener Filter Settings
# ─────────────────────────────────────────

# BIG ACCUMULATION filter thresholds (exact values from screener config)
BIG_ACCUM_FILTERS = {
    "accum_dist_min":  25,              # Bandar Accum/Dist > 25
    "min_value":       3_000_000_000,  # Value > 3,000,000,000
    "max_price":       500,            # Price < 500
    "vol_surge_ratio": 1.3,            # Volume MA5 > 1.3 x Volume MA20
    # MA20 > MA50 and Price > Previous Price checked directly in filter
}

# BSJP filter thresholds (exact values from screener config)
BSJP_FILTERS = {
    "min_value":          10_000_000_000, # Value > 10,000,000,000
    "vol_vs_prev_ratio":  1.2,            # Volume > 1.2 x Previous Volume
    "price_gain_ratio":   1.01,           # Price > 1.01 x Previous Price
    "vol_vs_ma20_ratio":  2.0,            # Volume > 2 x Volume MA20
    "net_foreign_streak": 2,              # Net Foreign Buy Streak >= 2
    # Price > MA20, MA20 > MA50, Price >= MA5 checked directly in filter
}

# ARA HUNTER filter thresholds (exact values from screener config)
ARA_FILTERS = {
    "price_gain_ratio": 1.05,           # Price > 1.05 x Previous Price
    "vol_vs_prev_ratio": 0.2,           # Volume > 0.2 x Previous Volume
    "min_value":        5_000_000_000,  # Value > 5,000,000,000
    # Price > MA5 and Price > Open checked directly in filter
}

# ─────────────────────────────────────────
# Result Settings
# ─────────────────────────────────────────
MAX_RESULTS = 10          # Show top N results
TP_PERCENT  = 0.05        # Take Profit: +5%
SL_PERCENT  = 0.03        # Stop Loss:   -3%

