import requests, pandas as pd, numpy as np, time, warnings
from scipy.stats import spearmanr
warnings.filterwarnings('ignore')

def fetch_daily(symbol, start="2020-01-01", end="2024-12-31"):
    url = "https://api.binance.com/api/v3/klines"
    s = int(pd.Timestamp(start).timestamp()*1000)
    e = int(pd.Timestamp(end).timestamp()*1000)
    rows, cur = [], s
    while cur < e:
        r = requests.get(url, params=dict(symbol=symbol, interval="1d",
                         startTime=cur, endTime=e, limit=1000), timeout=10)
        d = r.json()
        if not d: break
        rows.extend(d); cur = d[-1][0]+1
        if len(d) < 1000: break
        time.sleep(0.05)
    if not rows: return None
    cols = ["ot","open","high","low","close","vol","ct","qvol","trades","tbv","tbqv","x"]
    df = pd.DataFrame(rows, columns=cols)
    df["ot"] = pd.to_datetime(df["ot"], unit="ms", utc=True)
    for c in ["close","vol","tbv"]: df[c] = df[c].astype(float)
    df = df.set_index("ot").sort_index()
    df["ret"] = np.log(df["close"] / df["close"].shift(1))
    df["mom_5d"] = df["ret"].rolling(5).sum()
    df["mom_10d"] = df["ret"].rolling(10).sum()
    df["mom_20d"] = df["ret"].rolling(20).sum()
    df["ret_z_5d"] = df["ret"].rolling(5).apply(lambda x: (x[-1]-x.mean())/x.std() if x.std()>0 else 0)
    df["vol_ratio"] = df["vol"] / df["vol"].rolling(20).mean().replace(0, np.nan)
    df["ma50"] = df["close"].rolling(50).mean()
    df["ma200"] = df["close"].rolling(200).mean()
    df["atr"] = (df["high"].astype(float) - df["low"].astype(float)).rolling(14).mean() / df["close"]
    return df.dropna()

SYMBOLS = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
           "DOGEUSDT","ADAUSDT","AVAXUSDT","LINKUSDT","DOTUSDT",
           "TRXUSDT","NEARUSDT","UNIUSDT","LTCUSDT","AAVEUSDT",
           "INJUSDT","XLMUSDT","FILUSDT","ATOMUSDT"]

print("📥 下載數據...")
data = {}
for sym in SYMBOLS:
    df = fetch_daily(sym)
    if df is not None and len(df) > 300:
        data[sym] = df
        print(f"  {sym}: {len(df)}d")
    time.sleep(0.1)

ANN = 252
TC = 0.002

# ══════════════════════════════════════════════
# Part 1: ICIR 全面分析（多個 horizon）
# ══════════════════════════════════════════════
print("\n=== ICIR 分析（Mom_5d 反向信號）===")
print(f"{'幣種':12s} {'IC_mean':>9s} {'IC_std':>8s} {'ICIR':>8s} {'IC>0%':>7s} {'N':>5s}")
print("─"*55)

icir_data = {}
for sym, df in data.items():
    fwd = df["ret"].shift(-1)
    sub = pd.concat([df["mom_5d"], fwd], axis=1).dropna()
    sub.columns = ["s","f"]
    W = 20
    ics = [spearmanr(sub["s"].iloc[i-W:i], sub["f"].iloc[i-W:i])[0] for i in range(W, len(sub))]
    ics = np.array(ics)
    ic_mean = np.nanmean(ics)
    ic_std = np.nanstd(ics)
    icir = ic_mean/ic_std if ic_std > 0 else 0
    ic_pos = (ics > 0).mean()
    icir_data[sym] = {"ic_mean":ic_mean,"icir":icir,"ics":ics}
    star = "⭐" if abs(icir)>0.15 else ""
    print(f"{sym:12s} {ic_mean:>+9.4f} {ic_std:>8.4f} {icir:>+8.3f} {ic_pos*100:>6.1f}% {len(ics):>5d} {star}")

# ══════════════════════════════════════════════
# Part 2: Walk-Forward 回測（多個參數）
# ══════════════════════════════════════════════
print("\n=== Walk-Forward 回測：Mom_5d 反向 ===")
print("參數掃描：threshold=Q80/Q90, holding=1/3d, TC=0.1%/0.2%")
print()

