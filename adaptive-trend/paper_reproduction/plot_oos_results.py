#!/usr/bin/env python3
"""Plot IS/OOS results for the AdaptiveTrend reproduction."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
CHARTS = ROOT / "charts"
CHARTS.mkdir(exist_ok=True)


def drawdown(series: pd.Series) -> pd.Series:
    peak = series.cummax()
    return series / peak - 1


def main() -> None:
    source = ROOT / "results_volume_next_relaxed_IS2022_2024_OOS2025_202604.json"
    funded = ROOT / "results_volume_next_relaxed_IS2022_2024_OOS2025_202604_funding_adjusted.json"
    data = json.loads(source.read_text())
    funded_data = json.loads(funded.read_text())

    df = pd.DataFrame(data["history"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["equity"] = (1 + df["return"]).cumprod()
    df["drawdown"] = drawdown(df["equity"])
    df["period"] = np.where(df.index < pd.Timestamp("2025-01-01"), "IS", "OOS")

    fdf = pd.DataFrame(funded_data["history"])
    fdf["date"] = pd.to_datetime(fdf["date"])
    fdf = fdf.set_index("date")
    fdf["equity"] = (1 + fdf["return_with_funding"]).cumprod()

    plt.style.use("dark_background")
    fig, axes = plt.subplots(2, 2, figsize=(16, 10), facecolor="#0d1117")
    fig.suptitle("AdaptiveTrend Clean-Room Reproduction: IS vs 2025+ OOS", fontsize=16, fontweight="bold")

    ax = axes[0, 0]
    ax.set_facecolor("#111827")
    ax.plot(df.index, df["equity"], color="#58a6ff", linewidth=2.2, label="Base")
    ax.plot(fdf.index, fdf["equity"], color="#f0883e", linewidth=1.6, label="Funding approx.", alpha=0.9)
    ax.axvspan(pd.Timestamp("2025-01-01"), df.index.max(), color="#7c2d12", alpha=0.25, label="OOS")
    ax.axvline(pd.Timestamp("2025-01-01"), color="#fbbf24", linestyle="--", linewidth=1.4)
    ax.set_title("Equity Curve (Start = 1.0)")
    ax.set_ylabel("Equity multiple")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.18)

    ax = axes[0, 1]
    ax.set_facecolor("#111827")
    colors = np.where(df["return"] >= 0, "#2ea043", "#f85149")
    ax.bar(df.index, df["return"] * 100, color=colors, width=20)
    ax.axvline(pd.Timestamp("2025-01-01"), color="#fbbf24", linestyle="--", linewidth=1.4)
    ax.axhline(0, color="#c9d1d9", linewidth=0.8)
    ax.set_title("Monthly Returns")
    ax.set_ylabel("Return (%)")
    ax.grid(True, axis="y", alpha=0.18)

    ax = axes[1, 0]
    ax.set_facecolor("#111827")
    ax.fill_between(df.index, df["drawdown"] * 100, 0, color="#f85149", alpha=0.45)
    ax.plot(df.index, df["drawdown"] * 100, color="#ff7b72", linewidth=1.2)
    ax.axvline(pd.Timestamp("2025-01-01"), color="#fbbf24", linestyle="--", linewidth=1.4)
    ax.set_title("Drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.grid(True, alpha=0.18)

    ax = axes[1, 1]
    ax.set_facecolor("#111827")
    summary = pd.DataFrame(data["period_metrics"]).T
    x = np.arange(len(summary.index))
    width = 0.28
    ax.bar(x - width, summary["cagr"], width, label="CAGR", color="#58a6ff")
    ax.bar(x, summary["sharpe"], width, label="Sharpe", color="#a371f7")
    ax.bar(x + width, summary["max_dd"], width, label="MaxDD", color="#f85149")
    ax.axhline(0, color="#c9d1d9", linewidth=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels([label.upper() for label in summary.index])
    ax.set_title("IS/OOS Metrics")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.18)

    for ax in axes.flat:
        for spine in ax.spines.values():
            spine.set_color("#30363d")
        ax.tick_params(colors="#c9d1d9")
        title = ax.title
        title.set_color("#f0f6fc")

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    output = CHARTS / "volume_next_IS2022_2024_OOS2025_202604.png"
    fig.savefig(output, dpi=150, facecolor="#0d1117", bbox_inches="tight")
    print(output)


if __name__ == "__main__":
    main()
