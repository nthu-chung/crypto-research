#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const root = __dirname;
const charts = path.join(root, "charts");
fs.mkdirSync(charts, { recursive: true });

const inputFile = process.argv[2] || "results_volume_next_relaxed_IS2022_2024_OOS2025_202604.json";
const outputFile = process.argv[3] || inputFile.replace(/^results_/, "").replace(/\.json$/, "_static.html");
const fundedFile = process.argv[4] || null;

const base = JSON.parse(fs.readFileSync(path.join(root, inputFile), "utf8"));
const funded = fundedFile
  ? JSON.parse(fs.readFileSync(path.join(root, fundedFile), "utf8"))
  : null;

function cumulative(rows, key) {
  let value = 1;
  return rows.map((row) => {
    value *= 1 + Number(row[key] ?? row.return);
    return value;
  });
}

function drawdown(values) {
  let peak = values[0];
  return values.map((value) => {
    peak = Math.max(peak, value);
    return value / peak - 1;
  });
}

function points(values, width, height, pad, minY = null, maxY = null) {
  const min = minY ?? Math.min(...values);
  const max = maxY ?? Math.max(...values);
  const span = max - min || 1;
  return values.map((v, i) => {
    const x = pad.l + (i / Math.max(1, values.length - 1)) * (width - pad.l - pad.r);
    const y = pad.t + (1 - (v - min) / span) * (height - pad.t - pad.b);
    return [x, y];
  });
}

function pathLine(pts) {
  return pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
}

function axes(width, height, pad, title, yLabel = "") {
  return `
    <rect x="0" y="0" width="${width}" height="${height}" rx="8" fill="#111827" stroke="#30363d"/>
    <text x="${width / 2}" y="32" text-anchor="middle" fill="#f0f6fc" font-size="20" font-weight="700">${title}</text>
    <line x1="${pad.l}" y1="${height - pad.b}" x2="${width - pad.r}" y2="${height - pad.b}" stroke="#30363d"/>
    <line x1="${pad.l}" y1="${pad.t}" x2="${pad.l}" y2="${height - pad.b}" stroke="#30363d"/>
    <text x="18" y="${height / 2}" transform="rotate(-90 18 ${height / 2})" text-anchor="middle" fill="#8b949e" font-size="12">${yLabel}</text>`;
}

function equityChart(dates, equity, fundedEquity) {
  const width = 1280, height = 420, pad = { l: 70, r: 30, t: 56, b: 46 };
  const maxY = Math.max(...equity, ...fundedEquity) * 1.05;
  const minY = Math.min(...equity, ...fundedEquity, 1) * 0.95;
  const p1 = points(equity, width, height, pad, minY, maxY);
  const p2 = points(fundedEquity, width, height, pad, minY, maxY);
  const oosStart = base.config?.oos_start?.slice(0, 10) || "2025-01-31";
  const splitIndex = dates.findIndex((d) => d >= oosStart);
  const splitX = pad.l + (splitIndex / Math.max(1, dates.length - 1)) * (width - pad.l - pad.r);
  const fundedPath = funded ? `<path d="${pathLine(p2)}" fill="none" stroke="#f0883e" stroke-width="2"/>
    <text x="${pad.l + 70}" y="${pad.t + 18}" fill="#f0883e">Funding approx.</text>` : "";
  return `<svg viewBox="0 0 ${width} ${height}" class="chart-svg">
    ${axes(width, height, pad, "Equity Curve (Start = 1.0)", "Equity")}
    <rect x="${splitX}" y="${pad.t}" width="${width - pad.r - splitX}" height="${height - pad.t - pad.b}" fill="#7c2d12" opacity="0.22"/>
    <line x1="${splitX}" y1="${pad.t}" x2="${splitX}" y2="${height - pad.b}" stroke="#fbbf24" stroke-dasharray="6 6"/>
    <path d="${pathLine(p1)}" fill="none" stroke="#58a6ff" stroke-width="3"/>
    <text x="${pad.l + 8}" y="${pad.t + 18}" fill="#58a6ff">Base</text>
    ${fundedPath}
    <text x="${splitX + 10}" y="${pad.t + 18}" fill="#fbbf24">OOS starts ${oosStart}</text>
  </svg>`;
}

function monthlyChart(dates, returns) {
  const width = 620, height = 360, pad = { l: 60, r: 24, t: 56, b: 42 };
  const maxY = Math.max(...returns.map((r) => r * 100), 0) * 1.15;
  const minY = Math.min(...returns.map((r) => r * 100), 0) * 1.15;
  const span = maxY - minY || 1;
  const zeroY = pad.t + (1 - (0 - minY) / span) * (height - pad.t - pad.b);
  const barW = (width - pad.l - pad.r) / returns.length * 0.78;
  const bars = returns.map((r, i) => {
    const v = r * 100;
    const x = pad.l + (i / returns.length) * (width - pad.l - pad.r) + 2;
    const y = pad.t + (1 - (v - minY) / span) * (height - pad.t - pad.b);
    const h = Math.abs(zeroY - y);
    return `<rect x="${x.toFixed(1)}" y="${Math.min(y, zeroY).toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="${v >= 0 ? "#2ea043" : "#f85149"}"/>`;
  }).join("");
  return `<svg viewBox="0 0 ${width} ${height}" class="chart-svg">
    ${axes(width, height, pad, "Monthly Returns", "Return (%)")}
    <line x1="${pad.l}" y1="${zeroY}" x2="${width - pad.r}" y2="${zeroY}" stroke="#c9d1d9" opacity="0.6"/>
    ${bars}
  </svg>`;
}

