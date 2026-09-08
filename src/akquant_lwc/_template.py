"""HTML/CSS/JS template for the full akquant-lwc report page.

The template is a single self-contained HTML document. Placeholders are
substituted by :func:`akquant_lwc.report.render_html`:

- ``__TITLE__``: HTML-escaped report title (appears twice: <title> and <h1>).
- ``__LWC_JS__``: the vendored Lightweight Charts standalone bundle.
- ``__APP_JSON__``: JSON application payload (see ``report.build_app_data``).

Chart rendering uses two engines: Lightweight Charts for all time-series
charts (equity, drawdown, rolling metrics, benchmark, risk trends, indicator
panes, K-line review) and a small built-in canvas renderer for categorical
charts (yearly bars, histograms, scatter) which have no time x-axis.
"""

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>__TITLE__</title>
<style>
:root {
  --tooltip-bg: rgba(255, 255, 255, 0.97);
  --up: #ef5350;
  --down: #26a69a;
  --accent: #2962ff;
  --bg: #f5f6fa;
  --card: #ffffff;
  --text: #1f2937;
  --border: #e5e7eb;
  --muted: #6b7280;
  --panel: #fafafa;
  --grid-line: #f3f4f6;
}
html[data-theme="dark"] {
  --tooltip-bg: rgba(22, 29, 46, 0.97);
  --bg: #0f1420;
  --card: #161d2e;
  --text: #e5e7eb;
  --border: #2a3446;
  --muted: #9ca3af;
  --panel: #1b2436;
  --grid-line: #232c3f;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px 16px 48px;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", "PingFang SC",
    "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  transition: background 0.2s, color 0.2s;
}
.page { max-width: 1240px; margin: 0 auto; }
header { position: relative; }
header h1 { font-size: 22px; margin: 0 0 4px; }
.theme-toggle {
  position: absolute;
  top: 0;
  right: 0;
  padding: 6px 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--card);
  color: var(--text);
  font-size: 13px;
  cursor: pointer;
}
.theme-toggle:hover { background: var(--panel); }
header .sub { color: var(--muted); font-size: 12px; margin-bottom: 16px; }
footer {
  text-align: center;
  color: var(--muted);
  font-size: 12px;
  margin-top: 24px;
}
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 16px 18px;
  margin-bottom: 18px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
}
.card h2 { font-size: 16px; margin: 0 0 12px; }
.card h3 { font-size: 13px; margin: 14px 0 8px; color: var(--muted); }
.summary-box {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.summary-item {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  background: var(--panel);
}
.summary-item .label { font-size: 12px; color: var(--muted); }
.summary-item .value { font-size: 15px; font-weight: 600; margin-top: 2px; }
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 10px;
}
.metric {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--panel);
}
.metric .label { font-size: 12px; color: var(--muted); }
.metric .value { font-size: 16px; font-weight: 600; margin-top: 2px; }
.pos { color: var(--up); }
.neg { color: var(--down); }
.warn { color: var(--up); }
.grid-2col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 16px;
}
.grid-2col > div {
  min-width: 0;
}
/* 宽表格自身横向滚动；图表容器不截断 tooltip */
#tbl-orders, #tbl-executions {
  overflow-x: auto;
}
.chart { width: 100%; position: relative; }
.chart-lg { height: 460px; }
.chart-md { height: 300px; }
.chart-sm { height: 220px; }
.chart-xs { height: 180px; }
.chart-canvas { width: 100%; display: block; }
.controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.controls input {
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 14px;
  width: 220px;
}
.controls button, #data-file-btn {
  padding: 6px 16px;
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}
.controls button:hover, #data-file-btn:hover { background: #1e4fd8; }
.controls .status { font-size: 12px; color: var(--muted); }
.controls .status.error { color: var(--up); }
.tooltip {
  position: absolute;
  z-index: 20;
  display: none;
  max-width: 340px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--tooltip-bg);
  box-shadow: 0 2px 8px rgba(16, 24, 40, 0.12);
  font-size: 12px;
  line-height: 1.6;
  pointer-events: none;
}
table.trades, table.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin-top: 12px;
}
table.trades th, table.trades td,
table.data-table th, table.data-table td {
  border-bottom: 1px solid var(--border);
  padding: 5px 6px;
  text-align: right;
  white-space: nowrap;
}
table.trades th:first-child, table.trades td:first-child,
table.trades th:nth-child(2), table.trades td:nth-child(2),
table.data-table th:first-child, table.data-table td:first-child {
  text-align: left;
}
table.trades tbody tr { cursor: pointer; }
table.trades tbody tr:hover { background: var(--panel); }
table.heatmap td, table.heatmap th {
  text-align: center !important;
  min-width: 62px;
}
.hint { color: var(--muted); font-size: 12px; }
.empty-panel {
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 14px;
  color: var(--muted);
  font-size: 12px;
  background: var(--panel);
}
details.details-block {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 12px;
  background: var(--card);
}
details.details-block summary {
  cursor: pointer;
  font-size: 13px;
  color: #374151;
  font-weight: 600;
}
.legend { margin: 6px 0; font-size: 12px; color: var(--muted); }
.legend-item { margin-right: 12px; white-space: nowrap; }
.legend-swatch {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 4px;
}
.hbars { margin: 6px 0; }
.hbar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px 0;
  font-size: 12px;
}
.hbar-label {
  flex: 0 0 180px;
  text-align: right;
  color: #374151;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.hbar-track {
  flex: 1;
  display: flex;
  height: 14px;
  background: var(--grid-line);
  border-radius: 3px;
  overflow: hidden;
}
.hbar-fill { background: var(--accent); height: 100%; }
.hbar-seg { height: 100%; }
.hbar-value { flex: 0 0 auto; color: var(--muted); }
.position-list { display: flex; flex-wrap: wrap; gap: 6px; min-width: 320px; }
.position-chip {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 2px 7px; border: 1px solid var(--border);
  border-radius: 999px; background: var(--panel); font-size: 12px;
}
.position-chip span { color: var(--muted); }
.position-chip.long span { color: var(--up); }
.position-chip.short span { color: var(--down); }
.position-chip.long span:first-of-type { color: var(--up); }
.position-chip.short span:first-of-type { color: var(--down); }
.position-chip.long, .position-chip.short { border-color: currentColor; }
</style>
<script>__LWC_JS__</script>
</head>
<body>
<div class="page">
<header>
  <h1>__TITLE__</h1>
  <button id="theme-toggle" class="theme-toggle" type="button">🌙 暗色</button>
  <div class="sub">生成时间: <span id="generated-at"></span>
    &nbsp;·&nbsp; AKQuant &times; TradingView Lightweight Charts
    (akquant-lwc)</div>
