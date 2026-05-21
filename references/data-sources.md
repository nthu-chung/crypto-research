# Data Sources

Use public, reproducible sources first. If a paid or unavailable source is replaced by a proxy, the Research report must say so explicitly.

## CoinMetrics Community API

Best for BTC on-chain and long-history daily research.

Base URL: `https://community-api.coinmetrics.io/v4`

| Metric | Use |
|---|---|
| `PriceUSD` | BTC daily USD price |
| `CapMVRVCur` | MVRV ratio |
| `CapMrktCurUSD` | Market cap |

Notes:

- No API key required for community metrics.
- Use pagination with `next_page_token`.
- Sort ascending after downloading.
- Some useful metrics, such as realized cap components, may require paid access.

## Binance Spot API

Best for spot OHLCV, simple BTC/ETH baselines, and spot-only strategies.

Base URL: `https://api.binance.com`

| Endpoint | Use |
|---|---|
| `GET /api/v3/klines` | Spot candles |
| `GET /api/v3/ticker/price` | Current spot price |
| `GET /api/v3/exchangeInfo` | Trading rules, lot size, tick size |

Research requirements:

- Record symbol, interval, start/end time, and timezone.
- Use close time carefully to avoid trading on an unfinished candle.
- Apply fees and minimum trade constraints if modeling execution.

## Binance USD-M Futures API

Best for perpetual futures, long/short strategies, funding-aware research, and cross-sectional futures universes.

Base URL: `https://fapi.binance.com`

| Endpoint | Use |
|---|---|
| `GET /fapi/v1/exchangeInfo` | Current futures universe and contract metadata |
| `GET /fapi/v1/klines` | USD-M futures candles |
| `GET /fapi/v1/fundingRate` | Historical funding rates |
| `GET /fapi/v1/premiumIndex` | Current mark/index/funding data |
| `GET /fapi/v1/ticker/24hr` | Volume and liquidity snapshots |

Research requirements:

- Futures universes based on current `exchangeInfo` can contain survivorship bias.
- For historical cross-sectional studies, report whether delisted contracts are included.
- Funding, taker fees, and liquidation/margin assumptions must be separate from price return.
- Volume or market-cap rankings must use the previous known period, not the traded period.

## Binance eAPI Options

Best for option-chain snapshots and approximate options overlays.

Base URL: `https://eapi.binance.com`

| Endpoint | Use |
|---|---|
| `GET /eapi/v1/mark` | Option mark price and mark IV |
| `GET /eapi/v1/depth` | Option order book depth |
| `GET /eapi/v1/index` | Underlying index price |
| `GET /eapi/v1/exchangeInfo` | Option symbols and expiries |

Research requirements:

- Historical option chains may not be fully available through public endpoints.
- Any Black-Scholes or fixed-IV assumption must be labeled as an approximation.
- Bid/ask spread and liquidity are central, not optional.

## CoinGecko API

Best for broad spot market metadata and current market-cap snapshots.

Base URL: `https://api.coingecko.com/api/v3`

| Endpoint | Use |
|---|---|
| `GET /coins/markets` | Current market cap and volume rankings |
| `GET /coins/{id}/market_chart/range` | Historical price, market cap, volume where available |

Research requirements:

- Public API historical ranges may be limited.
- Current market-cap mappings are not valid historical universe membership.
- If used as a proxy, label it clearly.

## Suggested Source by Research Type

| Research type | Preferred source |
|---|---|
| BTC on-chain valuation | CoinMetrics |
| Spot buy-and-hold baseline | Binance Spot or CoinMetrics PriceUSD |
| Perpetual trend / long-short | Binance USD-M Futures |
| Funding strategies | Binance USD-M Futures funding endpoints |
| Options overlay | Binance eAPI, with clear liquidity caveats |
| Broad current market-cap proxy | CoinGecko |
| Historical market-cap universe | Paid CoinGecko/CoinMarketCap or a documented proxy |

## Standard Cost Defaults

- Binance futures taker fee: `config.fee_bps`, default `4`.
- Slippage: default `0` unless strategy turnover or liquidity requires a proxy.
- Funding: include separately for perpetual strategies when possible.
- Options: use bid/ask or conservative spread assumptions; do not treat mark price as executable without caveats.
