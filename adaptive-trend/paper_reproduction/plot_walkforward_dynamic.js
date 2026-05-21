#!/usr/bin/env node
const fs = require("fs");
const path = require("path");

const root = __dirname;
const charts = path.join(root, "charts");
fs.mkdirSync(charts, { recursive: true });

const inputFile = process.argv[2] || "results_volume_next_relaxed_walkforward_to_20260521_partial.json";
const outputFile = process.argv[3] || inputFile.replace(/^results_/, "").replace(/\.json$/, "_dynamic.html");
const data = JSON.parse(fs.readFileSync(path.join(root, inputFile), "utf8"));

const rows = data.history.map((row, index) => {
  const equity = Number(row.capital) / 10000;
  return {
    index,
    date: row.date,
    infoMonth: row.info_month,
    ret: Number(row.return),
    retPct: Number(row.return) * 100,
    capital: Number(row.capital),
    equity,
    longs: row.longs || [],
    shorts: row.shorts || [],
    longTrades: row.long_trades || 0,
    shortTrades: row.short_trades || 0,
  };
});

let peak = 1;
for (const row of rows) {
  peak = Math.max(peak, row.equity);
  row.drawdown = row.equity / peak - 1;
  row.drawdownPct = row.drawdown * 100;
}

const config = data.config || {};
const oosStart = (config.oos_start || "2025-01-31").slice(0, 10);
const isMetrics = data.period_metrics?.is || {};
const oosMetrics = data.period_metrics?.oos || {};
const fullMetrics = data.metrics || {};

function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

const payload = {
  rows,
  oosStart,
  config: {
    tradeStart: config.trade_start,
    tradeEnd: config.trade_end,
    includePartial: Boolean(config.include_partial),
    shortPoolMode: config.short_pool_mode,
    maxPositions: config.max_positions,
    longSr: config.long_sr,
    shortSr: config.short_sr,
    feeBps: config.fee_bps,
  },
  metrics: {
    full: fullMetrics,
    is: isMetrics,
    oos: oosMetrics,
  },
};