</header>

<section class="card">
  <div class="summary-box" id="summary-box"></div>
</section>

<section class="card" id="metrics-card">
  <h2>核心指标 (Key Metrics)</h2>
  <div class="metrics-grid" id="metrics"></div>
</section>

<section class="card" id="daily-positions-card">
  <h2>每日持仓总览 (Daily Holdings)</h2>
  <div id="daily-positions"></div>
</section>

<section class="card">
  <h2>权益与回撤 (Equity &amp; Drawdown)</h2>
  <div id="equity-chart" class="chart chart-md"></div>
  <h3>最大回撤 (Drawdown)</h3>
  <div id="drawdown-chart" class="chart chart-sm"></div>
  <h3>月度收益 (Monthly Returns)</h3>
  <div id="monthly-heatmap"></div>
</section>

<section class="card" id="indicator-card" style="display:none">
  <h2>自定义指标 (Custom Indicators)</h2>
  <div id="indicator-filter" class="hint" style="margin-bottom:8px"></div>
  <div id="indicator-cards"></div>
  <div id="indicator-panes"></div>
  <details class="details-block">
    <summary>指标定义明细 (Indicator Definitions)</summary>
    <div id="indicator-defs"></div>
  </details>
</section>

<section class="card">
  <h2>收益分析 (Return Analysis)</h2>
  <div class="grid-2col">
    <div>
      <h3>年度收益 (Yearly Returns)</h3>
      <div id="yearly-chart"></div>
    </div>
    <div>
      <h3>日收益率分布 (Daily Returns Distribution)</h3>
      <div id="retdist-chart"></div>
    </div>
  </div>
  <h3>滚动夏普 (Rolling Sharpe, window=126)</h3>
  <div id="roll-sharpe-chart" class="chart chart-xs"></div>
  <h3>滚动波动率 (Rolling Volatility, window=126)</h3>
  <div id="roll-vol-chart" class="chart chart-xs"></div>
</section>

<section class="card" id="benchmark-card">
  <h2>基准对比 (Benchmark Comparison)</h2>
  <div id="benchmark-empty" class="empty-panel" style="display:none"></div>
  <div class="metrics-grid" id="benchmark-metrics"></div>
  <div id="benchmark-chart" class="chart chart-md"></div>
</section>

<section class="card">
  <h2>交易分析 (Trade Analysis)</h2>
  <div class="grid-2col">
    <div>
      <h3>交易盈亏分布 (Trade PnL Distribution)</h3>
      <div id="pnldist-chart"></div>
    </div>
    <div>
      <h3>盈亏 vs 持仓时间 (PnL vs Duration)</h3>
      <div id="pnldur-chart"></div>
    </div>
  </div>
</section>