function drawdownChart(dates, dd) {
  const width = 620, height = 360, pad = { l: 60, r: 24, t: 56, b: 42 };
  const values = dd.map((x) => x * 100);
  const pts = points(values, width, height, pad, Math.min(...values) * 1.1, 0);
  const area = `${pathLine(pts)} L${width - pad.r},${pad.t} L${pad.l},${pad.t} Z`;
  return `<svg viewBox="0 0 ${width} ${height}" class="chart-svg">
    ${axes(width, height, pad, "Drawdown", "DD (%)")}
    <path d="${area}" fill="rgba(248,81,73,0.28)"/>
    <path d="${pathLine(pts)}" fill="none" stroke="#ff7b72" stroke-width="2"/>
  </svg>`;
}

function metricsChart(pm) {
  const width = 1280, height = 360, pad = { l: 90, r: 30, t: 56, b: 56 };
  const groups = [
    { name: "IS", vals: [pm.is.cagr, pm.is.sharpe, pm.is.max_dd] },
    { name: "OOS", vals: [pm.oos.cagr, pm.oos.sharpe, pm.oos.max_dd] },
  ];
  const colors = ["#58a6ff", "#a371f7", "#f85149"];
  const labels = ["CAGR", "Sharpe", "MaxDD"];
  const all = groups.flatMap((g) => g.vals);
  const maxY = Math.max(...all, 0) * 1.15;
  const minY = Math.min(...all, 0) * 1.15;
  const span = maxY - minY || 1;
  const zeroY = pad.t + (1 - (0 - minY) / span) * (height - pad.t - pad.b);
  const groupW = (width - pad.l - pad.r) / groups.length;
  const barW = 62;
  const bars = groups.map((g, gi) => g.vals.map((v, vi) => {
    const x = pad.l + gi * groupW + groupW / 2 - 105 + vi * 75;
    const y = pad.t + (1 - (v - minY) / span) * (height - pad.t - pad.b);
    const h = Math.abs(zeroY - y);
    return `<rect x="${x}" y="${Math.min(y, zeroY)}" width="${barW}" height="${h}" fill="${colors[vi]}"/>
      <text x="${x + barW / 2}" y="${v >= 0 ? y - 7 : y + h + 18}" text-anchor="middle" fill="#c9d1d9" font-size="12">${v}</text>`;
  }).join("")).join("");
  const names = groups.map((g, gi) => `<text x="${pad.l + gi * groupW + groupW / 2}" y="${height - 20}" text-anchor="middle" fill="#f0f6fc" font-size="16">${g.name}</text>`).join("");
  const legend = labels.map((l, i) => `<rect x="${width - 250 + i * 80}" y="24" width="12" height="12" fill="${colors[i]}"/><text x="${width - 232 + i * 80}" y="35" fill="#c9d1d9" font-size="13">${l}</text>`).join("");
  return `<svg viewBox="0 0 ${width} ${height}" class="chart-svg">
    ${axes(width, height, pad, "IS/OOS Metrics")}
    <line x1="${pad.l}" y1="${zeroY}" x2="${width - pad.r}" y2="${zeroY}" stroke="#c9d1d9" opacity="0.6"/>
    ${bars}${names}${legend}
  </svg>`;
}

const dates = base.history.map((r) => r.date);
const returns = base.history.map((r) => Number(r.return));
const eq = cumulative(base.history, "return");
const feq = funded ? cumulative(funded.history, "return_with_funding") : eq;
const dd = drawdown(eq);
const oosEnd = base.config?.oos_end?.slice(0, 10) || "2026-04-30";
const partialNote = base.config?.include_partial ? " including partial final month" : "";

const html = `<!doctype html>
<html><head><meta charset="utf-8"/>
<title>AdaptiveTrend IS/OOS Static Charts</title>
<style>
body{margin:0;background:#0d1117;color:#f0f6fc;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.wrap{padding:24px;max-width:1320px;margin:0 auto}
h1{font-size:24px;margin:0 0 4px}.sub{color:#8b949e;margin:0 0 18px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.wide{grid-column:1/span 2}.chart-svg{width:100%;height:auto;display:block}
.note{margin-top:18px;color:#c9d1d9;line-height:1.5}
</style></head><body><div class="wrap">
<h1>AdaptiveTrend Walk-Forward: IS vs 2025+ OOS</h1>
<p class="sub">No external JS. Candidate: volume-next relaxed long-short. IS 2022-2024, OOS 2025-01 to ${oosEnd}${partialNote}.</p>
<div class="grid">
<div class="wide">${equityChart(dates, eq, feq)}</div>
<div>${monthlyChart(dates, returns)}</div>
<div>${drawdownChart(dates, dd)}</div>
<div class="wide">${metricsChart(base.period_metrics)}</div>
</div>
<p class="note">Key read: the strategy compounds strongly in IS, then loses money in the 2025+ OOS period. OOS CAGR = ${base.period_metrics.oos.cagr}%, Sharpe = ${base.period_metrics.oos.sharpe}, MaxDD = ${base.period_metrics.oos.max_dd}%.</p>
</div></body></html>`;

const out = path.join(charts, outputFile);
fs.writeFileSync(out, html);
console.log(out);
