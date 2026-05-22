"""
Crypto Taxonomy Table
手動維護，按需更新。分類邏輯：
  - category: fundamental narrative group
  - bucket: trading behavior group (high_beta / mid_beta / low_beta / meme / stable_alt)
"""

TAXONOMY = {
    # L1 - Smart Contract Platforms
    "SOLUSDT":   {"category": "L1",       "bucket": "high_beta"},
    "AVAXUSDT":  {"category": "L1",       "bucket": "high_beta"},
    "ADAUSDT":   {"category": "L1",       "bucket": "mid_beta"},
    "DOTUSDT":   {"category": "L1",       "bucket": "mid_beta"},
    "NEARUSDT":  {"category": "L1",       "bucket": "high_beta"},
    "APTUSDT":   {"category": "L1",       "bucket": "high_beta"},
    "SUIUSDT":   {"category": "L1",       "bucket": "high_beta"},
    "TONUSDT":   {"category": "L1",       "bucket": "high_beta"},
    "TRXUSDT":   {"category": "L1",       "bucket": "mid_beta"},
    "XLMUSDT":   {"category": "L1",       "bucket": "mid_beta"},
    "ATOMUSDT":  {"category": "L1",       "bucket": "mid_beta"},
    "ALGOUSDT":  {"category": "L1",       "bucket": "mid_beta"},
    "FTMUSDT":   {"category": "L1",       "bucket": "high_beta"},
    "SEIUSDT":   {"category": "L1",       "bucket": "high_beta"},

    # L2 - Ethereum Scaling
    "MATICUSDT": {"category": "L2",       "bucket": "high_beta"},
    "ARBUSDT":   {"category": "L2",       "bucket": "high_beta"},
    "OPUSDT":    {"category": "L2",       "bucket": "high_beta"},
    "STRKUSDT":  {"category": "L2",       "bucket": "high_beta"},
    "IMXUSDT":   {"category": "L2",       "bucket": "high_beta"},
    "ZKUSDT":    {"category": "L2",       "bucket": "high_beta"},

    # DeFi
    "AAVEUSDT":  {"category": "DeFi",     "bucket": "mid_beta"},
    "UNIUSDT":   {"category": "DeFi",     "bucket": "mid_beta"},
    "CRVUSDT":   {"category": "DeFi",     "bucket": "high_beta"},
    "MKRUSDT":   {"category": "DeFi",     "bucket": "mid_beta"},
    "COMPUSDT":  {"category": "DeFi",     "bucket": "mid_beta"},
    "SNXUSDT":   {"category": "DeFi",     "bucket": "high_beta"},
    "JUPUSDT":   {"category": "DeFi",     "bucket": "high_beta"},
    "RUNEUSDT":  {"category": "DeFi",     "bucket": "high_beta"},
    "DYDXUSDT":  {"category": "DeFi",     "bucket": "high_beta"},
    "GMXUSDT":   {"category": "DeFi",     "bucket": "mid_beta"},
    "SUSHIUSDT": {"category": "DeFi",     "bucket": "high_beta"},
    "1INCHUSDT": {"category": "DeFi",     "bucket": "mid_beta"},

    # Exchange / CeFi
    "BNBUSDT":   {"category": "Exchange", "bucket": "mid_beta"},
    "OKBUSDT":   {"category": "Exchange", "bucket": "mid_beta"},

    # Meme
    "DOGEUSDT":  {"category": "Meme",     "bucket": "meme"},
    "SHIBUSDT":  {"category": "Meme",     "bucket": "meme"},
    "PEPEUSDT":  {"category": "Meme",     "bucket": "meme"},
    "FLOKIUSDT": {"category": "Meme",     "bucket": "meme"},
    "WIFUSDT":   {"category": "Meme",     "bucket": "meme"},
    "BONKUSDT":  {"category": "Meme",     "bucket": "meme"},
    "MEMEUSDT":  {"category": "Meme",     "bucket": "meme"},
    "TRUMPUSDT": {"category": "Meme",     "bucket": "meme"},

    # AI / Data
    "RENDERUSDT":{"category": "AI",       "bucket": "high_beta"},
    "TAOUSDT":   {"category": "AI",       "bucket": "high_beta"},
    "FETUSDT":   {"category": "AI",       "bucket": "high_beta"},
    "AGIXUSDT":  {"category": "AI",       "bucket": "high_beta"},
    "OCEANUSDT": {"category": "AI",       "bucket": "high_beta"},
    "WLDUSDT":   {"category": "AI",       "bucket": "high_beta"},
    "AKTUSDT":   {"category": "AI",       "bucket": "high_beta"},

    # Gaming / Metaverse
    "GALAUSDT":  {"category": "Gaming",   "bucket": "high_beta"},
    "SANDUSDT":  {"category": "Gaming",   "bucket": "high_beta"},
    "AXSUSDT":   {"category": "Gaming",   "bucket": "high_beta"},
    "ENJUSDT":   {"category": "Gaming",   "bucket": "mid_beta"},
    "YGGUSDT":   {"category": "Gaming",   "bucket": "high_beta"},
    "RONUSDT":   {"category": "Gaming",   "bucket": "high_beta"},

    # Infra / Oracle
    "LINKUSDT":  {"category": "Infra",    "bucket": "mid_beta"},
    "PYTHUSDT":  {"category": "Infra",    "bucket": "high_beta"},
    "API3USDT":  {"category": "Infra",    "bucket": "high_beta"},
    "BANDUSDT":  {"category": "Infra",    "bucket": "mid_beta"},
    "STXUSDT":   {"category": "Infra",    "bucket": "high_beta"},
    "LTCUSDT":   {"category": "Infra",    "bucket": "mid_beta"},

    # Storage
    "FILUSDT":   {"category": "Storage",  "bucket": "high_beta"},
    "ARUSDT":    {"category": "Storage",  "bucket": "high_beta"},

    # Privacy
    "XMRUSDT":   {"category": "Privacy",  "bucket": "mid_beta"},
    "ZECUSDT":   {"category": "Privacy",  "bucket": "mid_beta"},

    # Risk Factors (excluded from altcoin universe, used as factors)
    "BTCUSDT":   {"category": "RF",       "bucket": "rf_btc"},
    "ETHUSDT":   {"category": "RF",       "bucket": "rf_eth"},
}

RISK_FACTORS = ["BTCUSDT", "ETHUSDT"]
EXCLUDE_ALWAYS = {"BTCUSDT", "ETHUSDT"}  # not in alt universe

# Stablecoins and wrapped assets to exclude
STABLE_AND_WRAPPED = {
    "USDCUSDT", "BUSDUSDT", "TUSDUSDT", "USDPUSDT", "DAIUSDT",
    "FDUSDUSDT", "EURUSDT",
    "WBTCUSDT", "WETHUSDT", "STETHUSDT", "CBETHUSDT",
}

def get_category(symbol: str) -> str:
    return TAXONOMY.get(symbol, {}).get("category", "Unknown")

def get_bucket(symbol: str) -> str:
    return TAXONOMY.get(symbol, {}).get("bucket", "unknown")
