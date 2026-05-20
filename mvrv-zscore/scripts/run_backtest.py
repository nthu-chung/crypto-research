import requests, pandas as pd, numpy as np, time, warnings
warnings.filterwarnings('ignore')

def fetch(symbol, interval="1h", start="2023-01-01", end="2024-12-31"):
    url = "https://api.binance.com/api/v3/klines"
    s = int(pd.Timestamp(start).timestamp()*1000)
    e = int(pd.Timestamp(end).timestamp()*1000)
    rows, cur = [], s
    while cur < e:
        r = requests.get(url, params=dict(symbol=symbol,interval=interval,startTime=cur,endTime=e,limit=1000), timeout=10)
        d = r.json()
        if not d: break
        rows.extend(d); cur = d[-1][0]+1
        if len(d)<1000: break
        time.sleep(0.05)
    cols=["ot","open","high","low","close","vol","ct","qvol","trades","tbv","tbqv","x"]
    df=pd.DataFrame(rows,columns=cols)
    df["ot"]=pd.to_datetime(df["ot"],unit="ms",utc=True)
    for c in ["close","vol","tbv"]: df[c]=df[c].astype(float)
    df=df.set_index("ot")
    df["ret"]=np.log(df["close"]/df["close"].shift(1))
    df["flow_z"]=(((df["tbv"]-(df["vol"]-df["tbv"]))/df["vol"].replace(0,np.nan)).rolling(6).mean()-
                  ((df["tbv"]-(df["vol"]-df["tbv"]))/df["vol"].replace(0,np.nan)).rolling(24).mean())/\
                 ((df["tbv"]-(df["vol"]-df["tbv"]))/df["vol"].replace(0,np.nan)).rolling(24).std().replace(0,np.nan)
    df["ma200"]=df["close"].rolling(200).mean()
    df["vol_spike"]=df["vol"]/df["vol"].rolling(168).mean().replace(0,np.nan)
    df["ret_z"]=df["ret"].rolling(24).apply(lambda x:(x[-1]-x.mean())/x.std() if x.std()>0 else 0)
    return df.dropna()

print("下載數據...")
btc=fetch("BTCUSDT"); eth=fetch("ETHUSDT"); sol=fetch("SOLUSDT")
print(f"BTC:{len(btc)} ETH:{len(eth)} SOL:{len(sol)}")

idx=btc.index.intersection(eth.index).intersection(sol.index)
TC=0.001
ANN=8760

def backtest_signal(signal_series, ret_series, pos_rule, tc=TC):
    results=[]; prev=0
    for i in range(len(signal_series)):
        s=signal_series.iloc[i]; r=ret_series.iloc[i]
        if np.isnan(s) or np.isnan(r): prev=0; continue
        pos=pos_rule(s)
        cost=tc*abs(pos-prev)
        results.append({"net":pos*r-cost,"pos":pos})
        prev=pos
    if not results: return None
    df=pd.DataFrame(results)
    pnl=df["net"]
    cum=pnl.cumsum()
    ar=pnl.mean()*ANN; av=pnl.std()*np.sqrt(ANN)
    sh=ar/av if av>0 else 0
    mdd=(cum-cum.cummax()).min()
    return {"AnnRet":ar,"Sharpe":sh,"MaxDD":mdd,"N":(df["pos"]!=0).sum()}

print("\n=== 策略A：BTC-ETH 資金輪動對沖 ===")
# BTC flow高/ETH flow低 → 做空BTC做多ETH
diff = btc["flow_z"].reindex(idx) - eth["flow_z"].reindex(idx)
for thresh in [1.0, 1.5, 2.0]:
    r_btc=btc["ret"].reindex(idx); r_eth=eth["ret"].reindex(idx)
    pnl=[]; prev_pos_b=0; prev_pos_e=0
    for i in range(len(idx)):
        d=diff.iloc[i]; rb=r_btc.iloc[i]; re=r_eth.iloc[i]
        if np.isnan(d): continue
        if d>thresh:    pb,pe=-1,+1   # BTC過熱→空BTC多ETH
        elif d<-thresh: pb,pe=+1,-1   # ETH過熱→多BTC空ETH
        else:           pb,pe=0,0
        cost=TC*(abs(pb-prev_pos_b)+abs(pe-prev_pos_e))/2
        pnl.append((pb*rb+pe*re)/2 - cost)
        prev_pos_b=pb; prev_pos_e=pe
    if pnl:
        p=pd.Series(pnl); ar=p.mean()*ANN; av=p.std()*np.sqrt(ANN)
        sh=ar/av if av>0 else 0; mdd=(p.cumsum()-p.cumsum().cummax()).min()
        print(f"  thresh={thresh:.1f}  Sharpe={sh:.3f}  AnnRet={ar*100:.1f}%  MaxDD={mdd*100:.1f}%  N={int((p!=0).sum())}")

