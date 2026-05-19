#!/usr/bin/env python3
"""Check which CoinMetrics community metrics are available."""
import requests, json, time, sys

def fetch_coinmetrics(metrics, start="2020-01-01", page_size=100):
    url = "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics"
    all_data = []
    params = {
        "assets": "btc",
        "metrics": metrics,
        "frequency": "1d",
        "start_time": start,
        "page_size": page_size
    }
    while True:
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code != 200:
                print(f"ERROR {resp.status_code}: {resp.text[:200]}")
                return None
            j = resp.json()
            all_data.extend(j.get('data', []))
            token = j.get('next_page_token')
            if not token:
                break
            params = {"assets": "btc", "metrics": metrics, "frequency": "1d", "page_size": page_size, "next_page_token": token}
            time.sleep(0.1)
        except Exception as e:
            print(f"Exception: {e}")
            return None
    return all_data

# Test each metric individually
metrics_to_test = {
    "CapMVRVCur": "MVRV Ratio",
    "PriceUSD": "BTC Price USD",
    "IssTotUSD": "Issuance Total USD (Puell)",
    "IssContNtv": "Issuance Cont Native (alt for Puell)",
    "TxTfrValAdjUSD": "Adjusted Transfer Volume USD (NVT)",
    "NVTAdj": "NVT Adjusted (direct)",
    "SoprFull": "SOPR Full",
    "CapRealUSD": "Realized Cap USD",
    "AdrActCnt": "Active Addresses",
    "HashRate": "Hash Rate",
    "DiffMean": "Difficulty Mean",
    "RevUSD": "Miner Revenue USD",  
    "FeeTotUSD": "Total Fees USD",
    "TxTfrCnt": "Transaction Count",
    "SplyAct1yr": "Supply Active 1yr",
    "NVTAdj90": "NVT Adjusted 90d MA",
}

results = {}
for metric, desc in metrics_to_test.items():
    data = fetch_coinmetrics(metric, start="2023-01-01", page_size=10)
    if data and len(data) > 0:
        # Check if metric has non-null values
        has_data = any(row.get(metric) is not None for row in data)
        results[metric] = {"available": has_data, "desc": desc, "sample_rows": len(data)}
        status = "✓ AVAILABLE" if has_data else "✗ NULL"
        print(f"{status}: {metric} - {desc}")
    else:
        results[metric] = {"available": False, "desc": desc}
        print(f"✗ FAIL: {metric} - {desc}")
    time.sleep(0.2)

print("\n=== AVAILABLE METRICS ===")
available = [k for k, v in results.items() if v.get("available")]
print(available)

with open("/tmp/available_metrics.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved to /tmp/available_metrics.json")
