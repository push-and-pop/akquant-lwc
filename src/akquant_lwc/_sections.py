"""Section builders for the full akquant-lwc report (plotly-report parity).

Each builder returns JSON-serializable dicts/lists (chart payloads) or
pre-rendered HTML fragments (tables, heatmap, overview cards). The report
orchestrator (:mod:`akquant_lwc.report`) assembles them into the final
application payload consumed by the browser page.

Color semantics follow the A-share convention used throughout the report:
``pos`` = red (positive/up), ``neg`` = green (negative/down), ``warn`` = red
warning (drawdown cards).
"""

from __future__ import annotations

import html as _html
import math
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from ._tables import format_currency, format_table, rename_columns

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _num(value: Any) -> Optional[float]:
    """Coerce to float, returning None for missing/NaN values."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v or math.isinf(v):
        return None
    return v


def _fmt_pct100(v: Any) -> Optional[str]:
    n = _num(v)
    return f"{n:.2f}%" if n is not None else None


def _fmt_ratio(v: Any) -> Optional[str]:
    n = _num(v)
    return f"{n * 100:.2f}%" if n is not None else None


def _fmt_num(v: Any, digits: int = 2) -> Optional[str]:
    n = _num(v)
    return f"{n:.{digits}f}" if n is not None else None


def _fmt_int(v: Any) -> Optional[str]:
    n = _num(v)
    return f"{n:.0f}" if n is not None else None


def _sign_cls(v: Any) -> str:
    n = _num(v)
    if n is None or n == 0:
        return ""
    return "pos" if n > 0 else "neg"


def _read_metric(result: Any, *names: str) -> Optional[float]:
    """Read a numeric metric from result.metrics/trade_metrics/metrics_df.

    Names are probed on ``result.metrics`` and ``result.trade_metrics``
    first, then looked up in ``result.metrics_df`` (index=name, column
    ``value``) as a fallback.
    """
    for owner in (
        getattr(result, "metrics", None),
        getattr(result, "trade_metrics", None),
    ):
        if owner is None:
            continue
        for name in names:
            value = getattr(owner, name, None)
            n = _num(value)
            if n is not None:
                return n
    metrics_df = getattr(result, "metrics_df", None)
    if metrics_df is not None:
        for name in names:
            try:
                return _num(metrics_df.loc[name, "value"])
            except Exception:
                continue
    return None


def _date_str(ts: Any) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _series_tokens(series: pd.Series) -> List[Dict[str, Any]]:
    """Convert a datetime-indexed series to business-day token points."""
    return [
        {"time": _date_str(t), "value": float(v)}
        for t, v in series.items()
        if _num(v) is not None
    ]


def resolve_equity_series(result: Any, curve_freq: str = "D") -> pd.Series:
    """Resolve the equity curve as a tz-naive datetime-indexed Series.

    ``"D"`` prefers ``equity_curve_daily`` (daily last values); ``"raw"``
    keeps ``equity_curve`` at its original frequency. Timezones are stripped
    keeping wall-clock time (display convention of the AKQuant wrapper).

    :param result: ``BacktestResult``-like object.
    :param curve_freq: ``"D"`` or ``"raw"``.
    :return: Sorted, deduplicated Series; empty when unavailable.
    """
    series = None
    if curve_freq == "raw":
        candidate = getattr(result, "equity_curve", None)
        if candidate is not None and len(candidate) > 0:
            series = candidate
    else:
        for attr in ("equity_curve_daily", "equity_curve"):
            candidate = getattr(result, attr, None)
            if candidate is not None and len(candidate) > 0:
                series = candidate
                break
    if series is None:
        return pd.Series(dtype="float64")
    s = pd.Series(series, dtype="float64").copy()
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx
    s = s[~s.index.duplicated(keep="last")].sort_index()
    if curve_freq != "raw":
        s = s.resample("D").last().ffill().dropna()
    return s


def daily_returns_from_equity(equity: pd.Series) -> pd.Series:
    """Compute daily simple returns from an equity series."""
    if equity.empty:
        return pd.Series(dtype="float64")
    daily = equity.resample("D").last().ffill().dropna()
    return daily.pct_change().dropna()


# ---------------------------------------------------------------------------
# summary box & metric cards
# ---------------------------------------------------------------------------


def build_summary(result: Any, equity: pd.Series) -> Dict[str, str]:
    """Build the four summary-box fields of the report header.

    :param result: ``BacktestResult``-like object.
    :param equity: Equity series from :func:`resolve_equity_series`.
    :return: Dict with ``range``/``duration``/``initial_cash``/``final_equity``.
    """
    start = end = duration = final = "N/A"
    if not equity.empty:
        start = _date_str(equity.index[0])
        end = _date_str(equity.index[-1])
        duration = f"{(equity.index[-1] - equity.index[0]).days} 天"
        final = f"{equity.iloc[-1]:,.2f}"
    initial = getattr(result, "initial_cash", None)
    initial_str = f"{float(initial):,.2f}" if _num(initial) is not None else "N/A"
    return {
        "range": f"{start} ~ {end}" if equity is not None else "N/A",
        "duration": duration,
        "initial_cash": initial_str,
        "final_equity": final,
    }


def build_metric_cards(result: Any, compact: bool = True) -> List[Dict[str, str]]:
    """Build the 15 key-metric cards (label/value/color-class).

    Mirrors the plotly report's metric grid; cards whose value cannot be
    resolved are skipped.

    :param result: ``BacktestResult``-like object.
    :param compact: Compact K/M/B amounts switch (Max DD Amount card).
    :return: List of ``{"label", "value", "cls"}`` dicts.
    """
    cards: List[Dict[str, str]] = []

    def add(label: str, value: Optional[str], cls: str = "") -> None:
        if value is not None:
            cards.append({"label": label, "value": value, "cls": cls})

    tr = _read_metric(result, "total_return_pct")
    add("累计收益率 (Total Return)", _fmt_pct100(tr), _sign_cls(tr))
    ar = _read_metric(result, "annualized_return")
    add("年化收益率 (CAGR)", _fmt_ratio(ar), _sign_cls(ar))
    avg_pnl = _read_metric(result, "avg_pnl")
    add("平均盈亏 (Avg PnL)", _fmt_num(avg_pnl), _sign_cls(avg_pnl))
    sharpe = _read_metric(result, "sharpe_ratio")
    add("夏普比率 (Sharpe)", _fmt_num(sharpe), _sign_cls(sharpe))
    sortino = _read_metric(result, "sortino_ratio")
    add("索提诺比率 (Sortino)", _fmt_num(sortino), _sign_cls(sortino))
    calmar = _read_metric(result, "calmar_ratio")
    add("卡玛比率 (Calmar)", _fmt_num(calmar), _sign_cls(calmar))
    dd = _read_metric(result, "max_drawdown_pct")
    add("最大回撤 (Max DD)", _fmt_pct100(dd), "warn" if dd is not None else "")
    ddv = _read_metric(result, "max_drawdown_value")
    ddv_str = None if ddv is None else format_currency(ddv, compact=compact)
    add("最大回撤金额 (Max DD Amount)", ddv_str, "warn" if ddv is not None else "")
    vol = _read_metric(result, "volatility")
    add("波动率 (Volatility)", _fmt_ratio(vol))
    win = _read_metric(result, "win_rate")
    add("胜率 (Win Rate)", _fmt_pct100(win))
    pf = _read_metric(result, "profit_factor")
    add("盈亏比 (Profit Factor)", _fmt_num(pf))
    kelly = _read_metric(result, "kelly_criterion")
    add("凯利公式 (Kelly)", _fmt_ratio(kelly))

    closed = _read_metric(result, "total_closed_trades", "closed_trade_count")
    if closed is None:
        trades_df = getattr(result, "trades_df", None)
        if trades_df is not None:
            closed = float(len(trades_df))
    add("已完成交易数 (Closed Trades)", _fmt_int(closed))

    executions = _read_metric(result, "execution_count")
    if executions is None:
        executions_df = getattr(result, "executions_df", None)
        if executions_df is not None:
            executions = float(len(executions_df))
    add("成交笔数 (Executions)", _fmt_int(executions))

    open_pos = _read_metric(result, "open_position_count")
    if open_pos is None:
        open_pos = _count_open_positions(result)
    add("未平仓标的数 (Open Positions)", _fmt_int(open_pos))
    return cards


def _count_open_positions(result: Any) -> Optional[float]:
    """Count symbols with non-zero position on the last snapshot day."""
    positions_df = getattr(result, "positions_df", None)
    if positions_df is None or len(positions_df) == 0:
        return None
    try:
        df = positions_df
        last = df[df["date"] == df["date"].max()]
        long_s = last.get("long_shares", 0)
        short_s = last.get("short_shares", 0)
        return float(((long_s.fillna(0) != 0) | (short_s.fillna(0) != 0)).sum())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# return analysis: heatmap / yearly / distribution / rolling
# ---------------------------------------------------------------------------

_MONTH_NAMES = [f"{m}月" for m in range(1, 13)]


def build_monthly_heatmap_html(daily_returns: pd.Series) -> str:
    """Render the monthly-returns heatmap as an HTML table.

    Rows are years, columns are months; cell background interpolates
    white->red (positive) / white->green (negative) scaled by magnitude.

    :param daily_returns: Daily simple returns.
    :return: HTML table string, or a hint div when empty.
    """
    if daily_returns.empty:
        return '<div class="hint">暂无数据</div>'
    monthly = (1.0 + daily_returns).resample("ME").prod() - 1.0
    if monthly.empty:
        return '<div class="hint">暂无数据</div>'
    pivot: Dict[int, Dict[int, float]] = {}
    for ts, v in monthly.items():
        pivot.setdefault(ts.year, {})[ts.month] = float(v)
    years = sorted(pivot)
    limit = max(
        (abs(v) for month_map in pivot.values() for v in month_map.values()),
        default=0.0,
    )

    def cell(v: Optional[float]) -> str:
        if v is None:
            return "<td></td>"
        alpha = 0.15 + 0.65 * min(abs(v) / limit, 1.0) if limit > 0 else 0.15
        rgb = "211, 47, 47" if v >= 0 else "46, 125, 50"
        cls = "pos" if v >= 0 else "neg"
        style = f"background: rgba({rgb}, {alpha:.2f})"
        if alpha > 0.55:
            style += "; color: #fff"
        return f'<td class="{cls}" style="{style}">{v * 100:.2f}%</td>'

    head = (
        "<tr><th>年份</th>" + "".join(f"<th>{m}</th>" for m in _MONTH_NAMES) + "</tr>"
    )
    rows = []
    for year in years:
        cells = "".join(cell(pivot[year].get(m)) for m in range(1, 13))
        rows.append(f"<tr><td><b>{year}</b></td>{cells}</tr>")
    return (
        '<table class="data-table heatmap"><thead>'
        + head
        + "</thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )


def build_yearly_returns(daily_returns: pd.Series) -> List[Dict[str, Any]]:
    """Compound daily returns into per-year bars.

    :param daily_returns: Daily simple returns.
    :return: List of ``{"year", "value"}`` (value as decimal fraction).
    """
    if daily_returns.empty:
        return []
    yearly = (1.0 + daily_returns).resample("YE").prod() - 1.0
    return [{"year": int(ts.year), "value": float(v)} for ts, v in yearly.items()]


def build_returns_distribution(
    daily_returns: pd.Series, bins: int = 50
) -> Dict[str, Any]:
    """Histogram of daily returns plus a fitted normal curve.

    :param daily_returns: Daily simple returns.
    :param bins: Number of histogram bins.
    :return: Dict with ``bins`` (density heights), ``normal`` (pdf curve),
        ``mu`` and ``sigma``; empty lists when data is insufficient.
    """
    if len(daily_returns) < 5:
        return {"bins": [], "normal": [], "mu": 0.0, "sigma": 0.0}
    import numpy as np

    values = daily_returns.to_numpy(dtype="float64")
    mu = float(values.mean())
    sigma = float(values.std(ddof=1)) or 1e-12
    heights, edges = np.histogram(values, bins=bins, density=True)
    bin_list = [
        {"x0": float(edges[i]), "x1": float(edges[i + 1]), "y": float(heights[i])}
        for i in range(len(heights))
    ]
    xs = np.linspace(edges[0], edges[-1], 120)
    pdf = np.exp(-0.5 * ((xs - mu) / sigma) ** 2) / (sigma * math.sqrt(2 * math.pi))
    normal = [{"x": float(x), "y": float(y)} for x, y in zip(xs, pdf)]
    return {"bins": bin_list, "normal": normal, "mu": mu, "sigma": sigma}


def build_rolling_metrics(
    daily_returns: pd.Series, window: int = 126
) -> Dict[str, List[Dict[str, Any]]]:
    """Compute rolling Sharpe (mean/std*sqrt(252)) and rolling volatility.

    :param daily_returns: Daily simple returns.
    :param window: Rolling window in trading days (126 in the original).
    :return: Dict with ``sharpe`` and ``vol`` token-point lists.
    """
    if len(daily_returns) < window + 1:
        return {"sharpe": [], "vol": []}
    roll = daily_returns.rolling(window)
    std = roll.std()
    sharpe = (roll.mean() / std.replace(0.0, pd.NA)) * math.sqrt(252)
    vol = std * math.sqrt(252)
    return {
        "sharpe": _series_tokens(sharpe.dropna()),
        "vol": _series_tokens(vol.dropna()),
    }


# ---------------------------------------------------------------------------
# benchmark comparison
# ---------------------------------------------------------------------------


def build_benchmark_sections(
    daily_returns: pd.Series,
    benchmark: Optional[Union[str, pd.Series]],
) -> Dict[str, Any]:
    """Build benchmark comparison cards and cumulative-curve payloads.

    Mirrors the plotly report: string benchmarks are unsupported (reason
    echoed); series whose 95th percentile of absolute values exceeds 2 are
    treated as price/equity series and converted via ``pct_change``.

    :param daily_returns: Strategy daily returns (decimal fractions).
    :param benchmark: Benchmark daily returns Series, a label string or None.
    :return: Dict with ``available``/``reason``/``cards``/``strategy``/
        ``benchmark``/``excess`` keys.
    """
    unavailable: Dict[str, Any] = {
        "available": False,
        "reason": "",
        "cards": [],
        "strategy": [],
        "benchmark": [],
        "excess": [],
    }
    if benchmark is None:
        unavailable["reason"] = "未提供基准"
        return unavailable
    if isinstance(benchmark, str):
        unavailable["reason"] = f"暂不支持自动拉取基准： {benchmark}"
        return unavailable

    b = pd.Series(benchmark, dtype="float64").copy()
    idx = pd.to_datetime(b.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    b.index = idx
    b = b[~b.index.duplicated(keep="last")].sort_index()
    label = str(benchmark.name) if getattr(benchmark, "name", None) else "Benchmark"
    if len(b) and float(b.abs().quantile(0.95)) > 2.0:
        b = b.pct_change().dropna()

    aligned = pd.concat(
        [daily_returns.rename("s"), b.rename("b")], axis=1, join="inner"
    ).dropna()
    if aligned.empty:
        unavailable["reason"] = "基准与策略收益无重叠样本"
        return unavailable

    s, bb = aligned["s"], aligned["b"]
    excess_daily = s - bb
    annual_excess = float(excess_daily.mean()) * 252
    tracking_error = float(excess_daily.std(ddof=0)) * math.sqrt(252)
    info_ratio = annual_excess / tracking_error if tracking_error > 0 else None
    total_excess = float((1 + s).prod() / (1 + bb).prod() - 1.0)
    var_b = float(bb.var(ddof=0))
    # 协方差用逐元素运算，避免 DataFrame.cov 触发 numpy BLAS matmul
    # （部分环境 numpy BLAS 会无声崩溃）
    cov_sb = float(((s - s.mean()) * (bb - bb.mean())).mean())
    beta = cov_sb / var_b if var_b > 0 else None
    alpha = (
        (float(s.mean()) - beta * float(bb.mean())) * 252 if beta is not None else None
    )

    def beta_cls() -> str:
        if beta is None:
            return ""
        return _sign_cls(beta - 1.0)

    cards = [
        {"label": "基准名称 (Benchmark)", "value": label, "cls": ""},
        {
            "label": "累计超额收益 (Total Excess)",
            "value": f"{total_excess * 100:.2f}%",
            "cls": _sign_cls(total_excess),
        },
        {
            "label": "年化超额收益 (Annual Excess)",
            "value": f"{annual_excess * 100:.2f}%",
            "cls": _sign_cls(annual_excess),
        },
        {
            "label": "跟踪误差 (Tracking Error)",
            "value": f"{tracking_error * 100:.2f}%",
            "cls": "",
        },
        {
            "label": "信息比率 (Information Ratio)",
            "value": "N/A" if info_ratio is None else f"{info_ratio:.4f}",
            "cls": _sign_cls(info_ratio),
        },
        {
            "label": "Beta",
            "value": "N/A" if beta is None else f"{beta:.4f}",
            "cls": beta_cls(),
        },
        {
            "label": "Alpha (Annual)",
            "value": "N/A" if alpha is None else f"{alpha * 100:.2f}%",
            "cls": _sign_cls(alpha),
        },
    ]

    cum_s = (1 + s).cumprod() - 1.0
    cum_b = (1 + bb).cumprod() - 1.0
    cum_e = (1 + s).cumprod() / (1 + bb).cumprod() - 1.0
    return {
        "available": True,
        "reason": "",
        "cards": cards,
        "strategy": _series_tokens(cum_s),
        "benchmark": _series_tokens(cum_b),
        "excess": _series_tokens(cum_e),
    }


# ---------------------------------------------------------------------------
# trade analysis: pnl distribution / pnl vs duration
# ---------------------------------------------------------------------------


def build_trades_distribution(trades_df: Any, bins: int = 50) -> Dict[str, Any]:
    """Histogram of per-trade gross PnL (counts).

    :param trades_df: ``result.trades_df``-like frame with a ``pnl`` column.
    :param bins: Number of histogram bins.
    :return: Dict with ``bins`` list; empty when no trades.
    """
    if trades_df is None or len(trades_df) == 0 or "pnl" not in trades_df.columns:
        return {"bins": []}
    import numpy as np

    values = pd.to_numeric(trades_df["pnl"], errors="coerce").dropna().to_numpy()
    if len(values) < 2:
        return {"bins": []}
    counts, edges = np.histogram(values, bins=min(bins, max(10, len(values))))
    bin_list = [
        {"x0": float(edges[i]), "x1": float(edges[i + 1]), "y": int(counts[i])}
        for i in range(len(counts))
    ]
    return {"bins": bin_list}


def build_pnl_vs_duration(trades_df: Any) -> Dict[str, Any]:
    """Scatter points of trade PnL against holding duration.

    Duration unit auto-scales on the *average* duration (mirroring the
    original plotly chart): avg < 1 hour -> minutes, < 1 day -> hours,
    otherwise days. Each point carries the full trade record so the page
    can show a rich hover card and hot-switch the trade review on click.

    :param trades_df: ``result.trades_df``-like frame.
    :return: Dict with ``unit`` and ``points`` (``x``/``y``/``symbol`` plus
        side/entry/exit/prices/quantity/return_pct/net_pnl/duration_bars).
    """
    empty: Dict[str, Any] = {"unit": "天", "points": []}
    if trades_df is None or len(trades_df) == 0:
        return empty
    df = trades_df
    if "duration" in df.columns:
        durations = pd.to_timedelta(df["duration"], errors="coerce")
    elif {"entry_time", "exit_time"} <= set(df.columns):
        durations = pd.to_datetime(df["exit_time"]) - pd.to_datetime(df["entry_time"])
    else:
        return empty
    pnl = pd.to_numeric(df.get("pnl"), errors="coerce")
    valid = durations.notna() & pnl.notna()
    if not bool(valid.any()):
        return empty
    df = df.loc[valid]
    durations = durations[valid]
    pnl = pnl[valid]

    avg_d = durations.mean()
    if avg_d < pd.Timedelta(hours=1):
        scale, unit = pd.Timedelta(minutes=1), "分钟"
    elif avg_d < pd.Timedelta(days=1):
        scale, unit = pd.Timedelta(hours=1), "小时"
    else:
        scale, unit = pd.Timedelta(days=1), "天"
    x = durations / scale

    def _ts_label(value: Any) -> Optional[str]:
        if value is None or pd.isna(value):
            return None
        return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M")

    points = []
    for idx, (xv, yv) in enumerate(zip(x, pnl)):
        row = df.iloc[idx]
        side = str(row.get("side", "long")).lower()
        entry_ts = row.get("entry_time")
        exit_ts = row.get("exit_time")
        points.append(
            {
                "x": float(xv),
                "y": float(yv),
                "symbol": str(row.get("symbol", "")),
                "side": side,
                "entry_label": _ts_label(entry_ts),
                "exit_label": _ts_label(exit_ts),
                "entry_price": _num(row.get("entry_price")),
                "exit_price": _num(row.get("exit_price")),
                "quantity": _num(row.get("quantity")),
                "return_pct": _num(row.get("return_pct")),
                "pnl": _num(row.get("pnl")),
                "net_pnl": _num(row.get("net_pnl")),
                "duration_bars": _num(row.get("duration_bars")),
                "label": (
                    f"{row.get('symbol', '')} · 持仓 {float(xv):.1f}{unit}"
                    f" · 盈亏 {float(yv):,.2f}"
                ),
            }
        )
    return {"unit": unit, "points": points}


# ---------------------------------------------------------------------------
# attribution / capacity / ownership aggregation (HTML)
# ---------------------------------------------------------------------------


def _overview_card(label: str, value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return (
        '<div class="metric"><div class="label">'
        + _html.escape(label)
        + '</div><div class="value">'
        + _html.escape(value)
        + "</div></div>"
    )


def _call_result_df(
    result: Any, attr_name: str, *args: Any, **kwargs: Any
) -> pd.DataFrame:
    """Call a result DataFrame method/property defensively."""
    attr = getattr(result, attr_name, None)
    if attr is None:
        return pd.DataFrame()
    try:
        df = attr(*args, **kwargs) if callable(attr) else attr
    except Exception:
        return pd.DataFrame()
    if df is None:
        return pd.DataFrame()
    return df


def build_analysis_overview(result: Any, compact: bool) -> str:
    """Build the attribution & capacity overview card grid (up to 10 cards).

    :param result: ``BacktestResult``-like object.
    :param compact: Compact K/M/B amounts switch.
    :return: HTML fragment (grid of metric cards) or empty-state div.
    """
    cards: List[str] = []

    exposure = _call_result_df(result, "exposure_df", freq="D")
    if not exposure.empty:
        net = _num(
            exposure.get("net_exposure_pct", pd.Series(dtype=float)).iloc[-1]
            if "net_exposure_pct" in exposure
            else None
        )
        gross = _num(
            exposure.get("gross_exposure_pct", pd.Series(dtype=float)).iloc[-1]
            if "gross_exposure_pct" in exposure
            else None
        )
        lev = _num(exposure["leverage"].max() if "leverage" in exposure else None)
        for label, value in (
            ("最新净暴露比 (%)", _fmt_pct100(net)),
            ("最新总暴露比 (%)", _fmt_pct100(gross)),
            ("最大杠杆 (Max Leverage)", _fmt_num(lev, 4)),
        ):
            card = _overview_card(label, value)
            if card:
                cards.append(card)

    capacity = _call_result_df(result, "capacity_df", freq="D")
    if not capacity.empty:
        total_orders = _num(
            capacity["order_count"].sum() if "order_count" in capacity else None
        )
        filled_value = _num(
            capacity["filled_value"].sum() if "filled_value" in capacity else None
        )
        fill_rate = _num(
            capacity["fill_rate_qty"].mean() if "fill_rate_qty" in capacity else None
        )
        turnover = _num(capacity["turnover"].mean() if "turnover" in capacity else None)
        for label, value in (
            ("总订单数 (Orders)", _fmt_int(total_orders)),
            (
                "总成交额 (Filled Value)",
                None
                if filled_value is None
                else format_currency(filled_value, compact=compact),
            ),
            ("平均成交率 (Fill Rate)", _fmt_pct100(fill_rate)),
            ("平均换手率 (Turnover)", _fmt_pct100(turnover)),
        ):
            card = _overview_card(label, value)
            if card:
                cards.append(card)

    attribution = _call_result_df(result, "attribution_df", by="symbol")
    if not attribution.empty:
        total_pnl = _num(
            attribution["total_pnl"].sum() if "total_pnl" in attribution else None
        )
        total_comm = _num(
            attribution["total_commission"].sum()
            if "total_commission" in attribution
            else None
        )
        trade_count = _num(
            attribution["trade_count"].sum() if "trade_count" in attribution else None
        )
        for label, value in (
            (
                "归因总盈亏 (Total PnL)",
                None
                if total_pnl is None
                else format_currency(total_pnl, compact=compact),
            ),
            (
                "归因总手续费 (Total Commission)",
                None
                if total_comm is None
                else format_currency(total_comm, compact=compact),
            ),
            ("归因交易次数 (Trades)", _fmt_int(trade_count)),
        ):
            card = _overview_card(label, value)
            if card:
                cards.append(card)

    if not cards:
        return '<div class="hint">暂无归因与容量摘要数据</div>'
    return '<div class="metrics-grid">' + "".join(cards) + "</div>"


def build_analysis_tables(result: Any, compact: bool) -> Dict[str, str]:
    """Build the attribution/capacity/ownership detail tables (HTML).

    :param result: ``BacktestResult``-like object.
    :param compact: Compact K/M/B amounts switch.
    :return: Dict of HTML fragments keyed by section name.
    """
    out: Dict[str, str] = {}

    exposure = _call_result_df(result, "exposure_df", freq="D")
    if not exposure.empty:
        row = {}
        if "net_exposure_pct" in exposure:
            row["最新净暴露比 (%)"] = [float(exposure["net_exposure_pct"].iloc[-1])]
        if "gross_exposure_pct" in exposure:
            row["最新总暴露比 (%)"] = [float(exposure["gross_exposure_pct"].iloc[-1])]
        if "leverage" in exposure:
            row["最大杠杆 (Max Leverage)"] = [float(exposure["leverage"].max())]
        if row:
            df = pd.DataFrame(row)
            pct_cols = [c for c in df.columns if "(%)" in c and "杠杆" not in c]
            out["exposure"] = format_table(
                df, max_rows=1, pct_columns=pct_cols, compact=compact
            )

    capacity = _call_result_df(result, "capacity_df", freq="D")
    if not capacity.empty:
        row = {}
        if "order_count" in capacity:
            row["总订单数 (Orders)"] = [float(capacity["order_count"].sum())]
        if "filled_value" in capacity:
            row["总成交额 (Filled Value)"] = [float(capacity["filled_value"].sum())]
        if "fill_rate_qty" in capacity:
            row["平均成交率 (Fill Rate)"] = [float(capacity["fill_rate_qty"].mean())]
        if "turnover" in capacity:
            row["平均换手率 (Turnover)"] = [float(capacity["turnover"].mean())]
        if row:
            df = pd.DataFrame(row)
            out["capacity"] = format_table(
                df,
                max_rows=1,
                pct_columns={"平均成交率 (Fill Rate)", "平均换手率 (Turnover)"},
                currency_columns={"总成交额 (Filled Value)"},
                compact=compact,
            )

    attribution = _call_result_df(result, "attribution_df", by="symbol")
    if not attribution.empty:
        view = rename_columns(
            attribution,
            {
                "group": "分组 (Group)",
                "symbol": "分组 (Group)",
                "trade_count": "交易次数 (Trade Count)",
                "total_pnl": "总盈亏 (Total PnL)",
                "contribution_pct": "贡献占比 (Contribution %)",
                "total_commission": "总手续费 (Total Commission)",
            },
        )
        keep = [
            c
            for c in (
                "分组 (Group)",
                "交易次数 (Trade Count)",
                "总盈亏 (Total PnL)",
                "贡献占比 (Contribution %)",
                "总手续费 (Total Commission)",
            )
            if c in view.columns
        ]
        view = view[keep]
        if "总盈亏 (Total PnL)" in view.columns:
            view = view.sort_values("总盈亏 (Total PnL)", ascending=False)
        out["attribution"] = format_table(
            view,
            max_rows=10,
            pct_columns={"贡献占比 (Contribution %)"},
            currency_columns={"总盈亏 (Total PnL)", "总手续费 (Total Commission)"},
            compact=compact,
        )

    orders = _call_result_df(result, "orders_by_strategy")
    if not orders.empty:
        view = rename_columns(
            orders,
            {
                "owner_strategy_id": "策略ID (Strategy ID)",
                "order_count": "订单数 (Orders)",
                "filled_order_count": "已成交订单数 (Filled)",
                "filled_quantity": "成交数量 (Filled Qty)",
                "filled_value": "成交额 (Filled Value)",
                "fill_rate_qty": "数量成交率 (Fill Rate %)",
            },
        )
        keep = [
            c
            for c in (
                "策略ID (Strategy ID)",
                "订单数 (Orders)",
                "已成交订单数 (Filled)",
                "成交数量 (Filled Qty)",
                "成交额 (Filled Value)",
                "数量成交率 (Fill Rate %)",
            )
            if c in view.columns
        ]
        out["orders"] = format_table(
            view[keep],
            max_rows=20,
            pct_columns={"数量成交率 (Fill Rate %)"},
            currency_columns={"成交额 (Filled Value)"},
            compact=compact,
        )

    executions = _call_result_df(result, "executions_by_strategy")
    if not executions.empty:
        view = rename_columns(
            executions,
            {
                "owner_strategy_id": "策略ID (Strategy ID)",
                "execution_count": "成交笔数 (Executions)",
                "total_quantity": "总成交数量 (Total Qty)",
                "total_notional": "总成交额 (Total Value)",
                "total_value": "总成交额 (Total Value)",
                "total_commission": "总手续费 (Total Commission)",
                "avg_fill_price": "平均成交价 (Avg Price)",
                "avg_price": "平均成交价 (Avg Price)",
            },
        )
        keep = [
            c
            for c in (
                "策略ID (Strategy ID)",
                "成交笔数 (Executions)",
                "总成交数量 (Total Qty)",
                "总成交额 (Total Value)",
                "总手续费 (Total Commission)",
                "平均成交价 (Avg Price)",
            )
            if c in view.columns
        ]
        out["executions"] = format_table(
            view[keep],
            max_rows=20,
            currency_columns={"总成交额 (Total Value)", "总手续费 (Total Commission)"},
            compact=compact,
        )

    risk = _call_result_df(result, "risk_rejections_by_strategy")
    if not risk.empty:
        view = rename_columns(
            risk,
            {
                "owner_strategy_id": "策略ID (Strategy ID)",
                "risk_reject_count": "风险拒单总数 (Total)",
                "daily_loss_reject_count": "日损拒单数 (Daily Loss)",
                "drawdown_reject_count": "回撤拒单数 (Drawdown)",
                "reduce_only_reject_count": "仅平仓拒单数 (Reduce-Only)",
                "position_limit_reject_count": "持仓限制拒单数 (Position Limit)",
                "order_size_limit_reject_count": "订单量限制 (Order Size)",
                "order_value_limit_reject_count": "订单额限制 (Order Value)",
                "strategy_risk_budget_reject_count": "策略预算拒单 (Strategy Budget)",
                "portfolio_risk_budget_reject_count": "组合预算拒单 (Portfolio Budget)",
                "other_risk_reject_count": "其他拒单数 (Other)",
            },
        )
        out["risk"] = format_table(view, max_rows=20, compact=compact)

    liquidation = _call_result_df(result, "liquidation_audit_df")
    if not liquidation.empty:
        view = liquidation.copy()
        if "liquidation_order" in view.columns:
            view["liquidation_order"] = view["liquidation_order"].map(
                lambda v: {"short_first": "先平空头", "long_first": "先平多头"}.get(
                    str(v), str(v)
                )
            )
        if "liquidated_symbols" in view.columns:
            view["liquidated_symbols"] = view["liquidated_symbols"].map(
                lambda v: ", ".join(str(v).split(","))
            )
        view = rename_columns(
            view,
            {
                "timestamp": "时间戳 (Timestamp)",
                "date": "日期 (Date)",
                "daily_interest": "当日利息 (Daily Interest)",
                "liquidated_count": "强平标的数 (Count)",
                "liquidated_symbols": "强平标的 (Symbols)",
                "liquidation_order": "强平顺序 (Order)",
            },
        )
        keep = [
            c
            for c in (
                "时间戳 (Timestamp)",
                "日期 (Date)",
                "当日利息 (Daily Interest)",
                "强平标的数 (Count)",
                "强平标的 (Symbols)",
                "强平顺序 (Order)",
            )
            if c in view.columns
        ]
        out["liquidation"] = format_table(
            view[keep],
            max_rows=20,
            currency_columns={"当日利息 (Daily Interest)"},
            compact=compact,
        )
    return out


def build_daily_positions_section(
    result: Any,
    compact: bool,
    symbol_names: Optional[Dict[str, str]] = None,
) -> str:
    """Build the day-by-day holdings overview (HTML).

    ``positions_df`` only contains symbols with a non-zero position, so the
    daily index is joined against the equity curve to keep no-position days
    visible.

    :param result: ``BacktestResult``-like object.
    :param compact: Compact K/M/B amounts switch.
    :param symbol_names: Optional ``{symbol: display name}`` mapping; holding
        chips prefer the name and keep the code as the hover tooltip.
    :return: HTML fragment with summary cards and a daily holdings table.
    """
    positions = _call_result_df(result, "positions_df")
    required = {"date", "symbol"}
    if positions.empty or not required.issubset(positions.columns):
        return '<div class="hint">暂无持仓快照数据</div>'

    dates = pd.to_datetime(positions["date"], errors="coerce").dropna()
    if dates.empty:
        return '<div class="hint">暂无持仓快照数据</div>'

    view = positions.copy()
    view["date"] = pd.to_datetime(view["date"], errors="coerce")
    if view["date"].dt.tz is not None:
        view["date"] = view["date"].dt.tz_localize(None)
    view = view.dropna(subset=["date"])
    view["_day"] = view["date"].dt.normalize()
    view["_long"] = pd.to_numeric(view.get("long_shares"), errors="coerce").fillna(0.0)
    view["_short"] = pd.to_numeric(view.get("short_shares"), errors="coerce").fillna(
        0.0
    )
    view = view[(view["_long"].abs() > 0) | (view["_short"].abs() > 0)]

    market_value = pd.to_numeric(view.get("market_value"), errors="coerce")
    close = pd.to_numeric(view.get("close"), errors="coerce")
    fallback_mv = view["_long"] * close - view["_short"] * close
    view["_market_value"] = market_value.fillna(fallback_mv)
    view["_gross"] = view["_market_value"].abs()
    view["_equity"] = pd.to_numeric(view.get("equity"), errors="coerce")

    # Snapshot feeds can repeat a symbol within a day in intraday results;
    # the overview is daily, so the last snapshot is the end-of-day state.
    view = view.sort_values(["_day", "date", "symbol"]).drop_duplicates(
        ["_day", "symbol"], keep="last"
    )

    daily = view.groupby("_day", sort=True).agg(
        count=("symbol", "size"),
        net_value=("_market_value", "sum"),
        gross_value=("_gross", "sum"),
        equity=("_equity", "max"),
    )

    # ``resolve_equity_series`` fills daily calendar gaps for charts; the
    # holdings overview should follow realized backtest days only.
    equity = resolve_equity_series(result, "raw")
    if not equity.empty:
        daily_equity = equity.copy()
        daily_equity.index = pd.to_datetime(daily_equity.index).normalize()
        daily_equity = daily_equity[~daily_equity.index.duplicated(keep="last")]
        daily["equity"] = daily["equity"].fillna(daily_equity)
        daily = daily.reindex(daily.index.union(daily_equity.index)).sort_index()
    daily["count"] = daily["count"].fillna(0).astype(int)
    if daily.empty:
        return '<div class="hint">暂无持仓快照数据</div>'

    position_groups = {
        day: group.sort_values("_gross", ascending=False)
        for day, group in view.groupby("_day", sort=False)
    }

    def _fmt_wan(value: Any) -> str:
        n = _num(value)
        return "-" if n is None else f"{n / 10000:,.2f}万"

    avg_count = float(daily["count"].mean())
    max_count = float(daily["count"].max())
    flat_days = int((daily["count"] == 0).sum())
    exposures = []
    for row in daily.itertuples():
        if pd.isna(row.equity) or float(row.equity) <= 0:
            continue
        exposures.append(float(row.gross_value) / float(row.equity))
    avg_exposure = sum(exposures) / len(exposures) if exposures else None
    last_exposure = exposures[-1] if exposures else None

    cards = "".join(
        _overview_card(label, value)
        for label, value in (
            ("交易日 (Days)", _fmt_int(float(len(daily)))),
            ("平均持仓数 (Avg Positions)", _fmt_num(avg_count, 1)),
            ("最高持仓数 (Max Positions)", _fmt_int(max_count)),
            ("空仓天数 (Flat Days)", _fmt_int(float(flat_days))),
            ("平均仓位 (Avg Exposure)", _fmt_ratio(avg_exposure)),
            ("最新仓位 (Latest Exposure)", _fmt_ratio(last_exposure)),
        )
    )

    rows: List[str] = []
    for row in daily.sort_index(ascending=False).itertuples():
        day = pd.Timestamp(row.Index)
        holdings = position_groups.get(day)
        chips = []
        if holdings is not None and not holdings.empty:
            for _, item in holdings.iterrows():
                long_qty = float(item["_long"])
                short_qty = float(item["_short"])
                quantity = long_qty if abs(long_qty) > 0 else abs(short_qty)
                side = "long" if abs(long_qty) > 0 else "short"
                side_label = "多" if side == "long" else "空"
                qty_label = "N/A" if quantity <= 0 else f"{quantity:,.0f}股"
                weight = ""
                if pd.notna(row.equity) and float(row.equity) > 0:
                    weight = f"{float(item['_gross']) / float(row.equity) * 100:.2f}%"
                symbol = str(item["symbol"])
                name = str((symbol_names or {}).get(symbol, "")).strip()
                label = _html.escape(name) if name else _html.escape(symbol)
                title_attr = f' title="{_html.escape(symbol)}"' if name else ""
                chips.append(
                    f'<span class="position-chip {side}"{title_attr}><b>{label}</b>'
                    f"<span>{side_label}</span><span>{qty_label}</span>"
                    f"<span>{weight}</span></span>"
                )
        holdings_html = (
            '<div class="position-list">' + "".join(chips) + "</div>"
            if chips
            else '<span class="hint">空仓</span>'
        )
        gross = _num(row.gross_value)
        net = _num(row.net_value)
        equity_value = _num(row.equity)
        exposure = (
            gross / equity_value
            if gross is not None and equity_value is not None and equity_value > 0
            else None
        )
        rows.append(
            "<tr>"
            f"<td>{_date_str(day)}</td>"
            f"<td>{len(chips)}</td>"
            f'<td class="{_sign_cls(net)}">{_fmt_wan(net)}</td>'
            f"<td>{_fmt_wan(gross)}</td>"
            f'<td class="{_sign_cls(exposure)}">{_fmt_ratio(exposure)}</td>'
            f"<td>{_fmt_wan(equity_value)}</td>"
            f"<td>{holdings_html}</td>"
            "</tr>"
        )

    return (
        '<div class="metrics-grid">'
        + cards
        + '</div><div class="position-table-wrap">'
        + '<table class="data-table position-table"><thead><tr>'
        "<th>日期</th><th>持仓数</th><th>净持仓市值</th>"
        "<th>总持仓市值(万)</th><th>仓位</th><th>总资产(万)</th><th>持仓明细</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


# ---------------------------------------------------------------------------
# risk rejection / liquidation chart sections
# ---------------------------------------------------------------------------

_RISK_REASON_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("daily_loss_reject_count", "Daily Loss"),
    ("drawdown_reject_count", "Drawdown"),
    ("reduce_only_reject_count", "Reduce-Only"),
    ("position_limit_reject_count", "Position Limit"),
    ("order_size_limit_reject_count", "Order Size Limit"),
    ("order_value_limit_reject_count", "Order Value Limit"),
    ("strategy_risk_budget_reject_count", "Strategy Risk Budget"),
    ("portfolio_risk_budget_reject_count", "Portfolio Risk Budget"),
    ("other_risk_reject_count", "Other"),
)

_REASON_PALETTE = (
    "#5470c6",
    "#91cc75",
    "#fac858",
    "#ee6666",
    "#73c0de",
    "#3ba272",
    "#fc8452",
    "#9a60b4",
    "#ea7ccc",
)


def _html_ratio_bars(rows: List[Tuple[str, float, float]]) -> str:
    """Render horizontal ratio bars (label, ratio, count) as HTML."""
    parts = ['<div class="hbars">']
    for label, ratio, count in rows:
        pct = f"{ratio * 100:.1f}%"
        parts.append(
            '<div class="hbar-row">'
            f'<span class="hbar-label">{_html.escape(label)}</span>'
            '<span class="hbar-track">'
            f'<span class="hbar-fill" style="width:{ratio * 100:.2f}%"></span>'
            "</span>"
            f'<span class="hbar-value">{pct} ({count:.0f})</span>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _html_stacked_bars(
    rows: List[Tuple[str, List[Tuple[str, float]]]], palette: Tuple[str, ...]
) -> str:
    """Render 100% stacked horizontal bars with a legend as HTML."""
    legend_items: List[str] = []
    seen: Dict[str, str] = {}
    for _, segments in rows:
        for name, _ in segments:
            if name not in seen:
                seen[name] = palette[len(seen) % len(palette)]
    for name, color in seen.items():
        legend_items.append(
            f'<span class="legend-item">'
            f'<span class="legend-swatch" style="background:{color}"></span>'
            f"{_html.escape(name)}</span>"
        )
    parts = ['<div class="legend">', "".join(legend_items), "</div>"]
    parts.append('<div class="hbars">')
    for label, segments in rows:
        segs_html = []
        for name, ratio in segments:
            color = seen[name]
            segs_html.append(
                f'<span class="hbar-seg" title="{_html.escape(name)} '
                f'{ratio * 100:.1f}%" style="width:{ratio * 100:.2f}%;'
                f'background:{color}"></span>'
            )
        parts.append(
            '<div class="hbar-row">'
            f'<span class="hbar-label">{_html.escape(label)}</span>'
            f'<span class="hbar-track">{"".join(segs_html)}</span>'
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def build_risk_sections(result: Any, compact: bool) -> Dict[str, Any]:
    """Build all risk-rejection/liquidation chart payloads and HTML blocks.

    Mirrors the plotly report's conditional risk block: strategy-level reject
    ratio bars, per-strategy reason stacked bars, daily reject trend, daily
    reason stacked-area trend, per-strategy trend, liquidation count trend,
    daily interest bars and the top-8 reject reason table.

    :param result: ``BacktestResult``-like object.
    :param compact: Compact K/M/B amounts switch.
    :return: Dict consumed by the template/JS renderers.
    """
    out: Dict[str, Any] = {
        "emptyReason": "",
        "ratioBarsHtml": "",
        "reasonStackHtml": "",
        "rejectTrend": [],
        "reasonTrend": {"labels": [], "colors": [], "series": []},
        "strategyTrend": {"series": []},
        "liquidationCount": [],
        "interest": [],
        "topReasonsHtml": "",
    }

    top_reasons = _call_result_df(result, "top_reject_reason_types", top_n=8)
    if not top_reasons.empty:
        view = rename_columns(
            top_reasons,
            {
                "reject_reason_type": "拒单类型 (Reject Type)",
                "sample_reject_reason": "示例详情 (Sample Detail)",
                "count": "拒单数 (Count)",
                "ratio": "占比 (Ratio)",
            },
        )
        out["topReasonsHtml"] = format_table(
            view, max_rows=8, pct_columns={"占比 (Ratio)"}, compact=compact
        )

    risk_df = _call_result_df(result, "risk_rejections_by_strategy")
    total_rejects = 0.0
    if risk_df.empty or "risk_reject_count" not in risk_df.columns:
        out["emptyReason"] = "本次回测未产生策略级风控拒单统计数据。"
    else:
        base = risk_df.copy()
        if "owner_strategy_id" not in base.columns:
            base["owner_strategy_id"] = "_default"
        base["owner_strategy_id"] = (
            base["owner_strategy_id"].fillna("_default").astype(str)
        )
        counts = pd.to_numeric(base["risk_reject_count"], errors="coerce").fillna(0.0)
        total_rejects = float(counts.sum())
        if total_rejects <= 0:
            out["emptyReason"] = "本次回测风控拒单总数为 0，未触发拒单。"
        else:
            rows = sorted(
                zip(base["owner_strategy_id"], counts / total_rejects, counts),
                key=lambda r: r[1],
                reverse=True,
            )
            out["ratioBarsHtml"] = _html_ratio_bars(
                [(str(lbl), float(ratio), float(cnt)) for lbl, ratio, cnt in rows]
            )
            available = [
                (col, label)
                for col, label in _RISK_REASON_COLUMNS
                if col in base.columns
            ]
            if available:
                stack_rows: List[Tuple[str, List[Tuple[str, float]]]] = []
                for _, row in base.iterrows():
                    values = [
                        (label, _num(row[col]) or 0.0) for col, label in available
                    ]
                    row_total = sum(v for _, v in values)
                    if row_total <= 0:
                        continue
                    stack_rows.append(
                        (
                            str(row["owner_strategy_id"]),
                            [(label, v / row_total) for label, v in values if v > 0],
                        )
                    )
                if stack_rows:
                    out["reasonStackHtml"] = _html_stacked_bars(
                        stack_rows, _REASON_PALETTE
                    )

    trend = _call_result_df(result, "risk_rejections_trend", freq="D")
    if not trend.empty and "date" in trend.columns:
        trend = trend.copy()
        trend["date"] = pd.to_datetime(trend["date"], errors="coerce")
        trend = trend.dropna(subset=["date"]).sort_values("date")
        if not trend.empty and "risk_reject_count" in trend.columns:
            counts = pd.to_numeric(trend["risk_reject_count"], errors="coerce")
            out["rejectTrend"] = [
                {"time": _date_str(d), "value": float(v)}
                for d, v in zip(trend["date"], counts.fillna(0.0))
            ]
            reason_cols = [
                (col, label)
                for col, label in _RISK_REASON_COLUMNS
                if col in trend.columns
            ]
            if reason_cols:
                series_list = []
                for idx_color, (col, label) in enumerate(reason_cols):
                    values = pd.to_numeric(trend[col], errors="coerce").fillna(0.0)
                    if float(values.sum()) <= 0:
                        continue
                    series_list.append(
                        {
                            "name": label,
                            "color": _REASON_PALETTE[idx_color % len(_REASON_PALETTE)],
                            "data": [
                                {"time": _date_str(d), "value": float(v)}
                                for d, v in zip(trend["date"], values)
                            ],
                        }
                    )
                if series_list:
                    out["reasonTrend"] = {"series": series_list}

    by_strategy = _call_result_df(result, "risk_rejections_trend_by_strategy", freq="D")
    if not by_strategy.empty and "date" in by_strategy.columns:
        bs = by_strategy.copy()
        bs["date"] = pd.to_datetime(bs["date"], errors="coerce")
        bs = bs.dropna(subset=["date"]).sort_values("date")
        value_col = "risk_reject_count" if "risk_reject_count" in bs.columns else None
        group_col = "owner_strategy_id" if "owner_strategy_id" in bs.columns else None
        if value_col and group_col:
            series_list = []
            for idx_color, (strategy, grp) in enumerate(bs.groupby(group_col)):
                values = pd.to_numeric(grp[value_col], errors="coerce").fillna(0.0)
                series_list.append(
                    {
                        "name": str(strategy),
                        "color": _REASON_PALETTE[idx_color % len(_REASON_PALETTE)],
                        "data": [
                            {"time": _date_str(d), "value": float(v)}
                            for d, v in zip(grp["date"], values)
                        ],
                    }
                )
            if series_list:
                out["strategyTrend"] = {"series": series_list}

    liquidation = _call_result_df(result, "liquidation_audit_df")
    if not liquidation.empty:
        liq = liquidation.copy()
        date_col = "date" if "date" in liq.columns else None
        if date_col is None and "timestamp" in liq.columns:
            ts = pd.to_datetime(liq["timestamp"], errors="coerce")
            if ts.notna().any():
                liq["date"] = ts.dt.strftime("%Y-%m-%d")
                date_col = "date"
        if date_col:
            liq[date_col] = pd.to_datetime(liq[date_col], errors="coerce")
            liq = liq.dropna(subset=[date_col])
            if "liquidated_count" in liq.columns:
                counts = (
                    pd.to_numeric(liq["liquidated_count"], errors="coerce")
                    .fillna(0.0)
                    .groupby(liq[date_col])
                    .sum()
                )
                if float(counts.sum()) > 0:
                    out["liquidationCount"] = [
                        {"time": _date_str(d), "value": float(v)}
                        for d, v in counts.items()
                    ]
            if "daily_interest" in liq.columns:
                interest = (
                    pd.to_numeric(liq["daily_interest"], errors="coerce")
                    .fillna(0.0)
                    .groupby(liq[date_col])
                    .sum()
                )
                interest = interest[interest > 0]
                if not interest.empty:
                    out["interest"] = [
                        {"time": _date_str(d), "value": float(v)}
                        for d, v in interest.items()
                    ]

    if not out["emptyReason"] and not (
        out["ratioBarsHtml"]
        or out["rejectTrend"]
        or out["liquidationCount"]
        or out["interest"]
        or out["topReasonsHtml"]
    ):
        out["emptyReason"] = "本次回测未形成可绘制的风控拒单图表。"
    return out


# ---------------------------------------------------------------------------
# custom indicator preview section
# ---------------------------------------------------------------------------


def build_indicator_section(
    result: Any,
    name: Optional[str],
    symbol: Optional[str],
    include_warmup: bool,
    compact: bool,
) -> Dict[str, Any]:
    """Build the custom-indicator preview section (cards, chart panes, defs).

    :param result: ``BacktestResult``-like object exposing ``indicator_df``
        and ``indicator_definitions``.
    :param name: Optional indicator key filter.
    :param symbol: Optional symbol filter.
    :param include_warmup: Keep warmup points when true.
    :param compact: Compact K/M/B amounts switch.
    :return: Dict with ``cardsHtml``/``panes``/``defsHtml``/``empty``.
    """
    out: Dict[str, Any] = {
        "cardsHtml": "",
        "panes": [],
        "defsHtml": "",
        "empty": True,
        "filterHint": "",
    }
    indicator_df = _call_result_df(result, "indicator_df", name=name, symbol=symbol)
    if not include_warmup and not indicator_df.empty and "warmup" in indicator_df:
        indicator_df = indicator_df.loc[~indicator_df["warmup"]]

    definitions = getattr(result, "indicator_definitions", None)
    if definitions is None:
        definitions = pd.DataFrame()
    else:
        definitions = definitions.copy()
    if name is not None and not definitions.empty and "indicator_key" in definitions:
        definitions = definitions.loc[definitions["indicator_key"] == str(name)]

    symbol_count = (
        int(indicator_df["symbol"].dropna().astype(str).nunique())
        if not indicator_df.empty and "symbol" in indicator_df.columns
        else 0
    )
    cards = []
    for label, value in (
        ("指标定义数 (Indicator Definitions)", len(definitions)),
        ("指标点位数 (Indicator Points)", len(indicator_df)),
        ("标的数 (Symbols)", symbol_count),
    ):
        card = _overview_card(label, f"{value:,d}")
        if card:
            cards.append(card)
    out["cardsHtml"] = '<div class="metrics-grid">' + "".join(cards) + "</div>"

    filter_parts = []
    if name is not None:
        filter_parts.append(f"指标={name}")
    if symbol is not None:
        filter_parts.append(f"标的={symbol}")
    if not include_warmup:
        filter_parts.append("已排除预热点")
    out["filterHint"] = " | ".join(filter_parts)

    if not definitions.empty:
        view = rename_columns(
            definitions,
            {
                "indicator_key": "指标键 (Indicator Key)",
                "display_name": "展示名 (Display Name)",
                "pane": "面板 (Pane)",
                "render_type": "绘制方式 (Render Type)",
                "unit": "单位 (Unit)",
                "precision": "精度 (Precision)",
                "color": "颜色 (Color)",
            },
        )
        keep = [
            c
            for c in (
                "指标键 (Indicator Key)",
                "展示名 (Display Name)",
                "面板 (Pane)",
                "绘制方式 (Render Type)",
                "单位 (Unit)",
                "精度 (Precision)",
                "颜色 (Color)",
            )
            if c in view.columns
        ]
        out["defsHtml"] = format_table(view[keep], max_rows=20, compact=compact)

    if indicator_df.empty:
        return out

    meta: Dict[str, Dict[str, Any]] = {}
    if not definitions.empty and "indicator_key" in definitions.columns:
        for _, row in definitions.iterrows():
            meta[str(row["indicator_key"])] = {
                "pane": row.get("pane", 0),
                "render_type": str(row.get("render_type", "line")),
                "display_name": str(row.get("display_name", "")),
                "color": row.get("color", None),
            }

    df = indicator_df.copy()
    if "datetime" in df.columns:
        times = pd.to_datetime(df["datetime"], errors="coerce")
    elif "timestamp" in df.columns:
        times = pd.to_datetime(df["timestamp"], errors="coerce")
    elif "timestamp_ms" in df.columns:
        times = pd.to_datetime(df["timestamp_ms"], unit="ms", errors="coerce")
    else:
        return out
    if getattr(times.dt, "tz", None) is not None:
        times = times.dt.tz_localize(None)
    df["_time"] = times
    df = df.dropna(subset=["_time"])
    if df.empty:
        return out
    intraday = bool((df["_time"].dt.normalize() != df["_time"]).any())
    df["_token"] = df["_time"].map(
        lambda t: int(t.value // 10**9) if intraday else _date_str(t)
    )
    df["_value"] = pd.to_numeric(df.get("value"), errors="coerce")
    df = df.dropna(subset=["_value"])

    group_cols = [
        c for c in ("indicator_key", "owner_strategy_id", "symbol") if c in df.columns
    ]
    if not group_cols:
        return out
    grouped = df.sort_values("_time").groupby(group_cols, dropna=False)
    palette = _REASON_PALETTE
    panes: Dict[int, List[Dict[str, Any]]] = {}
    for idx, (key, grp) in enumerate(grouped):
        key_tuple = key if isinstance(key, tuple) else (key,)
        parts = dict(zip(group_cols, key_tuple))
        indicator_key = str(parts.get("indicator_key", ""))
        info = meta.get(indicator_key, {})
        pane = info.get("pane", 0)
        try:
            pane = int(pane)
        except (TypeError, ValueError):
            pane = 0
        render_type = info.get("render_type", "line")
        display = info.get("display_name") or indicator_key
        label = display
        if parts.get("symbol") not in (None, ""):
            label += f" · {parts.get('symbol')}"
        color = info.get("color") or palette[idx % len(palette)]
        series = {
            "name": label,
            "type": render_type,
            "color": str(color) if color else palette[idx % len(palette)],
            "data": [
                {"time": token, "value": float(v)}
                for token, v in zip(grp["_token"], grp["_value"])
            ],
        }
        panes.setdefault(pane, []).append(series)

    out["panes"] = [{"pane": pane, "series": panes[pane]} for pane in sorted(panes)]
    out["empty"] = False
    return out