<section class="card">
  <h2>交易复盘（K线买卖点）</h2>
  <div id="data-loader" class="empty-panel" style="display:none">
    复盘行情数据存放在外置文件 <b id="data-file-name"></b>
    （与本报告同目录）中。浏览器安全限制需要手动授权一次：点击下方按钮
    选择该文件，之后即可在页面内热切换全部标的，无需再次授权。
    <div style="margin-top:10px">
      <button id="data-file-btn" type="button">打开数据文件</button>
      <span class="hint" id="data-file-status"></span>
    </div>
    <input type="file" id="data-file-input"
           accept=".json,application/json" style="display:none"/>
  </div>
  <div class="controls">
    <input id="symbol-input" list="symbol-list"
           placeholder="输入股票代码后回车，如 600519.SH"/>
    <datalist id="symbol-list"></datalist>
    <button id="symbol-go" type="button">复盘</button>
    <span class="status" id="symbol-status"></span>
  </div>
  <div id="kline-chart" class="chart chart-lg">
    <div class="tooltip" id="trade-tooltip"></div>
  </div>
  <div class="hint">
    提示：点击交易明细行可定位到对应区间；K 线上悬停买卖点可查看交易详情。
  </div>
  <table class="trades" id="trades-table" style="display:none">
    <thead>
      <tr>
        <th>方向</th><th>开/平</th><th>开仓时间</th><th>开仓价</th>
        <th>平仓时间</th><th>平仓价</th><th>数量</th>
        <th>收益率</th><th>净利润</th>
      </tr>
    </thead>
    <tbody id="trades-body"></tbody>
  </table>
</section>

<section class="card">
  <h2>组合归因与容量分析 (Attribution &amp; Capacity)</h2>
  <div id="analysis-overview"></div>
  <details class="details-block">
    <summary>暴露摘要明细 (Exposure Summary)</summary>
    <div id="tbl-exposure"></div>
  </details>
  <details class="details-block">
    <summary>容量摘要明细 (Capacity Summary)</summary>
    <div id="tbl-capacity"></div>
  </details>
  <details class="details-block" open>
    <summary>归因明细 (Attribution by Symbol)</summary>
    <div id="tbl-attribution"></div>
  </details>
</section>

<section class="card">
  <h2>策略归属聚合 (Strategy Ownership)</h2>
  <div class="grid-2col">
    <div>
      <h3>策略订单聚合 (Orders by Strategy)</h3>
      <div id="tbl-orders"></div>
    </div>
    <div>
      <h3>策略成交聚合 (Executions by Strategy)</h3>
      <div id="tbl-executions"></div>
    </div>
  </div>
  <details class="details-block">
    <summary>策略风控拒单明细 (Risk Rejections by Strategy)</summary>
    <div id="tbl-risk"></div>
  </details>
  <details class="details-block">
    <summary>强平审计明细 (Liquidation Audit)</summary>
    <div id="tbl-liquidation"></div>
  </details>
</section>

<section class="card" id="risk-card">
  <h2>风控拒单与强平分析 (Risk &amp; Liquidation)</h2>
  <div id="risk-empty" class="empty-panel" style="display:none"></div>
  <div id="risk-ratio-block" style="display:none">
    <h3>策略级风控拒单占比 (Risk Reject Ratio by Strategy)</h3>
    <div id="risk-ratio"></div>
  </div>
  <div id="risk-stack-block" style="display:none">
    <h3>策略级拒单原因占比 (Risk Reason Ratio by Strategy)</h3>
    <div id="risk-reason-stack"></div>
  </div>
  <div id="risk-trend-block" style="display:none">
    <h3>按日风控拒单趋势 (Daily Risk Reject Trend)</h3>
    <div id="risk-trend-chart" class="chart chart-xs"></div>
  </div>
  <div id="risk-reason-trend-block" style="display:none">
    <h3>按日拒单原因趋势 (Daily Reject Reason Trend)</h3>
    <div id="risk-reason-legend" class="legend"></div>
    <div id="risk-reason-trend-chart" class="chart chart-xs"></div>
  </div>
  <div id="risk-strategy-block" style="display:none">
    <h3>按策略风控拒单趋势 (Risk Reject Trend by Strategy)</h3>
    <div id="risk-strategy-legend" class="legend"></div>
    <div id="risk-strategy-chart" class="chart chart-xs"></div>
  </div>
  <div id="liq-count-block" style="display:none">
    <h3>按日强平标的数趋势 (Daily Liquidation Count)</h3>
    <div id="liq-count-chart" class="chart chart-xs"></div>
  </div>
  <div id="liq-interest-block" style="display:none">
    <h3>按日强平计息 (Daily Liquidation Interest)</h3>
    <div id="liq-interest-chart" class="chart chart-xs"></div>
  </div>
  <div id="risk-top-block" style="display:none">
    <h3>拒单原因 Top 8 明细 (Top Reject Reasons)</h3>
    <div id="risk-top"></div>
  </div>
</section>
</div>
<footer>AKQuant Report | Powered by TradingView Lightweight Charts
  &amp; akquant-lwc</footer>

<script id="app-data" type="application/json">__APP_JSON__</script>
<script>
__APP_JS__
</script>
</body>
</html>
"""
