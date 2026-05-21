#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const root = __dirname;
const charts = path.join(root, "charts");
fs.mkdirSync(charts, { recursive: true });

const base = JSON.parse(fs.readFileSync(path.join(root, "results_volume_next_relaxed_IS2022_2024_OOS2025_202604.json"), "utf8"));
const funded = JSON.parse(fs.readFileSync(path.join(root, "results_volume_next_relaxed_IS2022_2024_OOS2025_202604_funding_adjusted.json"), "utf8"));

function cumprod(rows, key) {
  let v = 1;
  return rows.map((r) => {
    v *= 1 + Number(r[key]);
    return v;
  });
}

function drawdown(eq) {
  let peak = -Infinity;
  return eq.map((v) => {
    peak = Math.max(peak, v);
    return v / peak - 1;
  });
}

const dates = base.history.map((r) => r.date);
const returns = base.history.map((r) => Number(r.return));
const equity = cumprod(base.history, "return");
const fundedEquity = cumprod(funded.history, "return_with_funding");
const dd = drawdown(equity);
const splitDate = "2025-01-01";
const monthlyBars = returns.map((r, i) => ({ x: dates[i], y: r * 100, color: r >= 0 ? "#2ea043" : "#f85149" }));

const html = `<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>AdaptiveTrend IS/OOS Chart</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    body { margin: 0; background: #0d1117; color: #f0f6fc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    .wrap { padding: 24px; max-width: 1500px; margin: 0 auto; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    p { color: #8b949e; margin: 0 0 18px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
    .chart { background: #111827; border: 1px solid #30363d; border-radius: 8px; min-height: 430px; }
    .wide { grid-column: 1 / span 2; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>AdaptiveTrend Clean-Room Reproduction: IS vs 2025+ OOS</h1>
    <p>Candidate: volume-next relaxed long-short. Split: IS 2022-2024, OOS 2025-01 to 2026-04.</p>
    <div class="grid">
      <div id="equity" class="chart wide"></div>
      <div id="monthly" class="chart"></div>
      <div id="drawdown" class="chart"></div>
      <div id="metrics" class="chart wide"></div>
    </div>
  </div>
  <script>
    const dates = ${JSON.stringify(dates)};
    const equity = ${JSON.stringify(equity)};
    const fundedEquity = ${JSON.stringify(fundedEquity)};
    const monthlyBars = ${JSON.stringify(monthlyBars)};
    const dd = ${JSON.stringify(dd.map((x) => x * 100))};
    const periodMetrics = ${JSON.stringify(base.period_metrics)};
    const splitDate = "${splitDate}";

    const commonLayout = {
      paper_bgcolor: "#111827",
      plot_bgcolor: "#111827",
      font: { color: "#c9d1d9" },
      margin: { l: 60, r: 24, t: 54, b: 46 },
      xaxis: { gridcolor: "rgba(201,209,217,0.12)", zerolinecolor: "#30363d" },
      yaxis: { gridcolor: "rgba(201,209,217,0.12)", zerolinecolor: "#30363d" },
      shapes: [{
        type: "line", x0: splitDate, x1: splitDate, y0: 0, y1: 1, yref: "paper",
        line: { color: "#fbbf24", dash: "dash", width: 2 }
      }]
    };

    Plotly.newPlot("equity", [
      { x: dates, y: equity, type: "scatter", mode: "lines", name: "Base", line: { color: "#58a6ff", width: 3 } },
      { x: dates, y: fundedEquity, type: "scatter", mode: "lines", name: "Funding approx.", line: { color: "#f0883e", width: 2 } }
    ], { ...commonLayout, title: "Equity Curve (Start = 1.0)", yaxis: { ...commonLayout.yaxis, title: "Equity multiple" } }, { responsive: true });

    Plotly.newPlot("monthly", [{
      x: monthlyBars.map(d => d.x), y: monthlyBars.map(d => d.y), type: "bar",
      marker: { color: monthlyBars.map(d => d.color) }, name: "Monthly return"
    }], { ...commonLayout, title: "Monthly Returns", yaxis: { ...commonLayout.yaxis, title: "Return (%)" } }, { responsive: true });

    Plotly.newPlot("drawdown", [{
      x: dates, y: dd, type: "scatter", mode: "lines", fill: "tozeroy",
      name: "Drawdown", line: { color: "#ff7b72", width: 2 }, fillcolor: "rgba(248,81,73,0.35)"
    }], { ...commonLayout, title: "Drawdown", yaxis: { ...commonLayout.yaxis, title: "Drawdown (%)" } }, { responsive: true });

    const labels = ["IS", "OOS"];
    Plotly.newPlot("metrics", [
      { x: labels, y: [periodMetrics.is.cagr, periodMetrics.oos.cagr], type: "bar", name: "CAGR", marker: { color: "#58a6ff" } },
      { x: labels, y: [periodMetrics.is.sharpe, periodMetrics.oos.sharpe], type: "bar", name: "Sharpe", marker: { color: "#a371f7" } },
      { x: labels, y: [periodMetrics.is.max_dd, periodMetrics.oos.max_dd], type: "bar", name: "MaxDD", marker: { color: "#f85149" } }
    ], { ...commonLayout, title: "IS/OOS Metrics", shapes: [] }, { responsive: true });
  </script>
</body>
</html>`;

const out = path.join(charts, "volume_next_IS2022_2024_OOS2025_202604.html");
fs.writeFileSync(out, html);
console.log(out);