print("\n=== 策略B：均值回歸多空（3幣各自）===")
for sym, df in [("BTC",btc),("ETH",eth),("SOL",sol)]:
    sub=df.reindex(idx).dropna()
    res=backtest_signal(sub["ret_z"],sub["ret"],
        lambda s: -1.0 if s>2.0 else (1.0 if s<-2.0 else 0.0))
    if res: print(f"  {sym}  Sharpe={res['Sharpe']:.3f}  AnnRet={res['AnnRet']*100:.1f}%  MaxDD={res['MaxDD']*100:.1f}%  N={res['N']}")

print("\n=== 策略C：Regime-Filtered 多空（BTC MA200）===")
btc_ma200=btc["ma200"].reindex(idx)
btc_price=btc["close"].reindex(idx)
for sym, df in [("BTC",btc),("ETH",eth),("SOL",sol)]:
    sub=df.reindex(idx)
    pnl=[]; prev=0
    for i in range(len(idx)):
        fz=sub["flow_z"].iloc[i]; r=sub["ret"].iloc[i]
        ma=btc_ma200.iloc[i]; pr=btc_price.iloc[i]
        if np.isnan(fz) or np.isnan(r) or np.isnan(ma): prev=0; continue
        bull=(pr>ma); bear=(pr<ma)
        q80=sub["flow_z"].iloc[max(0,i-720):i].quantile(0.90) if i>100 else 1.0
        q20=sub["flow_z"].iloc[max(0,i-720):i].quantile(0.10) if i>100 else -1.0
        if bull and fz<q20: pos=1.0      # 牛市+超跌→做多
        elif bear and fz>q80: pos=-1.0   # 熊市+過熱→做空
        else: pos=0.0
        cost=TC*abs(pos-prev); pnl.append(pos*r-cost); prev=pos
    if pnl:
        p=pd.Series(pnl); ar=p.mean()*ANN; av=p.std()*np.sqrt(ANN)
        sh=ar/av if av>0 else 0; mdd=(p.cumsum()-p.cumsum().cummax()).min()
        n=int((p!=0).sum())
        print(f"  {sym}  Sharpe={sh:.3f}  AnnRet={ar*100:.1f}%  MaxDD={mdd*100:.1f}%  N={n}")

print("\n=== 策略D：3幣等權組合（各自信號，1/vol加權）===")
all_pnl={}
for sym, df in [("BTC",btc),("ETH",eth),("SOL",sol)]:
    sub=df.reindex(idx); pnl=[]; prev=0
    vols=sub["ret"].rolling(168).std()
    for i in range(len(idx)):
        fz=sub["flow_z"].iloc[i]; r=sub["ret"].iloc[i]
        if np.isnan(fz) or np.isnan(r): prev=0; pnl.append(0); continue
        q80=sub["flow_z"].iloc[max(0,i-500):i].quantile(0.90) if i>100 else 1.0
        q20=sub["flow_z"].iloc[max(0,i-500):i].quantile(0.10) if i>100 else -1.0
        pos=-1.0 if fz>q80 else (1.0 if fz<q20 else 0.0)
        cost=TC*abs(pos-prev); pnl.append(pos*r-cost); prev=pos
    all_pnl[sym]=pd.Series(pnl,index=idx[:len(pnl)])

port=pd.DataFrame(all_pnl).mean(axis=1)
ar=port.mean()*ANN; av=port.std()*np.sqrt(ANN)
sh=ar/av if av>0 else 0; mdd=(port.cumsum()-port.cummax()).min()
print(f"  等權組合  Sharpe={sh:.3f}  AnnRet={ar*100:.1f}%  MaxDD={mdd*100:.1f}%")
print("\n  年度分解：")
port_df=pd.DataFrame({"net":port}); port_df["year"]=port_df.index.year
for yr,g in port_df.groupby("year"):
    p=g["net"]; ar2=p.mean()*ANN; av2=p.std()*np.sqrt(ANN)
    sh2=ar2/av2 if av2>0 else 0
    print(f"  {yr}  AnnRet={ar2*100:.1f}%  Sharpe={sh2:.3f}")

print("\n✅完成")
