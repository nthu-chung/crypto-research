"""
=============================================================
On-Chain Flow Return Prediction Strategy
Based on: Chi, Chu & Hao (2024) arXiv:2411.06327
=============================================================

研究問題：
  USDT net inflow 能否預測 BTC/ETH 未來 1~6h 報酬？
  ETH net inflow 對 ETH 報酬的負向預測效果？

策略架構：
  1. 數據收集：Binance API 取 OHLCV（代替 on-chain，先做可行性驗證）
  2. 信號構建：Flow proxy signal（用成交量不均衡代替）
  3. 預測模型：OLS → Ridge → 方向性信號
  4. 回測框架：Walk-forward with transaction cost
  5. 績效評估：Sharpe, Sortino, MaxDD, IC/ICIR
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import time
import warnings
warnings.filterwarnings('ignore')

# ─────────────────────────────────────────
# 1. 數據收集模組
# ─────────────────────────────────────────

class BinanceDataFetcher:
    """從 Binance 公開 API 取歷史 K 線數據"""

    BASE_URL = "https://api.binance.com/api/v3/klines"

    INTERVAL_MAP = {
        "1h": "1h",
        "4h": "4h",
        "1d": "1d",
    }

    def fetch_klines(self, symbol: str, interval: str,
                     start_str: str, end_str: str = None) -> pd.DataFrame:
        """
        取 Binance K 線數據
        symbol    : 如 'BTCUSDT'
        interval  : '1h', '4h', '1d'
        start_str : '2020-01-01'
        """
        start_ts = int(pd.Timestamp(start_str).timestamp() * 1000)
        end_ts   = int(pd.Timestamp(end_str).timestamp() * 1000) if end_str \
                   else int(datetime.now(timezone.utc).timestamp() * 1000)

        all_data = []
        current  = start_ts

        while current < end_ts:
            params = {
                "symbol":    symbol,
                "interval":  interval,
                "startTime": current,
                "endTime":   end_ts,
                "limit":     1000,
            }
            try:
                resp = requests.get(self.BASE_URL, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if not data:
                    break
                all_data.extend(data)
                current = data[-1][0] + 1  # 下一根 K 線起點
                if len(data) < 1000:
                    break
                time.sleep(0.1)  # rate limit
            except Exception as e:
                print(f"  ⚠️  Fetch error: {e}")
                break

        if not all_data:
            return pd.DataFrame()

        df = pd.DataFrame(all_data, columns=[
            "open_time","open","high","low","close","volume",
            "close_time","quote_vol","trades","taker_buy_vol",
            "taker_buy_quote_vol","ignore"
        ])
        df["open_time"]  = pd.to_datetime(df["open_time"],  unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
        numeric_cols = ["open","high","low","close","volume",
                        "quote_vol","taker_buy_vol","taker_buy_quote_vol"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        df = df.set_index("open_time").sort_index()
        return df


# ─────────────────────────────────────────
# 2. 信號構建模組
# ─────────────────────────────────────────

class OnChainFlowProxy:
    """
    用 Binance K 線中的 Taker Buy Volume 構建
    On-Chain Flow 的 Proxy Signal

    理論依據：
      - Taker Buy Vol / Total Vol → 買方主動成交比例
        ≈ Exchange Inflow 的代理（主動買入 ≈ 資金流入 CEX）
      - USDT 對 BTC/ETH 的 taker buy 可代替 USDT netflow

    注意：真實研究需用 CryptoQuant/Glassnode 的真實 on-chain data
          這裡先用 proxy 驗證框架可行性
    """

    def compute_flow_signal(self, df: pd.DataFrame,
                            window: int = 24) -> pd.DataFrame:
        """
        計算 Flow Proxy Signal

        F_t = (TakerBuyVol_t - TakerSellVol_t) / TotalVol_t
            = 2 * (TakerBuyVol / TotalVol) - 1
            ∈ [-1, +1]

        滾動標準化：Z_t = (F_t - mean(F, window)) / std(F, window)
        """
        df = df.copy()

        # Taker Sell Vol = Total Vol - Taker Buy Vol
        df["taker_sell_vol"] = df["volume"] - df["taker_buy_vol"]

        # Raw flow signal [-1, +1]
        df["flow_raw"] = (df["taker_buy_vol"] - df["taker_sell_vol"]) \
                         / df["volume"].replace(0, np.nan)

        # 滾動 Z-score 標準化（用 window 期）
        roll_mean = df["flow_raw"].rolling(window, min_periods=window//2).mean()
        roll_std  = df["flow_raw"].rolling(window, min_periods=window//2).std()
        df["flow_z"] = (df["flow_raw"] - roll_mean) / roll_std.replace(0, np.nan)

        # 對數報酬
        df["log_return"] = np.log(df["close"] / df["close"].shift(1))

        return df

    def compute_cross_asset_signal(self,
                                   usdt_df: pd.DataFrame,
                                   eth_df:  pd.DataFrame,
                                   btc_df:  pd.DataFrame) -> pd.DataFrame:
        """
        複合信號（對應論文的兩個核心發現）：
          Signal_USDT = USDT 買壓 → 正向預測 BTC/ETH（資金流入 signal）
          Signal_ETH  = ETH 買壓  → 負向預測 ETH（賣壓 signal）
        """
        # 對齊時間軸
        combined = pd.DataFrame(index=btc_df.index)
        combined["btc_return"]  = np.log(btc_df["close"] / btc_df["close"].shift(1))
        combined["eth_return"]  = np.log(eth_df["close"] / eth_df["close"].shift(1))
        combined["usdt_flow_z"] = usdt_df["flow_z"].reindex(combined.index)
        combined["eth_flow_z"]  = eth_df["flow_z"].reindex(combined.index)
        combined["btc_flow_z"]  = btc_df["flow_z"].reindex(combined.index)

        # 前向報酬（預測目標）h = 1, 2, 4, 6 小時
        for h in [1, 2, 4, 6]:
            combined[f"btc_fwd_{h}h"] = combined["btc_return"].shift(-h).rolling(h).sum()
            combined[f"eth_fwd_{h}h"] = combined["eth_return"].shift(-h).rolling(h).sum()

        return combined.dropna(subset=["usdt_flow_z","eth_flow_z"])


# ─────────────────────────────────────────
# 3. 預測模型模組
# ─────────────────────────────────────────

class FlowPredictionModel:
    """
    OLS 線性預測模型（基準）
    r_{t+h} = α + β1*F_USDT_t + β2*F_ETH_t + β3*r_t + ε
    """

    def fit_ols(self, X: pd.DataFrame, y: pd.Series):
        """簡單 OLS，回傳係數與統計量"""
        from numpy.linalg import lstsq

        X_mat = np.column_stack([np.ones(len(X)), X.values])
        coefs, _, _, _ = lstsq(X_mat, y.values, rcond=None)

        # 計算 t-stats
        y_hat    = X_mat @ coefs
        residuals = y.values - y_hat
        n, k     = X_mat.shape
        s2       = (residuals**2).sum() / (n - k)
        try:
            cov = s2 * np.linalg.inv(X_mat.T @ X_mat)
        except np.linalg.LinAlgError:
            # 矩陣奇異時用 pseudoinverse
            cov = s2 * np.linalg.pinv(X_mat.T @ X_mat)
        se       = np.sqrt(np.diag(cov))
        t_stats  = coefs / se
        p_vals   = 2 * (1 - self._t_cdf(np.abs(t_stats), df=n-k))

        return {
            "coefs":   coefs,
            "t_stats": t_stats,
            "p_vals":  p_vals,
            "names":   ["const"] + list(X.columns),
            "r2":      1 - (residuals**2).sum() / ((y - y.mean())**2).sum()
        }

    def _t_cdf(self, t, df):
        from scipy.stats import t as t_dist
        return t_dist.cdf(t, df)

    def compute_ic(self, signals: pd.Series, returns: pd.Series) -> float:
        """
        IC = Spearman rank correlation(signal_t, return_{t+h})
        衡量信號的排序預測能力
        """
        from scipy.stats import spearmanr
        mask = signals.notna() & returns.notna()
        if mask.sum() < 10:
            return np.nan
        ic, _ = spearmanr(signals[mask], returns[mask])
        return ic


# ─────────────────────────────────────────
# 4. 回測框架
# ─────────────────────────────────────────

class WalkForwardBacktest:
    """
    Walk-Forward 回測
    避免 lookahead bias，模擬真實交易環境

    時間軸：
    |── Train ──|── Test ──|── Test ──|── ...
    擴展窗口（expanding window）：train 逐步增大
    """

    def __init__(self,
                 transaction_cost: float = 0.001,   # 0.1%（含 slippage）
                 min_train_periods: int  = 500,      # 最少 500 小時訓練
                 refit_every: int        = 168):     # 每 168 小時（1週）重新訓練
        self.tc             = transaction_cost
        self.min_train      = min_train_periods
        self.refit_every    = refit_every

    def run(self, data: pd.DataFrame,
            feature_cols: list,
            target_col:   str,
            signal_threshold: float = 0.3) -> pd.DataFrame:
        """
        執行 Walk-Forward 回測

        Parameters:
          data             : 包含特徵與目標的 DataFrame
          feature_cols     : 信號特徵欄位
          target_col       : 預測目標（前向報酬）
          signal_threshold : 進場閾值（Z-score）

        Returns:
          回測結果 DataFrame（每期持倉、報酬、累積報酬）
        """
        results = []
        model   = FlowPredictionModel()
        prev_pos = 0

        for i in range(self.min_train, len(data), self.refit_every):
            # ── 訓練集（expanding window）
            train = data.iloc[:i].dropna(subset=feature_cols + [target_col])
            if len(train) < self.min_train // 2:
                continue

            X_train = train[feature_cols]
            y_train = train[target_col]

            # ── 在訓練集估計 OLS 係數
            fit = model.fit_ols(X_train, y_train)
            coefs = fit["coefs"]

            # ── 測試集（下一個 refit_every 期）
            test_end = min(i + self.refit_every, len(data))
            test     = data.iloc[i:test_end].dropna(subset=feature_cols)

            for idx, row in test.iterrows():
                x_vec    = np.array([1.0] + [row[c] for c in feature_cols])
                pred_ret = x_vec @ coefs

                # ── 信號轉倉位
                # 標準化預測值（用訓練集的 std 標準化）
                pred_std = y_train.std()
                pred_z   = pred_ret / pred_std if pred_std > 0 else 0

                if pred_z > signal_threshold:
                    position = 1.0
                elif pred_z < -signal_threshold:
                    position = -1.0
                else:
                    position = 0.0

                # ── 實際報酬（下一期）
                actual_ret = data.loc[idx, target_col] \
                             if target_col in data.columns else np.nan

                # ── 交易成本（倉位改變時才收）
                cost = self.tc * abs(position - prev_pos)

                results.append({
                    "datetime":     idx,
                    "position":     position,
                    "pred_z":       pred_z,
                    "actual_ret":   actual_ret,
                    "gross_pnl":    position * actual_ret if not np.isnan(actual_ret) else 0,
                    "net_pnl":      position * actual_ret - cost if not np.isnan(actual_ret) else -cost,
                    "cost":         cost,
                    "train_size":   len(train),
                })
                prev_pos = position

        if not results:
            return pd.DataFrame()

        res_df = pd.DataFrame(results).set_index("datetime")
        res_df["cumulative_pnl"] = res_df["net_pnl"].cumsum()
        return res_df


# ─────────────────────────────────────────
# 5. 績效評估模組
# ─────────────────────────────────────────

class PerformanceAnalyzer:

    def compute_metrics(self, pnl_series: pd.Series,
                        freq_per_year: int = 8760) -> dict:
        """
        計算完整績效指標
        freq_per_year: 1h = 8760, 4h = 2190, 1d = 365
        """
        pnl = pnl_series.dropna()
        if len(pnl) < 2:
            return {}

        ann_factor = np.sqrt(freq_per_year)

        # 基本統計
        mean_ret = pnl.mean()
        std_ret  = pnl.std()

        # Sharpe（年化）
        sharpe = (mean_ret / std_ret * ann_factor) if std_ret > 0 else 0

        # Sortino（只用下行波動）
        downside = pnl[pnl < 0].std()
        sortino  = (mean_ret / downside * ann_factor) if downside > 0 else 0

        # Max Drawdown
        cum     = pnl.cumsum()
        rolling_max = cum.cummax()
        drawdown = cum - rolling_max
        max_dd   = drawdown.min()

        # Calmar
        ann_ret = mean_ret * freq_per_year
        calmar  = (ann_ret / abs(max_dd)) if max_dd != 0 else 0

        # Hit Rate
        hit_rate = (pnl > 0).mean()

        # Win/Loss Ratio
        avg_win  = pnl[pnl > 0].mean() if (pnl > 0).any() else 0
        avg_loss = abs(pnl[pnl < 0].mean()) if (pnl < 0).any() else 0
        wl_ratio = (avg_win / avg_loss) if avg_loss > 0 else np.inf

        return {
            "Ann. Return":   f"{ann_ret*100:.2f}%",
            "Ann. Vol":      f"{std_ret * ann_factor * 100:.2f}%",
            "Sharpe":        f"{sharpe:.3f}",
            "Sortino":       f"{sortino:.3f}",
            "Max Drawdown":  f"{max_dd*100:.2f}%",
            "Calmar":        f"{calmar:.3f}",
            "Hit Rate":      f"{hit_rate*100:.1f}%",
            "Win/Loss":      f"{wl_ratio:.2f}x",
            "N Trades":      int((pnl != 0).sum()),
            "Total PnL":     f"{pnl.sum()*100:.2f}%",
        }

    def compute_ic_series(self, signals: pd.Series,
                          returns: pd.Series,
                          window: int = 30) -> dict:
        """
        滾動 IC 與 ICIR
        IC   = mean(monthly Spearman corr)
        ICIR = IC / std(IC)
        """
        from scipy.stats import spearmanr

        ic_list = []
        for i in range(window, len(signals)):
            s = signals.iloc[i-window:i]
            r = returns.iloc[i-window:i]
            mask = s.notna() & r.notna()
            if mask.sum() < 5:
                ic_list.append(np.nan)
                continue
            ic, _ = spearmanr(s[mask], r[mask])
            ic_list.append(ic)

        ic_series = pd.Series(ic_list, index=signals.index[window:])
        ic_mean   = ic_series.mean()
        ic_std    = ic_series.std()
        icir      = ic_mean / ic_std if ic_std > 0 else 0

        return {
            "IC Mean":  f"{ic_mean:.4f}",
            "IC Std":   f"{ic_std:.4f}",
            "ICIR":     f"{icir:.3f}",
            "IC > 0%":  f"{(ic_series > 0).mean()*100:.1f}%",
        }


# ─────────────────────────────────────────
# 6. 主程序
# ─────────────────────────────────────────

def main():
    print("=" * 60)
    print("  On-Chain Flow Return Prediction Strategy")
    print("  Based on: Chi, Chu & Hao (2024) arXiv:2411.06327")
    print("=" * 60)

    # ── Step 1: 取數據
    print("\n📥 Step 1: 下載 Binance 歷史數據...")
    fetcher = BinanceDataFetcher()
    proxy   = OnChainFlowProxy()

    symbols = {
        "BTCUSDT":  "2021-01-01",
        "ETHUSDT":  "2021-01-01",
        "BUSDUSDT": "2021-01-01",   # BUSD flow proxy（USDT 穩定幣流動性代理）
    }

    raw_data = {}
    for sym, start in symbols.items():
        print(f"  → {sym} from {start}...")
        df = fetcher.fetch_klines(sym, "1h", start, "2024-12-31")
        if df.empty:
            print(f"    ⚠️  No data for {sym}")
            continue
        df = proxy.compute_flow_signal(df)
        raw_data[sym] = df
        print(f"    ✅ {len(df)} rows, {df.index[0].date()} ~ {df.index[-1].date()}")

    if len(raw_data) < 2:
        print("❌ 數據不足，請檢查網路連線")
        return

    # ── Step 2: 構建特徵矩陣
    print("\n🔧 Step 2: 構建信號特徵...")
    btc_df  = raw_data.get("BTCUSDT", pd.DataFrame())
    eth_df  = raw_data.get("ETHUSDT", pd.DataFrame())
    usdt_df = raw_data.get("BUSDUSDT", pd.DataFrame())

    # 對齊時間軸
    common_idx = btc_df.index.intersection(eth_df.index)
    if not usdt_df.empty:
        common_idx = common_idx.intersection(usdt_df.index)

    data = pd.DataFrame(index=common_idx)
    data["btc_ret"]      = np.log(btc_df["close"] / btc_df["close"].shift(1)).reindex(common_idx)
    data["eth_ret"]      = np.log(eth_df["close"] / eth_df["close"].shift(1)).reindex(common_idx)
    data["btc_flow_z"]   = btc_df["flow_z"].reindex(common_idx)
    data["eth_flow_z"]   = eth_df["flow_z"].reindex(common_idx)

    if not usdt_df.empty:
        data["usdt_flow_z"] = usdt_df["flow_z"].reindex(common_idx)
    else:
        data["usdt_flow_z"] = 0.0

    # 前向報酬（預測目標）
    for h in [1, 2, 4, 6]:
        data[f"btc_fwd_{h}h"] = data["btc_ret"].rolling(h).sum().shift(-h)
        data[f"eth_fwd_{h}h"] = data["eth_ret"].rolling(h).sum().shift(-h)

    data = data.dropna(subset=["btc_flow_z", "eth_flow_z", "btc_ret", "eth_ret"])
    print(f"  ✅ 特徵矩陣: {len(data)} 行 × {len(data.columns)} 列")
    print(f"  📅 時間範圍: {data.index[0].date()} ~ {data.index[-1].date()}")

    # ── Step 3: OLS 預測分析（靜態，全樣本）
    print("\n📊 Step 3: OLS 回歸分析（全樣本，僅供參考）")
    model = FlowPredictionModel()
    analyzer = PerformanceAnalyzer()

    print("\n  ┌─ BTC 前向報酬預測 ─────────────────────────────┐")
    for h in [1, 2, 4, 6]:
        target = f"btc_fwd_{h}h"
        features = ["usdt_flow_z", "btc_flow_z", "btc_ret"]
        subset   = data[features + [target]].dropna()
        if len(subset) < 100:
            continue
        fit = model.fit_ols(subset[features], subset[target])
        print(f"  h={h}h  R²={fit['r2']:.4f}", end="  |  ")
        for name, coef, tstat, pval in zip(
                fit["names"], fit["coefs"], fit["t_stats"], fit["p_vals"]):
            sig = "***" if pval < 0.01 else ("**" if pval < 0.05 else ("*" if pval < 0.1 else ""))
            print(f"{name}:{coef:.4f}(t={tstat:.2f}{sig})", end="  ")
        print()

    print("\n  ┌─ ETH 前向報酬預測 ─────────────────────────────┐")
    for h in [1, 2, 4, 6]:
        target   = f"eth_fwd_{h}h"
        features = ["usdt_flow_z", "eth_flow_z", "eth_ret"]
        subset   = data[features + [target]].dropna()
        if len(subset) < 100:
            continue
        fit = model.fit_ols(subset[features], subset[target])
        print(f"  h={h}h  R²={fit['r2']:.4f}", end="  |  ")
        for name, coef, tstat, pval in zip(
                fit["names"], fit["coefs"], fit["t_stats"], fit["p_vals"]):
            sig = "***" if pval < 0.01 else ("**" if pval < 0.05 else ("*" if pval < 0.1 else ""))
            print(f"{name}:{coef:.4f}(t={tstat:.2f}{sig})", end="  ")
        print()

    # ── Step 4: IC 分析
    print("\n📐 Step 4: IC / ICIR 分析")
    for signal_col, target_col, label in [
        ("usdt_flow_z", "btc_fwd_1h", "USDT→BTC (1h)"),
        ("usdt_flow_z", "eth_fwd_1h", "USDT→ETH (1h)"),
        ("eth_flow_z",  "eth_fwd_1h", "ETH→ETH  (1h)"),
        ("btc_flow_z",  "btc_fwd_1h", "BTC→BTC  (1h)"),
    ]:
        subset = data[[signal_col, target_col]].dropna()
        if len(subset) < 50:
            continue
        ic_stats = analyzer.compute_ic_series(
            subset[signal_col], subset[target_col], window=30)
        print(f"  {label:20s}  IC={ic_stats['IC Mean']:>8s}  "
              f"ICIR={ic_stats['ICIR']:>7s}  IC>0%={ic_stats['IC > 0%']}")

    # ── Step 5: Walk-Forward 回測
    print("\n🔄 Step 5: Walk-Forward 回測")
    backtester = WalkForwardBacktest(
        transaction_cost=0.001,
        min_train_periods=500,
        refit_every=168
    )

    for target_asset, feature_list, target_col in [
        ("BTC", ["usdt_flow_z", "btc_flow_z", "btc_ret"], "btc_fwd_1h"),
        ("ETH", ["usdt_flow_z", "eth_flow_z", "eth_ret"], "eth_fwd_1h"),
    ]:
        print(f"\n  ── {target_asset} / 1h horizon ──")
        bt_data = data[feature_list + [target_col]].dropna()
        results = backtester.run(
            data=bt_data,
            feature_cols=feature_list,
            target_col=target_col,
            signal_threshold=0.3
        )
        if results.empty:
            print("    ⚠️  回測無結果")
            continue

        metrics = analyzer.compute_metrics(
            results["net_pnl"], freq_per_year=8760)
        print(f"  {'指標':<15} {'值':>10}")
        print(f"  {'-'*26}")
        for k, v in metrics.items():
            print(f"  {k:<15} {str(v):>10}")

        # 儲存結果
        results.to_csv(
            f"/root/.openclaw/workspace/research/backtest_{target_asset}_1h.csv")
        print(f"  💾 結果已儲存: backtest_{target_asset}_1h.csv")

    print("\n✅ 分析完成！")
    print("─" * 60)
    print("📌 注意：此版本使用 Taker Buy Vol 作為 On-Chain Flow Proxy")
    print("        真實研究需替換為 CryptoQuant/Glassnode Exchange Netflow")
    print("─" * 60)


if __name__ == "__main__":
    main()
