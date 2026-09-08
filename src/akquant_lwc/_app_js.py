"""Browser-side JavaScript application for the akquant-lwc report page.

The ``APP_JS`` constant is injected into the page template (``__APP_JS__``)
by :func:`akquant_lwc.report.render_html`. It renders every report section
from the embedded JSON payload: Lightweight Charts time-series charts,
built-in canvas charts for categorical data, pre-rendered HTML fragments
(tables/heatmap/ratio bars) and the interactive K-line trade review.
"""

APP_JS = r"""
(function () {
'use strict';
var APP = JSON.parse(document.getElementById('app-data').textContent);
var UP = '#ef5350';
var DOWN = '#26a69a';
var ACCENT = '#2962ff';
var GRAY = '#7f8c8d';
var EXCESS = '#c0392b';
var ORANGE = '#f58518';
var AMBER = '#fac858';

/* 主题调色板：payload 与主题无关，切换主题只重着色不重建数据 */
var PAL = {
  bg: '#ffffff',
  text: '#374151',
  sub: '#6b7280',
  grid: '#f3f4f6',
  border: '#e5e7eb'
};
var PAL_DARK = {
  bg: '#161d2e',
  text: '#e5e7eb',
  sub: '#9ca3af',
  grid: '#232c3f',
  border: '#2a3446'
};
var LWC_CHARTS = [];
var CANVAS_REDRAWS = [];

function applyTheme(dark) {
  PAL = dark ? PAL_DARK : {
    bg: '#ffffff',
    text: '#374151',
    sub: '#6b7280',
    grid: '#f3f4f6',
    border: '#e5e7eb'
  };
  document.documentElement.setAttribute(
    'data-theme', dark ? 'dark' : 'light');
  el('theme-toggle').textContent = dark ? '☀️ 浅色' : '🌙 暗色';
  LWC_CHARTS.forEach(function (chart) {
    chart.applyOptions({
      layout: {
        background: { type: 'solid', color: PAL.bg },
        textColor: PAL.text
      },
      grid: {
        vertLines: { color: PAL.grid },
        horzLines: { color: PAL.grid }
      },
      rightPriceScale: { borderColor: PAL.border },
      timeScale: { borderColor: PAL.border }
    });
  });
  CANVAS_REDRAWS.forEach(function (redraw) { redraw(null); });
}

el('theme-toggle').addEventListener('click', function () {
  applyTheme(
    document.documentElement.getAttribute('data-theme') !== 'dark');
});

function el(id) { return document.getElementById(id); }
function hasData(arr) { return arr && arr.length > 0; }

/* ---------------- formatting ---------------- */
function fmtPct(x, digits) {
  if (x == null || isNaN(x)) { return '-'; }
  return (x * 100).toFixed(digits == null ? 2 : digits) + '%';
}
function fmtNum(x) {
  if (x == null || isNaN(x)) { return '-'; }
  return Number(x).toLocaleString('zh-CN', { maximumFractionDigits: 2 });
}
function fmtSigned(x) {
  if (x == null || isNaN(x)) { return '-'; }
  return (x >= 0 ? '+' : '') + fmtNum(x);
}
function pnlClass(x) {
  if (x == null || isNaN(x)) { return ''; }
  return x >= 0 ? 'pos' : 'neg';
}
function pctPriceFormat(digits) {
  return {
    type: 'custom',
    minMove: 0.0001,
    formatter: function (v) { return fmtPct(v, digits); }
  };
}

/* ---------------- LWC base helpers ---------------- */
function wallTimeFmt(time) {
  if (time == null) { return ''; }
  if (typeof time === 'object') {
    var m = ('0' + time.month).slice(-2);
    var d = ('0' + time.day).slice(-2);
    return time.year + '-' + m + '-' + d;
  }
  if (typeof time === 'string') { return time.slice(0, 16); }
  var dt = new Date(time * 1000);
  if (isNaN(dt.getTime())) { return ''; }
  var iso = dt.toISOString();
  if (iso.slice(11, 16) === '00:00') { return iso.slice(0, 10); }
  return iso.slice(0, 16).replace('T', ' ');
}

function baseOpts(height) {
  return {
    height: height,
    layout: {
      background: { type: 'solid', color: PAL.bg },
      textColor: PAL.text,
      attributionLogo: false
    },
    grid: {
      vertLines: { color: PAL.grid },
      horzLines: { color: PAL.grid }
    },
    rightPriceScale: { borderColor: PAL.border },
    timeScale: {
      borderColor: PAL.border,
      timeVisible: true,
      tickMarkFormatter: wallTimeFmt
    },
    localization: { timeFormatter: wallTimeFmt },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal }
  };
}

function watchResize(chart, node) {
  if (typeof ResizeObserver === 'undefined') { return; }
  var ro = new ResizeObserver(function (entries) {
    var w = entries[0].contentRect.width;
    if (w > 0) { chart.applyOptions({ width: w }); }
  });
  ro.observe(node);
}

function makeTimeChart(nodeId, height) {
  var node = el(nodeId);
  if (!node) { return null; }
  var chart = LightweightCharts.createChart(node, baseOpts(height));
  LWC_CHARTS.push(chart);
  watchResize(chart, node);
  return chart;
}

function addArea(chart, data, color, isPct) {
  var series = chart.addSeries(LightweightCharts.AreaSeries, {
    lineColor: color,
    topColor: color + '47',
    bottomColor: color + '05',
    lineWidth: 2,
    priceLineVisible: false
  });
  if (isPct) { series.applyOptions({ priceFormat: pctPriceFormat(2) }); }
  series.setData(data);
  return series;
}

function addLine(chart, data, color, opts) {
  opts = opts || {};
  var series = chart.addSeries(LightweightCharts.LineSeries, {
    color: color,
    lineWidth: 2,
    priceLineVisible: false,
    lineStyle: opts.dashed
      ? LightweightCharts.LineStyle.Dashed
      : LightweightCharts.LineStyle.Solid,
    pointsVisible: !!opts.points
  });
  if (opts.isPct) { series.applyOptions({ priceFormat: pctPriceFormat(2) }); }
  series.setData(data);
  return series;
}

function syncCharts(charts) {
  var syncing = false;
  charts.forEach(function (src) {
    if (!src) { return; }
    src.timeScale().subscribeVisibleLogicalRangeChange(function (range) {
      if (syncing || !range) { return; }
      syncing = true;
      charts.forEach(function (dst) {
        if (dst && dst !== src) {
          dst.timeScale().setVisibleLogicalRange(range);
        }
      });
      syncing = false;
    });
  });
}

function renderLegend(nodeId, items) {
  var node = el(nodeId);
  if (!node) { return; }
  node.innerHTML = items.map(function (it) {
    return '<span class="legend-item">' +
      '<span class="legend-swatch" style="background:' + it.color + '"></span>' +
      it.name + '</span>';
  }).join('');
}

/* ---------------- header & summary & metrics ---------------- */
el('generated-at').textContent = APP.generatedAt || '';

(function renderSummary() {
  var box = el('summary-box');
  var items = [
    ['回测区间', APP.summary.range],
    ['回测时长', APP.summary.duration],
    ['初始资金', APP.summary.initial_cash],
    ['最终权益', APP.summary.final_equity]
  ];
  box.innerHTML = items.map(function (kv) {
    return '<div class="summary-item"><div class="label">' + kv[0] +
      '</div><div class="value">' + kv[1] + '</div></div>';
  }).join('');
})();

function renderMetricCards(nodeId, cards) {
  var node = el(nodeId);
  if (!hasData(cards)) {
    node.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  node.innerHTML = cards.map(function (m) {
    var cls = m.cls ? ' ' + m.cls : '';
    return '<div class="metric"><div class="label">' + m.label +
      '</div><div class="value' + cls + '">' + m.value + '</div></div>';
  }).join('');
}
renderMetricCards('metrics', APP.metrics);

/* ---------------- equity / drawdown / heatmap ---------------- */
var eqChart = null;
var ddChart = null;
if (hasData(APP.equity)) {
  eqChart = makeTimeChart('equity-chart', 300);
  addArea(eqChart, APP.equity, ACCENT, false);
  eqChart.timeScale().fitContent();
} else {
  el('equity-chart').innerHTML = '<div class="hint">暂无数据</div>';
}
if (hasData(APP.drawdown)) {
  ddChart = makeTimeChart('drawdown-chart', 180);
  addArea(ddChart, APP.drawdown, UP, true);
  ddChart.timeScale().fitContent();
} else {
  el('drawdown-chart').innerHTML = '<div class="hint">暂无数据</div>';
}
syncCharts([eqChart, ddChart]);
el('monthly-heatmap').innerHTML =
  APP.monthlyHeatmapHtml || '<div class="hint">暂无数据</div>';

/* ---------------- canvas chart engine ---------------- */
function canvasCtx(canvas) {
  var dpr = window.devicePixelRatio || 1;
  var w = canvas.clientWidth;
  var h = canvas.clientHeight;
  canvas.width = Math.max(1, Math.round(w * dpr));
  canvas.height = Math.max(1, Math.round(h * dpr));
  var ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx: ctx, w: w, h: h };
}

function makeCanvasChart(node, height, drawFn, hoverFn, clickFn) {
  node.style.position = 'relative';
  var canvas = document.createElement('canvas');
  canvas.className = 'chart-canvas';
  canvas.style.height = height + 'px';
  node.appendChild(canvas);
  var tip = document.createElement('div');
  tip.className = 'tooltip';
  node.appendChild(tip);
  function redraw(hover) {
    var c = canvasCtx(canvas);
    drawFn(c.ctx, c.w, c.h, hover);
  }
  CANVAS_REDRAWS.push(redraw);
  redraw(null);
  if (typeof ResizeObserver !== 'undefined') {
    var ro = new ResizeObserver(function () { redraw(null); });
    ro.observe(canvas);
  }
  if (hoverFn) {
    canvas.addEventListener('mousemove', function (ev) {
      var rect = canvas.getBoundingClientRect();
      var hit = hoverFn(ev.clientX - rect.left, ev.clientY - rect.top,
        rect.width, rect.height);
      if (!hit) {
        tip.style.display = 'none';
        redraw(null);
        return;
      }
      redraw(hit);
      tip.innerHTML = hit.html;
      tip.style.display = 'block';
      // 靠近右/下边缘时翻转到点的另一侧，避免被容器截断
      var tw = tip.offsetWidth;
      var th = tip.offsetHeight;
      var lx = hit.x + 12;
      if (lx + tw > rect.width - 4) { lx = Math.max(4, hit.x - tw - 12); }
      var ty = hit.y + 12;
      if (ty + th > rect.height - 4) { ty = Math.max(4, hit.y - th - 12); }
      tip.style.left = lx + 'px';
      tip.style.top = ty + 'px';
    });
    canvas.addEventListener('mouseleave', function () {
      tip.style.display = 'none';
      redraw(null);
    });
  }
  if (clickFn) {
    canvas.addEventListener('click', function (ev) {
      var rect = canvas.getBoundingClientRect();
      clickFn(ev.clientX - rect.left, ev.clientY - rect.top,
        rect.width, rect.height);
    });
    canvas.style.cursor = 'pointer';
  }
}

var AX = { l: 58, r: 14, t: 18, b: 32 };

function niceRange(minV, maxV) {
  if (minV > 0) { minV = 0; }
  if (maxV < 0) { maxV = 0; }
  if (minV === maxV) { minV -= 1; maxV += 1; }
  var pad = (maxV - minV) * 0.08;
  return [minV - pad, maxV + pad];
}

function drawAxes(ctx, w, h, minV, maxV, yFmt) {
  var H = h - AX.t - AX.b;
  function y(v) { return AX.t + H - (v - minV) / (maxV - minV) * H; }
  ctx.strokeStyle = PAL.grid;
  ctx.fillStyle = PAL.sub;
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'right';
  ctx.lineWidth = 1;
  for (var i = 0; i <= 4; i++) {
    var v = minV + (maxV - minV) * i / 4;
    var yy = y(v);
    ctx.beginPath();
    ctx.moveTo(AX.l, yy);
    ctx.lineTo(w - AX.r, yy);
    ctx.stroke();
    ctx.fillText(yFmt(v), AX.l - 6, yy + 3);
  }
  if (minV < 0 && maxV > 0) {
    ctx.strokeStyle = PAL.sub;
    ctx.beginPath();
    ctx.moveTo(AX.l, y(0));
    ctx.lineTo(w - AX.r, y(0));
    ctx.stroke();
  }
  return y;
}

function drawBarsChart(node, data, height) {
  if (!hasData(data)) {
    node.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  makeCanvasChart(node, height || 220, function (ctx, w, h) {
    var values = data.map(function (d) { return d.value; });
    var range = niceRange(Math.min.apply(null, values),
      Math.max.apply(null, values));
    var y = drawAxes(ctx, w, h, range[0], range[1],
      function (v) { return fmtPct(v, 0); });
    var n = data.length;
    var W = w - AX.l - AX.r;
    var bw = Math.max(4, Math.min(56, W / n * 0.55));
    ctx.textAlign = 'center';
    data.forEach(function (d, i) {
      var cx = AX.l + W * (i + 0.5) / n;
      var y0 = y(0);
      var y1 = y(d.value);
      ctx.fillStyle = d.value >= 0 ? UP : DOWN;
      ctx.fillRect(cx - bw / 2, Math.min(y0, y1), bw,
        Math.max(1, Math.abs(y1 - y0)));
      ctx.fillStyle = PAL.text;
      ctx.fillText(fmtPct(d.value), cx, Math.min(y0, y1) - 5);
      ctx.fillStyle = PAL.sub;
      ctx.fillText(String(d.label), cx, h - AX.b + 15);
    });
  }, null);
}

function drawHistChart(node, payload, height, xFmt, yFmt) {
  var bins = payload.bins || [];
  if (!hasData(bins)) {
    node.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  var line = payload.normal || [];
  makeCanvasChart(node, height || 220, function (ctx, w, h, hover) {
    var x0 = bins[0].x0;
    var x1 = bins[bins.length - 1].x1;
    var maxY = 0;
    bins.forEach(function (b) { maxY = Math.max(maxY, b.y); });
    line.forEach(function (p) { maxY = Math.max(maxY, p.y); });
    var range = niceRange(0, maxY);
    var y = drawAxes(ctx, w, h, range[0], range[1], yFmt);
    var W = w - AX.l - AX.r;
    function xp(v) { return AX.l + (v - x0) / (x1 - x0) * W; }
    bins.forEach(function (b, i) {
      ctx.fillStyle = (hover && hover.bin === i) ? ACCENT : 'rgba(41,98,255,0.55)';
      var bw = Math.max(1, xp(b.x1) - xp(b.x0) - 1);
      ctx.fillRect(xp(b.x0), y(b.y), bw, y(0) - y(b.y));
    });
    if (hasData(line)) {
      ctx.strokeStyle = '#6b7280';
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      line.forEach(function (p, i) {
        if (i === 0) { ctx.moveTo(xp(p.x), y(p.y)); }
        else { ctx.lineTo(xp(p.x), y(p.y)); }
      });
      ctx.stroke();
      ctx.setLineDash([]);
    }
    ctx.fillStyle = PAL.sub;
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(xFmt(x0), AX.l + 10, h - AX.b + 15);
    ctx.fillText(xFmt((x0 + x1) / 2), AX.l + W / 2, h - AX.b + 15);
    ctx.fillText(xFmt(x1), w - AX.r - 10, h - AX.b + 15);
  }, function (mx, my, w, h) {
    var x0 = bins[0].x0;
    var x1 = bins[bins.length - 1].x1;
    var W = w - AX.l - AX.r;
    if (mx < AX.l || mx > w - AX.r) { return null; }
    var v = x0 + (mx - AX.l) / W * (x1 - x0);
    for (var i = 0; i < bins.length; i++) {
      if (v >= bins[i].x0 && v <= bins[i].x1) {
        return {
          bin: i,
          x: mx,
          y: my,
          html: '区间 [' + xFmt(bins[i].x0) + ', ' + xFmt(bins[i].x1) + ']' +
            '<br/>值: ' + fmtNum(bins[i].y)
        };
      }
    }
    return null;
  });
}

function drawScatterChart(node, payload, height) {
  var points = payload.points || [];
  if (!hasData(points)) {
    node.innerHTML = '<div class="hint">暂无数据</div>';
    return;
  }
  var xs = points.map(function (p) { return p.x; });
  var ys = points.map(function (p) { return p.y; });
  var minX = Math.min.apply(null, xs);
  var maxX = Math.max.apply(null, xs);
  if (minX === maxX) { minX -= 1; maxX += 1; }
  var rangeY = niceRange(Math.min.apply(null, ys), Math.max.apply(null, ys));

  function makeScaler(w, h) {
    var W = w - AX.l - AX.r;
    var H = h - AX.t - AX.b;
    return {
      xp: function (v) { return AX.l + (v - minX) / (maxX - minX) * W; },
      yv: function (v) {
        return AX.t + H - (v - rangeY[0]) / (rangeY[1] - rangeY[0]) * H;
      }
    };
  }

  function hitAt(mx, my, w, h, radius) {
    var sc = makeScaler(w, h);
    var best = null;
    var bestD = radius * radius;
    points.forEach(function (p, i) {
      var dx = sc.xp(p.x) - mx;
      var dy = sc.yv(p.y) - my;
      var d = dx * dx + dy * dy;
      if (d < bestD) {
        bestD = d;
        best = { idx: i, x: sc.xp(p.x), y: sc.yv(p.y) };
      }
    });
    return best;
  }

  function pointHtml(p) {
    var dir = p.side === 'short' ? '空头' : '多头';
    var lines = [
      '<b>' + p.symbol + ' · ' + dir + '</b>',
      '持仓 ' + p.x.toFixed(1) + ' ' + payload.unit +
        (p.duration_bars != null ? '（' + p.duration_bars + ' 根K线）' : '')
    ];
    if (p.entry_label) {
      lines.push('开仓 ' + p.entry_label + ' @ ' + fmtNum(p.entry_price));
    }
    if (p.exit_label) {
      lines.push('平仓 ' + p.exit_label + ' @ ' + fmtNum(p.exit_price));
    }
    if (p.quantity != null) { lines.push('数量 ' + fmtNum(p.quantity)); }
    lines.push(
      '收益率 <span class="' + pnlClass(p.return_pct) + '">' +
      fmtPct(p.return_pct) + '</span>' +
      ' &nbsp;毛盈亏 ' + fmtSigned(p.pnl) +
      ' &nbsp;净盈亏 <span class="' + pnlClass(p.net_pnl) + '">' +
      fmtSigned(p.net_pnl) + '</span>'
    );
    lines.push('<span class="hint">点击跳转交易复盘 →</span>');
    return lines.join('<br/>');
  }

  makeCanvasChart(node, height || 220, function (ctx, w, h, hover) {
    var sc = makeScaler(w, h);
    var y = drawAxes(ctx, w, h, rangeY[0], rangeY[1],
      function (v) { return fmtNum(v); });
    points.forEach(function (p, i) {
      var hot = hover && hover.idx === i;
      ctx.fillStyle = p.y >= 0 ? UP : DOWN;
      ctx.beginPath();
      ctx.arc(sc.xp(p.x), y(p.y), hot ? 5 : 3, 0, Math.PI * 2);
      ctx.fill();
    });
    // x 轴数值刻度
    ctx.fillStyle = PAL.sub;
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    var tickCount = 5;
    var decimals = (maxX - minX) >= 20 ? 0 : 1;
    for (var i = 0; i <= tickCount; i++) {
      var v = minX + (maxX - minX) * i / tickCount;
      var tx = sc.xp(v);
      ctx.strokeStyle = PAL.grid;
      ctx.beginPath();
      ctx.moveTo(tx, h - AX.b);
      ctx.lineTo(tx, h - AX.b + 4);
      ctx.stroke();
      ctx.fillText(v.toFixed(decimals), tx, h - AX.b + 15);
    }
    ctx.fillText('持仓 (' + payload.unit + ')', AX.l + (w - AX.l - AX.r) / 2,
      h - 4);
  }, function (mx, my, w, h) {
    var best = hitAt(mx, my, w, h, 24);
    if (!best) { return null; }
    best.html = pointHtml(points[best.idx]);
    return best;
  }, function (mx, my, w, h) {
    var best = hitAt(mx, my, w, h, 32);
    if (!best) { return; }
    var symbol = points[best.idx].symbol;
    if (symbol && APP._switchSymbol) {
      APP._switchSymbol(symbol);
      var review = document.getElementById('kline-chart');
      if (review && review.scrollIntoView) {
        review.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }
  });
}

/* ---------------- return analysis charts ---------------- */
drawBarsChart(el('yearly-chart'), (APP.yearlyReturns || []).map(function (d) {
  return { label: d.year, value: d.value };
}), 220);
drawHistChart(el('retdist-chart'), APP.returnsDist || { bins: [] }, 220,
  function (v) { return fmtPct(v, 1); },
  function (v) { return fmtNum(v); });

var rollCharts = [];
if (hasData(APP.rolling && APP.rolling.sharpe)) {
  var c1 = makeTimeChart('roll-sharpe-chart', 180);
  addLine(c1, APP.rolling.sharpe, ACCENT, {});
  c1.timeScale().fitContent();
  rollCharts.push(c1);
} else {
  el('roll-sharpe-chart').innerHTML = '<div class="hint">样本不足</div>';
}
if (hasData(APP.rolling && APP.rolling.vol)) {
  var c2 = makeTimeChart('roll-vol-chart', 180);
  addLine(c2, APP.rolling.vol, ORANGE, { isPct: true });
  c2.timeScale().fitContent();
  rollCharts.push(c2);
} else {
  el('roll-vol-chart').innerHTML = '<div class="hint">样本不足</div>';
}
syncCharts(rollCharts);

/* ---------------- benchmark ---------------- */
(function renderBenchmark() {
  var bm = APP.benchmark || { available: false, reason: '未提供基准' };
  if (!bm.available) {
    el('benchmark-empty').style.display = '';
    el('benchmark-empty').textContent = bm.reason || '基准不可用';
    el('benchmark-chart').style.display = 'none';
    return;
  }
  renderMetricCards('benchmark-metrics', bm.cards);
  var chart = makeTimeChart('benchmark-chart', 300);
  addLine(chart, bm.strategy, ACCENT, { isPct: true });
  addLine(chart, bm.benchmark, GRAY, { isPct: true, dashed: true });
  addLine(chart, bm.excess, EXCESS, { isPct: true });
  chart.timeScale().fitContent();
  var legend = document.createElement('div');
  legend.className = 'legend';
  legend.innerHTML =
    '<span class="legend-item"><span class="legend-swatch" ' +
    'style="background:' + ACCENT + '"></span>策略累计收益</span>' +
    '<span class="legend-item"><span class="legend-swatch" ' +
    'style="background:' + GRAY + '"></span>基准累计收益</span>' +
    '<span class="legend-item"><span class="legend-swatch" ' +
    'style="background:' + EXCESS + '"></span>累计超额收益</span>';
  var chartNode = el('benchmark-chart');
  chartNode.parentNode.insertBefore(legend, chartNode);
})();

/* ---------------- trade analysis charts ---------------- */
drawHistChart(el('pnldist-chart'), APP.tradesDist || { bins: [] }, 220,
  function (v) { return fmtNum(v); },
  function (v) { return fmtNum(v); });
drawScatterChart(el('pnldur-chart'), APP.pnlDuration || { points: [] }, 220);

/* ---------------- analysis tables (pre-rendered fragments) ---------------- */
function injectFragment(nodeId, html, hideIfEmpty) {
  var node = el(nodeId);
  if (!node) { return; }
  if (html) {
    node.innerHTML = html;
  } else if (hideIfEmpty) {
    var details = node.closest('details');
    if (details) { details.style.display = 'none'; }
    else { node.innerHTML = '<div class="hint">暂无数据</div>'; }
  } else {
    node.innerHTML = '<div class="hint">暂无数据</div>';
  }
}

injectFragment('analysis-overview', APP.analysisOverviewHtml, false);
injectFragment('daily-positions', APP.dailyPositionsHtml, false);
injectFragment('tbl-exposure', (APP.analysisTables || {}).exposure, true);
injectFragment('tbl-capacity', (APP.analysisTables || {}).capacity, true);
injectFragment('tbl-attribution', (APP.analysisTables || {}).attribution, true);
injectFragment('tbl-orders', (APP.analysisTables || {}).orders, true);
injectFragment('tbl-executions', (APP.analysisTables || {}).executions, true);
injectFragment('tbl-risk', (APP.analysisTables || {}).risk, true);
injectFragment('tbl-liquidation', (APP.analysisTables || {}).liquidation, true);

/* ---------------- risk & liquidation section ---------------- */
(function renderRisk() {
  var risk = APP.risk || {};
  var anyBlock = false;
  function show(id) {
    el(id).style.display = '';
    anyBlock = true;
  }
  if (risk.ratioBarsHtml) {
    el('risk-ratio').innerHTML = risk.ratioBarsHtml;
    show('risk-ratio-block');
  }
  if (risk.reasonStackHtml) {
    el('risk-reason-stack').innerHTML = risk.reasonStackHtml;
    show('risk-stack-block');
  }
  if (hasData(risk.rejectTrend)) {
    var chart = makeTimeChart('risk-trend-chart', 180);
    addLine(chart, risk.rejectTrend, ACCENT, { points: true });
    chart.timeScale().fitContent();
    show('risk-trend-block');
  }
  var reasonSeries = (risk.reasonTrend && risk.reasonTrend.series) || [];
  if (hasData(reasonSeries)) {
    renderStackedArea('risk-reason-trend-chart', reasonSeries);
    renderLegend('risk-reason-legend', reasonSeries);
    show('risk-reason-trend-block');
  }
  var strategySeries = (risk.strategyTrend && risk.strategyTrend.series) || [];
  if (hasData(strategySeries)) {
    var sc = makeTimeChart('risk-strategy-chart', 180);
    strategySeries.forEach(function (s) {
      addLine(sc, s.data, s.color, { points: false });
    });
    sc.timeScale().fitContent();
    renderLegend('risk-strategy-legend', strategySeries);
    show('risk-strategy-block');
  }
  if (hasData(risk.liquidationCount)) {
    var lc = makeTimeChart('liq-count-chart', 180);
    addLine(lc, risk.liquidationCount, ACCENT, { points: true });
    lc.timeScale().fitContent();
    show('liq-count-block');
  }
  if (hasData(risk.interest)) {
    var ic = makeTimeChart('liq-interest-chart', 180);
    var hist = ic.addSeries(LightweightCharts.HistogramSeries, { color: AMBER, priceLineVisible: false });
    hist.setData(risk.interest);
    ic.timeScale().fitContent();
    show('liq-interest-block');
  }
  if (risk.topReasonsHtml) {
    el('risk-top').innerHTML = risk.topReasonsHtml;
    show('risk-top-block');
  }
  if (!anyBlock) {
    var reason = risk.emptyReason || '本次回测未产生风控拒单数据。';
    el('risk-empty').textContent = reason +
      ' 建议：可降低风险阈值或增加高波动样本以触发拒单统计。';
    el('risk-empty').style.display = '';
  }
})();

function renderStackedArea(nodeId, seriesList) {
  var chart = makeTimeChart(nodeId, 180);
  if (!chart) { return; }
  var timeSet = {};
  seriesList.forEach(function (s) {
    s.data.forEach(function (d) { timeSet[d.time] = 1; });
  });
  var times = Object.keys(timeSet).sort();
  var numeric = times.length > 0 && !isNaN(Number(times[0]));
  if (numeric) { times.sort(function (a, b) { return Number(a) - Number(b); }); }
  var cum = {};
  times.forEach(function (t) { cum[t] = 0; });
  var layers = seriesList.map(function (s) {
    var map = {};
    s.data.forEach(function (d) { map[d.time] = d.value; });
    var data = times.map(function (t) {
      cum[t] += (map[t] || 0);
      return {
        time: numeric ? Number(t) : t,
        value: cum[t]
      };
    });
    return { name: s.name, color: s.color, data: data };
  });
  for (var i = layers.length - 1; i >= 0; i--) {
    var series = chart.addSeries(LightweightCharts.AreaSeries, {
      lineColor: layers[i].color,
      topColor: layers[i].color,
      bottomColor: layers[i].color,
      lineWidth: 1,
      priceLineVisible: false
    });
    series.setData(layers[i].data);
  }
  chart.timeScale().fitContent();
}

/* ---------------- custom indicator panes ---------------- */
(function renderIndicators() {
  var ind = APP.indicators;
  if (!ind || !ind.enabled) { return; }
  el('indicator-card').style.display = '';
  if (ind.filterHint) {
    el('indicator-filter').textContent = '过滤条件: ' + ind.filterHint;
  }
  injectFragment('indicator-cards', ind.cardsHtml, false);
  injectFragment('indicator-defs', ind.defsHtml, false);
  var paneCharts = [];
  (ind.panes || []).forEach(function (pane, idx) {
    var holder = document.createElement('div');
    holder.className = 'chart chart-sm';
    holder.id = 'indicator-pane-' + idx;
    el('indicator-panes').appendChild(holder);
    var chart = makeTimeChart(holder.id, 220);
    pane.series.forEach(function (s) {
      var type = (s.type || 'line').toLowerCase();
      if (type === 'area') {
        addArea(chart, s.data, s.color, false);
      } else if (type === 'bar' || type === 'column' || type === 'histogram') {
        var hist = chart.addSeries(LightweightCharts.HistogramSeries, {
          color: s.color,
          priceLineVisible: false
        });
        hist.setData(s.data);
      } else if (type === 'scatter' || type === 'signal') {
        var sc = chart.addSeries(LightweightCharts.LineSeries, {
          color: s.color,
          lineVisible: false,
          pointsVisible: true,
          priceLineVisible: false
        });
        sc.setData(s.data);
      } else {
        addLine(chart, s.data, s.color, {});
      }
    });
    chart.timeScale().fitContent();
    paneCharts.push(chart);
  });
  syncCharts(paneCharts);
})();

/* ---------------- kline trade review ---------------- */
(function initReview() {
  if (APP.includeTradeKline === false) {
    el('symbol-status').textContent = '已关闭 K 线复盘图';
    el('symbol-input').disabled = true;
    el('symbol-go').disabled = true;
    return;
  }
  var klineNode = el('kline-chart');
  var klineChart = LightweightCharts.createChart(
    klineNode, baseOpts(klineNode.clientHeight || 460));
  LWC_CHARTS.push(klineChart);
  var candleSeries = klineChart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: UP,
    downColor: DOWN,
    borderVisible: false,
    wickUpColor: UP,
    wickDownColor: DOWN
  });
  candleSeries.priceScale().applyOptions({
    scaleMargins: { top: 0.08, bottom: 0.28 }
  });
  var volumeSeries = klineChart.addSeries(LightweightCharts.HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: ''
  });
  klineChart.priceScale('').applyOptions({
    scaleMargins: { top: 0.82, bottom: 0 }
  });
  var markersApi = LightweightCharts.createSeriesMarkers(candleSeries, []);
  watchResize(klineChart, klineNode);

  var currentSymbol = null;

  function setStatus(text, isError) {
    var node = el('symbol-status');
    node.textContent = text;
    node.className = isError ? 'status error' : 'status';
  }

  function addSymbolOption(code) {
    var list = el('symbol-list');
    var exists = Array.prototype.some.call(
      list.options, function (o) { return o.value === code; });
    if (!exists) {
      var opt = document.createElement('option');
      opt.value = code;
      list.appendChild(opt);
    }
  }

  (APP.symbols || []).forEach(addSymbolOption);

  function renderKline(payload) {
    candleSeries.setData(payload.candles || []);
    volumeSeries.setData(payload.volumes || []);
    markersApi.setMarkers(payload.markers || []);
    payload._times = (payload.candles || []).map(function (c) {
      return c.time;
    });
    klineChart.timeScale().fitContent();
  }

  function renderTradesTable(payload) {
    var tbody = el('trades-body');
    var table = el('trades-table');
    tbody.innerHTML = '';
    var trades = payload.trades || [];
    table.style.display = trades.length ? '' : 'none';
    trades.forEach(function (t) {
      var tr = document.createElement('tr');
      var cells = [
        t.side === 'short' ? '空' : '多',
        t.side === 'short' ? 'S→B' : 'B→S',
        t.entry_label,
        fmtNum(t.entry_price),
        t.exit_label,
        fmtNum(t.exit_price),
        fmtNum(t.quantity),
        fmtPct(t.return_pct),
        fmtSigned(t.net_pnl)
      ];
      cells.forEach(function (text, idx) {
        var td = document.createElement('td');
        td.textContent = text == null ? '-' : text;
        if (idx >= 7) { td.className = pnlClass(t.net_pnl); }
        tr.appendChild(td);
      });
      tr.addEventListener('click', function () {
        focusTrade(payload, t);
      });
      tbody.appendChild(tr);
    });
  }

  function focusTrade(payload, trade) {
    var times = payload._times || [];
    var i = times.indexOf(trade.entry_time);
    var j = times.indexOf(trade.exit_time);
    if (i < 0) { i = 0; }
    if (j < 0) { j = times.length - 1; }
    klineChart.timeScale().setVisibleLogicalRange({
      from: Math.max(0, i - 10),
      to: Math.min(times.length + 10, j + 10)
    });
  }

  function tradeTipHtml(trades, time) {
    var rows = trades.map(function (t) {
      var isEntry = t.entry_time === time;
      var pnl = fmtSigned(t.net_pnl);
      var cls = pnlClass(t.net_pnl);
      var head = isEntry ? '开仓' : '平仓';
      var dir = t.side === 'short' ? '空头' : '多头';
      return '<div><b>' + head + ' · ' + dir + '</b><br/>' +
        '开仓 ' + t.entry_label + ' @ ' + fmtNum(t.entry_price) + '<br/>' +
        '平仓 ' + t.exit_label + ' @ ' + fmtNum(t.exit_price) + '<br/>' +
        '数量 ' + fmtNum(t.quantity) +
        ' &nbsp;收益率 ' + fmtPct(t.return_pct) +
        ' &nbsp;净利润 <span class="' + cls + '">' + pnl + '</span></div>';
    });
    return rows.join('<hr style="border:none;' +
      'border-top:1px solid #eee;margin:6px 0"/>');
  }

  klineChart.subscribeCrosshairMove(function (param) {
    var tip = el('trade-tooltip');
    if (!param.time || !param.point || currentSymbol == null) {
      tip.style.display = 'none';
      return;
    }
    var payload = APP.payloads[currentSymbol];
    if (!payload) {
      tip.style.display = 'none';
      return;
    }
    var time = param.time;
    var hits = (payload.trades || []).filter(function (t) {
      return t.entry_time === time || t.exit_time === time;
    });
    if (!hits.length) {
      tip.style.display = 'none';
      return;
    }
    tip.innerHTML = tradeTipHtml(hits, time);
    tip.style.display = 'block';
    var rect = klineNode.getBoundingClientRect();
    var x = Math.min(param.point.x + 16, rect.width - 340);
    var y = Math.min(param.point.y + 16, rect.height - 150);
    tip.style.left = Math.max(0, x) + 'px';
    tip.style.top = Math.max(0, y) + 'px';
  });

  function ensurePayload(code) {
    if (APP.payloads[code]) {
      return Promise.resolve(APP.payloads[code]);
    }
    if (!APP.serverMode) {
      return Promise.reject(new Error('报告中未包含该标的的行情数据'));
    }
    return fetch('/api/symbol?code=' + encodeURIComponent(code))
      .then(function (resp) {
        if (!resp.ok) {
          return resp.json().then(function (body) {
            throw new Error(body.error || ('HTTP ' + resp.status));
          });
        }
        return resp.json();
      })
      .then(function (payload) {
        APP.payloads[code] = payload;
        addSymbolOption(code);
        return payload;
      });
  }

  function switchSymbol(code) {
    code = (code || '').trim();
    if (!code) { return; }
    setStatus('加载中…');
    ensurePayload(code).then(function (payload) {
      currentSymbol = code;
      el('symbol-input').value = code;
      renderKline(payload);
      renderTradesTable(payload);
      setStatus(
        '当前复盘：' + code +
        '（' + (payload.candles || []).length + ' 根K线，' +
        (payload.trades || []).length + ' 笔交易）'
      );
    }).catch(function (err) {
      setStatus('无法加载 ' + code + '：' + err.message, true);
    });
  }

  // 供其他图表（如盈亏 vs 持仓时间散点）点击联动复盘
  APP._switchSymbol = switchSymbol;

  el('symbol-go').addEventListener('click', function () {
    switchSymbol(el('symbol-input').value);
  });
  el('symbol-input').addEventListener('keydown', function (ev) {
    if (ev.key === 'Enter') { switchSymbol(el('symbol-input').value); }
  });

  var ext = APP.externalData;
  if (ext && ext.file) {
    // 外置数据模式：一次文件授权（浏览器安全要求），之后全部热切换
    el('data-loader').style.display = '';
    el('data-file-name').textContent = ext.file;
    setStatus('请先打开数据文件');
    el('data-file-btn').addEventListener('click', function () {
      el('data-file-input').click();
    });
    el('data-file-input').addEventListener('change', function (ev) {
      var file = ev.target.files && ev.target.files[0];
      if (!file) { return; }
      var status = el('data-file-status');
      status.textContent = ' 读取中…';
      var reader = new FileReader();
      reader.onload = function () {
        try {
          var companion = JSON.parse(reader.result);
          var payloads = companion.payloads || {};
          Object.keys(payloads).forEach(function (code) {
            APP.payloads[code] = payloads[code];
          });
          (companion.symbols || Object.keys(payloads)).forEach(addSymbolOption);
          el('data-loader').style.display = 'none';
          if (APP.initialSymbol) {
            switchSymbol(APP.initialSymbol);
          } else {
            setStatus('数据已加载，请输入股票代码开始复盘');
          }
        } catch (err) {
          status.textContent = ' 解析失败：' + err.message;
        }
      };
      reader.onerror = function () {
        status.textContent = ' 读取失败，请重试';
      };
      reader.readAsText(file);
    });
  } else if (APP.initialSymbol) {
    switchSymbol(APP.initialSymbol);
  } else if (!hasData(APP.symbols)) {
    setStatus('未提供行情数据，已跳过 K 线复盘图');
  } else {
    setStatus('请输入股票代码开始复盘');
  }
})();

})();
"""
