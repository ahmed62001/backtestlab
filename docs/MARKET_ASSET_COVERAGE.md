# Market Asset Coverage

Registry of all market instruments with their verified data status.
Generated from `backend/app/instruments.py` on 2026-11-13, updated with real-provider verification.
Statuses:
- `LIVE_VERIFIED` — genuine provider price event received and shown in the browser.
- `DELAYED_ONLY` — delayed/end-of-day REST works; live streaming unverified per symbol.
- `REFERENCE_ONLY` — reference rates (Frankfurter), not executable quotes.
- `ENTITLEMENT_REQUIRED` — needs a keyed provider/streaming plan.
- `UNSUPPORTED` — no source at all.

Real verification (2026-11-13): Twelve Data WS ticks for BTC/USD, AAPL (provider-ts age 6s) and EUR/USD; GBP/USD rejected on trial entitlement; Massive real-time endpoints 403 (upgrade required); FRED observations 200 (macro daily).

| Symbol | Name | Class | Quote | Providers | Stream symbol | Status | Evidence | Backtest |
|---|---|---|---|---|---|---|---|---|

### equity

| `005930.KS` | Samsung Electronics | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `005930.KS` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `0700.HK` | Tencent Holdings | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `0700.HK` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `1120.SR` | Al Rajhi Bank | equity | SAR | yfinance | `1120.SR` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `2222.SR` | Saudi Aramco | equity | SAR | yfinance | `2222.SR` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `AAPL` | Apple Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `AAPL` | `LIVE_VERIFIED` | Genuine Twelve Data WS tick received + visible in browser (2026-11-13). | yes |
| `AMD` | Advanced Micro Devices | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `AMD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `AMZN` | Amazon.com Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `AMZN` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `ASML` | ASML Holding (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `ASML` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `AVGO` | Broadcom Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `AVGO` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `BABA` | Alibaba Group (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `BABA` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `BRK-B` | Berkshire Hathaway B | equity | USD | yfinance, stooq, alphavantage, polygon | `BRK.B` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `COST` | Costco Wholesale Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `COST` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `CVX` | Chevron Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `CVX` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `GOOG` | Alphabet Inc. Class C | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `GOOG` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `GOOGL` | Alphabet Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `GOOGL` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `INTC` | Intel Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `INTC` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `JNJ` | Johnson & Johnson | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `JNJ` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `JPM` | JPMorgan Chase & Co. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `JPM` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `LLY` | Eli Lilly and Company | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `LLY` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `MA` | Mastercard Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `MA` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `META` | Meta Platforms Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `META` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `MSFT` | Microsoft Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `MSFT` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `MU` | Micron Technology Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `MU` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `NFLX` | Netflix Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `NFLX` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `NVDA` | NVIDIA Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `NVDA` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `NVO` | Novo Nordisk (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `NVO` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `ORCL` | Oracle Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `ORCL` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `PG` | Procter & Gamble Co. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `PG` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `PLTR` | Palantir Technologies | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `PLTR` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `SAP` | SAP SE (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `SAP` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `SHEL` | Shell plc (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `SHEL` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `SPY` | SPDR S&P 500 ETF Trust | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `SPY` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `TM` | Toyota Motor (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `TM` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `TSLA` | Tesla Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `TSLA` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `TSM` | Taiwan Semiconductor (ADR) | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `TSM` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `V` | Visa Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `V` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `WMT` | Walmart Inc. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `WMT` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `XOM` | Exxon Mobil Corp. | equity | USD | yfinance, stooq, alphavantage, polygon, twelvedata | `XOM` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |

### crypto

| `ADA-USD` | Cardano / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `ADA/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `BNB-USD` | Binance Coin / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `BNB/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `BTC-USD` | Bitcoin / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `BTC/USD` | `LIVE_VERIFIED` | Genuine Twelve Data WS tick received + visible in browser (2026-11-13). | yes |
| `BTC-USDT` | Bitcoin / Tether | crypto | USDT | binance_public, ccxt, twelvedata, polygon | `BTC-USDT` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `DOGE-USD` | Dogecoin / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `DOGE/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `ETH-USD` | Ethereum / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `ETH/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `ETH-USDT` | Ethereum / Tether | crypto | USDT | binance_public, ccxt, twelvedata, polygon | `ETH-USDT` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `SOL-USD` | Solana / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `SOL/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `TRX-USD` | Tron / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `TRX/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |
| `XRP-USD` | XRP / US Dollar | crypto | USD | binance_public, ccxt, yfinance, twelvedata, polygon | `XRP/USD` | `DELAYED_ONLY` | Twelve Data REST polling is real-time-capable; streaming not individually tested. | yes |

### fx

| `AUDUSD` | Australian Dollar / US Dollar | fx | USD | twelvedata, polygon | `AUDUSD` | `REFERENCE_ONLY` | Frankfurter ECB reference quotes only; live FX needs a keyed provider. | no |
| `EURGBP` | Euro / British Pound | fx | GBP | twelvedata, polygon | `EURGBP` | `REFERENCE_ONLY` | Frankfurter ECB reference quotes only; live FX needs a keyed provider. | no |
| `EURUSD` | Euro / US Dollar | fx | USD | twelvedata, polygon | `EUR/USD` | `LIVE_VERIFIED` | Genuine Twelve Data WS tick received + visible in browser (2026-11-13). | no |
| `GBPUSD` | British Pound / US Dollar | fx | USD | twelvedata, polygon | `GBP/USD` | `REFERENCE_ONLY` | Frankfurter ECB reference quotes only; live FX needs a keyed provider. | no |
| `NZDUSD` | New Zealand Dollar / US Dollar | fx | USD | twelvedata, polygon | `NZDUSD` | `ENTITLEMENT_REQUIRED` | Not covered by Frankfurter; Twelve Data/Polygon (keyed). | no |
| `USDCAD` | US Dollar / Canadian Dollar | fx | CAD | twelvedata, polygon | `USDCAD` | `REFERENCE_ONLY` | Frankfurter ECB reference quotes only; live FX needs a keyed provider. | no |
| `USDCHF` | US Dollar / Swiss Franc | fx | CHF | twelvedata, polygon | `USDCHF` | `REFERENCE_ONLY` | Frankfurter ECB reference quotes only; live FX needs a keyed provider. | no |
| `USDCNH` | US Dollar / Chinese Yuan (offshore) | fx | CNH | twelvedata, polygon | `USDCNH` | `ENTITLEMENT_REQUIRED` | Not covered by Frankfurter; Twelve Data/Polygon (keyed). | no |
| `USDEGP` | US Dollar / Egyptian Pound | fx | EGP | twelvedata, polygon | `USDEGP` | `ENTITLEMENT_REQUIRED` | Not covered by Frankfurter; Twelve Data/Polygon (keyed). | no |
| `USDJPY` | US Dollar / Japanese Yen | fx | JPY | twelvedata, polygon | `USD/JPY` | `REFERENCE_ONLY` | Frankfurter ECB reference quotes only; live FX needs a keyed provider. | no |

### index

| `^DJI` | Dow Jones | index | USD | yfinance | `^DJI` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^FTSE` | FTSE 100 | index | GBP | yfinance | `FTSE` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^GDAXI` | DAX 40 | index | EUR | yfinance | `GDAXI` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^GSPC` | S&P 500 | index | USD | yfinance | `^GSPC` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^HSI` | Hang Seng | index | HKD | yfinance | `HSI` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^IXIC` | NASDAQ 100 | index | USD | yfinance | `^IXIC` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^N225` | Nikkei 225 | index | JPY | yfinance | `N225` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^NDX` | NASDAQ 100 | index | USD | yfinance | `NDX` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^RUT` | Russell 2000 | index | USD | yfinance | `RUT` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `^TASI` | Tadawul All Share Index | index | SAR | yfinance | `TASI` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |

### commodity

| `BZ=F` | Brent Crude Oil futures | commodity | USD | yfinance | `BZ=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `CC=F` | Cocoa Futures contract | commodity | USD | yfinance | `CC=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `CL=F` | Crude oil futures | commodity | USD | yfinance | `CL=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `GC=F` | Gold futures | commodity | USD | yfinance | `GC=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `HG=F` | Copper Futures contract | commodity | USD | yfinance | `HG=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `HO=F` | Heating Oil futures | commodity | USD | yfinance | `HO=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `KC=F` | Coffee Futures contract | commodity | USD | yfinance | `KC=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `NG=F` | Natural Gas futures | commodity | USD | yfinance | `NG=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `PA=F` | Palladium futures | commodity | USD | yfinance | `PA=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `PL=F` | Platinum futures | commodity | USD | yfinance | `PL=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `RB=F` | RBOB Gasoline futures | commodity | USD | yfinance | `RB=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `SB=F` | Sugar Futures contract | commodity | USD | yfinance | `SB=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `SI=F` | Silver futures | commodity | USD | yfinance | `SI=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `XAG/USD` | Silver Spot | commodity | USD | twelvedata, polygon | `XAG/USD` | `ENTITLEMENT_REQUIRED` | Spot metals stream via Twelve Data/Polygon (keyed); no keyless source. | no |
| `XAU/USD` | Gold Spot | commodity | USD | twelvedata, polygon | `XAU/USD` | `ENTITLEMENT_REQUIRED` | Spot metals stream via Twelve Data/Polygon (keyed); no keyless source. | no |
| `XPD/USD` | Palladium Spot | commodity | USD | twelvedata, polygon | `XPD/USD` | `ENTITLEMENT_REQUIRED` | Spot metals stream via Twelve Data/Polygon (keyed); no keyless source. | no |
| `XPT/USD` | Platinum Spot | commodity | USD | twelvedata, polygon | `XPT/USD` | `ENTITLEMENT_REQUIRED` | Spot metals stream via Twelve Data/Polygon (keyed); no keyless source. | no |
| `ZC=F` | Corn Futures contract | commodity | USD | yfinance | `ZC=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `ZS=F` | Soybean Futures contract | commodity | USD | yfinance | `ZS=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
| `ZW=F` | Wheat Futures contract | commodity | USD | yfinance | `ZW=F` | `DELAYED_ONLY` | yfinance REST (delayed/EOD); Twelve Data REST preferred when keyed. | yes |