const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>AdaptiveTrend Walk-Forward Dynamic</title>
<style>
:root {
  color-scheme: dark;
  --bg: #0d1117;
  --panel: #111827;
  --panel-2: #0f172a;
  --line: #30363d;
  --text: #f0f6fc;
  --muted: #9aa4b2;
  --blue: #58a6ff;
  --green: #2ea043;
  --red: #f85149;
  --orange: #f0883e;
  --yellow: #fbbf24;
  --violet: #a371f7;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
.wrap {
  width: min(1360px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 22px 0 28px;
}
header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 16px;
}
h1 {
  font-size: 24px;
  line-height: 1.15;
  margin: 0 0 4px;
}
.sub {
  color: var(--muted);
  margin: 0;
  font-size: 14px;
}
.pill-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
}
.pill {
  border: 1px solid var(--line);
  border-radius: 999px;
  padding: 6px 10px;
  background: #0f172a;
  color: #c9d1d9;
  font-size: 12px;
  white-space: nowrap;
}
.layout {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(330px, 0.8fr);
  gap: 16px;
  align-items: start;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px 0;
}
.panel-title {
  font-size: 15px;
  font-weight: 700;
}
.panel-note {
  color: var(--muted);
  font-size: 12px;
}
svg {
  display: block;
  width: 100%;
  height: auto;
}
.controls {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
  padding: 12px 14px 14px;
  border-top: 1px solid var(--line);
}
button {
  width: 42px;
  height: 34px;
  border: 1px solid #3b4758;
  border-radius: 7px;
  background: #182235;
  color: var(--text);
  font-size: 16px;
  cursor: pointer;
}
button:hover { border-color: var(--blue); }
input[type="range"] {
  width: 100%;
  accent-color: var(--blue);
}
.speed {
  display: flex;
  gap: 6px;
}
.speed button {
  width: auto;
  min-width: 42px;
  padding: 0 10px;
  font-size: 12px;
}
.speed button.active {
  background: #1f6feb;
  border-color: #58a6ff;
}
.side {
  display: grid;
  gap: 16px;
}
.stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  padding: 14px;
}
.stat {
  min-height: 78px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-2);
  padding: 10px;
}
.stat-label {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}
.stat-value {
  font-size: 20px;
  line-height: 1.1;
  font-weight: 750;
  letter-spacing: 0;
}
.green { color: #3fb950; }
.red { color: #ff7b72; }
.blue { color: var(--blue); }
.orange { color: var(--orange); }
.lists {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
  padding: 0 14px 14px;
}
.list-box {
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel-2);
  padding: 10px;
  min-height: 150px;
}
.list-title {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 8px;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  border: 1px solid #344154;
  border-radius: 6px;
  padding: 4px 6px;
  color: #d1d9e6;
  font-size: 11px;
  background: #121c2e;
}
.metrics-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.metrics-table th,
.metrics-table td {
  border-top: 1px solid var(--line);
  padding: 9px 10px;
  text-align: right;
}
.metrics-table th:first-child,
.metrics-table td:first-child { text-align: left; }
.metrics-table thead th {
  color: var(--muted);
  font-weight: 600;
}
.explain {
  margin-top: 16px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: #0f172a;
  padding: 14px 16px;
  color: #c9d1d9;
  line-height: 1.55;
  font-size: 14px;
}
@media (max-width: 960px) {
  header { align-items: start; flex-direction: column; }
  .pill-row { justify-content: flex-start; }
  .layout { grid-template-columns: 1fr; }
}
@media (max-width: 620px) {
  .controls { grid-template-columns: auto 1fr; }
  .speed { grid-column: 1 / span 2; }
  .stats, .lists { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>AdaptiveTrend Walk-Forward Dynamic</h1>
      <p class="sub">逐月播放：每個月用上一個資訊月份調整，下一段才交易。OOS 從 ${esc(oosStart)} 開始。</p>
    </div>
    <div class="pill-row">
      <span class="pill">short pool: ${esc(payload.config.shortPoolMode)}</span>
      <span class="pill">max positions: ${esc(payload.config.maxPositions)}</span>
      <span class="pill">fee: ${esc(payload.config.feeBps)} bps</span>
      <span class="pill">${payload.config.includePartial ? "partial final month" : "complete months"}</span>
    </div>
  </header>

  <div class="layout">
    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">Equity / Monthly Return / Drawdown</div>
        <div class="panel-note" id="phaseLabel">IS</div>
      </div>
      <svg id="mainChart" viewBox="0 0 1000 590" aria-label="dynamic walk-forward chart"></svg>
      <div class="controls">
        <button id="play" aria-label="play or pause">▶</button>
        <input id="monthSlider" type="range" min="0" max="${rows.length - 1}" value="${rows.length - 1}" step="1" aria-label="month"/>
        <div class="speed">
          <button data-speed="900">慢</button>
          <button data-speed="550" class="active">中</button>
          <button data-speed="260">快</button>
        </div>
      </div>
    </section>

    <aside class="side">
      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">Current Month</div>
          <div class="panel-note" id="monthCount"></div>
        </div>
        <div class="stats">
          <div class="stat"><div class="stat-label">Trade month end</div><div class="stat-value" id="dateValue"></div></div>
          <div class="stat"><div class="stat-label">Info month used</div><div class="stat-value blue" id="infoValue"></div></div>
          <div class="stat"><div class="stat-label">Monthly return</div><div class="stat-value" id="returnValue"></div></div>
          <div class="stat"><div class="stat-label">Capital</div><div class="stat-value" id="capitalValue"></div></div>
          <div class="stat"><div class="stat-label">Drawdown</div><div class="stat-value red" id="drawdownValue"></div></div>
          <div class="stat"><div class="stat-label">Trades</div><div class="stat-value orange" id="tradesValue"></div></div>
        </div>
        <div class="lists">
          <div class="list-box"><div class="list-title">Longs</div><div class="chips" id="longsList"></div></div>
          <div class="list-box"><div class="list-title">Shorts</div><div class="chips" id="shortsList"></div></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">Period Metrics</div>
          <div class="panel-note">IS vs OOS</div>
        </div>
        <table class="metrics-table">
          <thead><tr><th>Period</th><th>CAGR</th><th>Sharpe</th><th>MaxDD</th><th>Total</th></tr></thead>
          <tbody>
            <tr><td>IS</td><td>${esc(isMetrics.cagr)}%</td><td>${esc(isMetrics.sharpe)}</td><td>${esc(isMetrics.max_dd)}%</td><td>${esc(isMetrics.total_return)}%</td></tr>
            <tr><td>OOS</td><td>${esc(oosMetrics.cagr)}%</td><td>${esc(oosMetrics.sharpe)}</td><td>${esc(oosMetrics.max_dd)}%</td><td>${esc(oosMetrics.total_return)}%</td></tr>
            <tr><td>Full</td><td>${esc(fullMetrics.cagr)}%</td><td>${esc(fullMetrics.sharpe)}</td><td>${esc(fullMetrics.max_dd)}%</td><td>${esc(fullMetrics.total_return)}%</td></tr>
          </tbody>
        </table>
      </section>
    </aside>
  </div>

  <div class="explain">
    讀法：藍線是資金曲線，綠/紅柱是每月報酬，下方紅線是回撤；黃色直線之後是 2025+ OOS。播放時可以看到策略在 IS 期間往上走得很順，但進入 OOS 後回撤變深，代表「每月重新調參」沒有保證下個月延續有效。
  </div>
</div>

<script>
const payload = ${JSON.stringify(payload)};
const rows = payload.rows;
const svg = document.getElementById("mainChart");
const slider = document.getElementById("monthSlider");
const playButton = document.getElementById("play");
const phaseLabel = document.getElementById("phaseLabel");
let current = rows.length - 1;
let timer = null;
let speedMs = 550;

const fmtPct = (x) => (x >= 0 ? "+" : "") + x.toFixed(2) + "%";
const fmtMoney = (x) => "$" + x.toLocaleString(undefined, { maximumFractionDigits: 0 });
const cls = (x) => x >= 0 ? "green" : "red";

function scaleX(i, left, width) {
  return left + (i / Math.max(1, rows.length - 1)) * width;
}
function scaleY(v, min, max, top, height) {
  return top + (1 - (v - min) / (max - min || 1)) * height;
}
function linePath(points) {
  return points.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
}
function chipHtml(items) {
  if (!items.length) return '<span class="chip">none</span>';
  return items.map((item) => '<span class="chip">' + item + '</span>').join("");
}
function draw(index) {
  const visible = rows.slice(0, index + 1);
  const w = 1000;
  const h = 590;
  const pad = { l: 66, r: 28 };
  const eqTop = 48, eqH = 245;
  const retTop = 338, retH = 95;
  const ddTop = 468, ddH = 72;
  const plotW = w - pad.l - pad.r;
  const eqMin = Math.min(0.9, ...rows.map((r) => r.equity)) * 0.96;
  const eqMax = Math.max(...rows.map((r) => r.equity)) * 1.04;
  const retMin = Math.min(...rows.map((r) => r.retPct), 0) * 1.15;
  const retMax = Math.max(...rows.map((r) => r.retPct), 0) * 1.15;
  const ddMin = Math.min(...rows.map((r) => r.drawdownPct)) * 1.12;
  const oosIndex = rows.findIndex((r) => r.date >= payload.oosStart);
  const oosX = scaleX(oosIndex, pad.l, plotW);

  const eqPoints = visible.map((r) => [scaleX(r.index, pad.l, plotW), scaleY(r.equity, eqMin, eqMax, eqTop, eqH)]);
  const ddPoints = visible.map((r) => [scaleX(r.index, pad.l, plotW), scaleY(r.drawdownPct, ddMin, 0, ddTop, ddH)]);
  const retZero = scaleY(0, retMin, retMax, retTop, retH);
  const barW = Math.max(3, plotW / rows.length * 0.7);
  const bars = visible.map((r) => {
    const x = scaleX(r.index, pad.l, plotW) - barW / 2;
    const y = scaleY(r.retPct, retMin, retMax, retTop, retH);
    const bh = Math.abs(retZero - y);
    return '<rect x="' + x.toFixed(1) + '" y="' + Math.min(y, retZero).toFixed(1) + '" width="' + barW.toFixed(1) + '" height="' + bh.toFixed(1) + '" fill="' + (r.retPct >= 0 ? '#2ea043' : '#f85149') + '"/>';
  }).join("");
  const last = rows[index];
  const lastX = scaleX(last.index, pad.l, plotW);
  const lastY = scaleY(last.equity, eqMin, eqMax, eqTop, eqH);
  const monthTicks = rows
    .filter((r) => r.date.endsWith("-12-31") || r.index === 0 || r.index === rows.length - 1)
    .map((r) => '<text x="' + scaleX(r.index, pad.l, plotW).toFixed(1) + '" y="570" text-anchor="middle" fill="#9aa4b2" font-size="12">' + r.date.slice(0, 4) + '</text>')
    .join("");

  svg.innerHTML =
    '<rect x="0" y="0" width="' + w + '" height="' + h + '" fill="#111827"/>' +
    '<rect x="' + oosX.toFixed(1) + '" y="34" width="' + (w - pad.r - oosX).toFixed(1) + '" height="510" fill="#7c2d12" opacity="0.18"/>' +
    '<line x1="' + oosX.toFixed(1) + '" y1="34" x2="' + oosX.toFixed(1) + '" y2="544" stroke="#fbbf24" stroke-dasharray="6 6"/>' +
    '<text x="' + (oosX + 8).toFixed(1) + '" y="52" fill="#fbbf24" font-size="12">OOS starts</text>' +
    '<line x1="' + pad.l + '" y1="' + (eqTop + eqH) + '" x2="' + (w - pad.r) + '" y2="' + (eqTop + eqH) + '" stroke="#30363d"/>' +
    '<line x1="' + pad.l + '" y1="' + (retTop + retH) + '" x2="' + (w - pad.r) + '" y2="' + (retTop + retH) + '" stroke="#30363d"/>' +
    '<line x1="' + pad.l + '" y1="' + (ddTop + ddH) + '" x2="' + (w - pad.r) + '" y2="' + (ddTop + ddH) + '" stroke="#30363d"/>' +
    '<text x="16" y="176" transform="rotate(-90 16 176)" fill="#9aa4b2" text-anchor="middle" font-size="12">Equity</text>' +
    '<text x="16" y="386" transform="rotate(-90 16 386)" fill="#9aa4b2" text-anchor="middle" font-size="12">Return</text>' +
    '<text x="16" y="506" transform="rotate(-90 16 506)" fill="#9aa4b2" text-anchor="middle" font-size="12">DD</text>' +
    '<path d="' + linePath(eqPoints) + '" fill="none" stroke="#58a6ff" stroke-width="3"/>' +
    '<circle cx="' + lastX.toFixed(1) + '" cy="' + lastY.toFixed(1) + '" r="5" fill="#58a6ff" stroke="#f0f6fc" stroke-width="2"/>' +
    '<text x="' + Math.min(lastX + 10, 890).toFixed(1) + '" y="' + Math.max(lastY - 10, 20).toFixed(1) + '" fill="#c9d1d9" font-size="12">' + last.date + ' / ' + last.equity.toFixed(2) + 'x</text>' +
    '<line x1="' + pad.l + '" y1="' + retZero.toFixed(1) + '" x2="' + (w - pad.r) + '" y2="' + retZero.toFixed(1) + '" stroke="#c9d1d9" opacity="0.55"/>' +
    bars +
    '<path d="' + linePath(ddPoints) + '" fill="none" stroke="#ff7b72" stroke-width="2"/>' +
    monthTicks;

  document.getElementById("dateValue").textContent = last.date;
  document.getElementById("infoValue").textContent = last.infoMonth;
  const returnValue = document.getElementById("returnValue");
  returnValue.textContent = fmtPct(last.retPct);
  returnValue.className = "stat-value " + cls(last.retPct);
  document.getElementById("capitalValue").textContent = fmtMoney(last.capital);
  document.getElementById("drawdownValue").textContent = last.drawdownPct.toFixed(2) + "%";
  document.getElementById("tradesValue").textContent = (last.longTrades + last.shortTrades).toString();
  document.getElementById("longsList").innerHTML = chipHtml(last.longs);
  document.getElementById("shortsList").innerHTML = chipHtml(last.shorts);
  document.getElementById("monthCount").textContent = (index + 1) + " / " + rows.length;
  phaseLabel.textContent = last.date >= payload.oosStart ? "OOS" : "IS";
  phaseLabel.style.color = last.date >= payload.oosStart ? "#fbbf24" : "#58a6ff";
}

function setIndex(next) {
  current = Math.max(0, Math.min(rows.length - 1, Number(next)));
  slider.value = current;
  draw(current);
}
function stop() {
  clearInterval(timer);
  timer = null;
  playButton.textContent = "▶";
}
function play() {
  if (timer) {
    stop();
    return;
  }
  if (current >= rows.length - 1) setIndex(0);
  playButton.textContent = "Ⅱ";
  timer = setInterval(() => {
    if (current >= rows.length - 1) {
      stop();
      return;
    }
    setIndex(current + 1);
  }, speedMs);
}

slider.addEventListener("input", (event) => {
  stop();
  setIndex(event.target.value);
});
playButton.addEventListener("click", play);
document.querySelectorAll("[data-speed]").forEach((button) => {
  button.addEventListener("click", () => {
    speedMs = Number(button.dataset.speed);
    document.querySelectorAll("[data-speed]").forEach((b) => b.classList.remove("active"));
    button.classList.add("active");
    if (timer) {
      stop();
      play();
    }
  });
});
setIndex(current);
</script>
</body>
</html>`;

const out = path.join(charts, outputFile);
fs.writeFileSync(out, html);
console.log(out);