def wf_bt(df, sig_col, direction, q_thresh=0.80, hold=1, tc=0.002,
          train_min=252, refit=21):
    fwd = df["ret"].rolling(hold).sum().shift(-hold)
    sub = pd.concat([df[sig_col], fwd], axis=1).dropna()
    sub.columns = ["sig","fwd"]
    n = len(sub); results = []; prev = 0; hold_cnt = 0
    for i in range(train_min, n, refit):
        q_hi = sub["sig"].iloc[:i].quantile(q_thresh)
        q_lo = sub["sig"].iloc[:i].quantile(1-q_thresh)
        for j in range(i, min(i+refit, n-hold)):
            s = sub["sig"].iloc[j]; r = sub["fwd"].iloc[j]
            if np.isnan(s) or np.isnan(r): prev=0; continue
            if hold_cnt > 0:
                pos = prev; hold_cnt -= 1
            elif direction == "contra":
                if s > q_hi: pos = -1.0; hold_cnt = hold-1
                elif s < q_lo: pos = 1.0; hold_cnt = hold-1
                else: pos = 0.0
            cost = tc * abs(pos-prev)
            results.append({"dt":sub.index[j],"pos":pos,"net":pos*r-cost})
            prev = pos
    if not results: return None
    res = pd.DataFrame(results).set_index("dt")
    pnl = res["net"]
    cum = pnl.cumsum()
    ar = pnl.mean()*ANN; av = pnl.std()*np.sqrt(ANN)
    sh = ar/av if av>0 else 0
    down = pnl[pnl<0].std()*np.sqrt(ANN)
    so = ar/down if down>0 else 0
    mdd = (cum-cum.cummax()).min()
    return {"Sharpe":sh,"Sortino":so,"AnnRet":ar,"MaxDD":mdd,
            "N":int((res["pos"]!=0).sum()),"res":res}

# 掃描最佳參數
best_by_sym = {}
print(f"{'幣種':12s} {'Q':>4s} {'Hold':>5s} {'TC':>6s} {'Sharpe':>8s} {'AnnRet':>8s} {'MaxDD':>8s} {'Sortino':>8s}")
print("─"*70)
for sym, df in data.items():
    best = None
    for q in [0.80, 0.85, 0.90]:
        for hold in [1, 3, 5]:
            for tc in [0.001, 0.002]:
                r = wf_bt(df, "mom_5d", "contra", q_thresh=q, hold=hold, tc=tc)
                if r and (best is None or r["Sharpe"] > best["Sharpe"]):
                    best = r; best["q"]=q; best["hold"]=hold; best["tc"]=tc
    if best:
        best_by_sym[sym] = best
        flag = " ⭐" if best["Sharpe"]>0.5 else (" ✅" if best["Sharpe"]>0 else "")
        print(f"{sym:12s} {best['q']:>4.2f} {best['hold']:>5d} {best['tc']*100:>5.1f}% "
              f"{best['Sharpe']:>+8.3f} {best['AnnRet']*100:>+7.1f}% "
              f"{best['MaxDD']*100:>7.1f}% {best['Sortino']:>+8.3f}{flag}")

# ══════════════════════════════════════════════
# Part 3: 最佳幣別深度分析（前5名）
# ══════════════════════════════════════════════
top5 = sorted(best_by_sym.items(), key=lambda x: x[1]["Sharpe"], reverse=True)[:5]
print("\n=== 前5名幣別年度績效分解 ===")
for sym, r in top5:
    res = r["res"]
    print(f"\n{sym} (Sharpe={r['Sharpe']:+.3f}, Q={r['q']:.2f}, Hold={r['hold']}d, TC={r['tc']*100:.1f}%)")
    print(f"  {'年份':6s} {'AnnRet':>8s} {'Sharpe':>8s} {'MaxDD':>8s}")
    res2 = res.copy(); res2["year"] = res2.index.year
    for yr, g in res2.groupby("year"):
        p=g["net"]; ar=p.mean()*ANN; av=p.std()*np.sqrt(ANN)
        sh=ar/av if av>0 else 0; cum=p.cumsum(); mdd=(cum-cum.cummax()).min()
        print(f"  {yr:6d} {ar*100:>+7.1f}% {sh:>+8.3f} {mdd*100:>7.1f}%")

# ══════════════════════════════════════════════
# Part 4: 等權組合（全部正Sharpe幣種）
# ══════════════════════════════════════════════
print("\n=== 等權組合（全部幣種，Mom_5d 反向）===")
pos_syms = [(sym, r) for sym, r in best_by_sym.items() if r["Sharpe"] > 0]
print(f"正Sharpe幣種數：{len(pos_syms)}")

if pos_syms:
    # 對齊日期
    all_pnl = {}
    for sym, r in pos_syms:
        all_pnl[sym] = r["res"]["net"]
    port = pd.DataFrame(all_pnl).mean(axis=1).dropna()
    ar=port.mean()*ANN; av=port.std()*np.sqrt(ANN)
    sh=ar/av if av>0 else 0
    down=port[port<0].std()*np.sqrt(ANN)
    so=ar/down if down>0 else 0
    cum=port.cumsum(); mdd=(cum-cum.cummax()).min()
    calmar=ar/abs(mdd) if mdd!=0 else 0
    print(f"\n  Sharpe={sh:+.3f}  Sortino={so:+.3f}  AnnRet={ar*100:+.1f}%  MaxDD={mdd*100:.1f}%  Calmar={calmar:.3f}")
    print(f"\n  年度分解：")
    port_df=pd.DataFrame({"net":port}); port_df["year"]=port_df.index.year
    for yr,g in port_df.groupby("year"):
        p=g["net"]; ar2=p.mean()*ANN; av2=p.std()*np.sqrt(ANN)
        sh2=ar2/av2 if av2>0 else 0
        cum2=p.cumsum(); mdd2=(cum2-cum2.cummax()).min()
        print(f"  {yr}  AnnRet={ar2*100:+.1f}%  Sharpe={sh2:+.3f}  MaxDD={mdd2*100:.1f}%")

print("\n✅ 完成！")
