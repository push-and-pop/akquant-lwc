"""Static HTML report generation based on TradingView Lightweight Charts.

Produces a single self-contained HTML file (the Lightweight Charts bundle is
vendored into the package, no CDN required) that is a feature-parity
replacement of AKQuant's plotly-based report:

- summary box and the full key-metric card grid,
- equity curve with a synchronized drawdown pane and a monthly heatmap,
- return analysis (yearly bars, returns distribution, rolling metrics),
- benchmark comparison (cards + cumulative curves),
- trade analysis (PnL distribution, PnL vs holding duration),
- a trade-review section (candlesticks + volume + buy/sell markers) where
  the reviewed symbol can be hot-switched from the page,
- attribution & capacity tables, strategy ownership aggregation,
- risk rejection / liquidation chart blocks,
- optional custom-indicator preview panes.

Typical usage::

    from akquant_lwc import plot_report

    plot_report(result, market_data={"600000": df1, "600004": df2},
                filename="report.html")
"""

from __future__ import annotations

import html as _html
import json
import warnings
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from ._app_js import APP_JS
from ._normalize import (
    _time_token,
    build_symbol_payload,
    coerce_market_data,
    extract_trades_by_symbol,
    pick_initial_symbol,
)
from ._sections import (
    _series_tokens,
    build_analysis_overview,
    build_analysis_tables,
    build_benchmark_sections,
    build_daily_positions_section,
    build_indicator_section,
    build_metric_cards,
    build_monthly_heatmap_html,
    build_pnl_vs_duration,
    build_returns_distribution,
    build_risk_sections,
    build_rolling_metrics,
    build_summary,
    build_trades_distribution,
    build_yearly_returns,
    daily_returns_from_equity,
    resolve_equity_series,
)
from ._template import HTML_TEMPLATE

_ASSETS_DIR = Path(__file__).parent / "assets"
_LWC_BUNDLE = "lightweight-charts.standalone.production.js"


def load_standalone_js() -> str:
    """Read the vendored Lightweight Charts standalone bundle.

    :return: JavaScript source of the bundle.
    :raises FileNotFoundError: If the bundle is missing from the package.
    """
    path = _ASSETS_DIR / _LWC_BUNDLE
    if not path.exists():
        raise FileNotFoundError(
            "Lightweight Charts bundle not found at %s; the akquant_lwc "
            "package data may be incomplete." % path
        )
    return path.read_text(encoding="utf-8")


def _curve_tokens(
    equity: pd.Series, curve_freq: str
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Convert an equity series into (equity, drawdown) chart token lists."""
    if equity.empty:
        return [], []
    drawdown = equity / equity.cummax() - 1.0
    if curve_freq == "raw":
        intraday = bool((equity.index.normalize() != equity.index).any())
        eq = [
            {"time": _time_token(t, intraday), "value": float(v)}
            for t, v in equity.items()
        ]
        dd = [
            {"time": _time_token(t, intraday), "value": float(v)}
            for t, v in drawdown.items()
        ]
        return eq, dd
    return _series_tokens(equity), _series_tokens(drawdown)


def build_app_data(
    result: Any,
    market_data: Optional[Union[pd.DataFrame, Dict[str, pd.DataFrame]]] = None,
    symbols: Optional[List[str]] = None,
    title: str = "",
    server_mode: bool = False,
    plot_symbol: Optional[str] = None,
    extra_symbols: Optional[List[str]] = None,
    compact_currency: bool = True,
    include_trade_kline: bool = True,
    include_indicators: bool = False,
    indicator_name: Optional[str] = None,
    indicator_symbol: Optional[str] = None,
    indicator_include_warmup: bool = True,
    benchmark: Optional[Union[str, "pd.Series"]] = None,
    curve_freq: str = "D",
) -> Dict[str, Any]:
    """Build the JSON payload consumed by the browser application.

    :param result: ``BacktestResult``-like object.
    :param market_data: OHLCV data used for the trade-review chart. Accepts a
        ``{symbol: frame}`` dict, a single frame, or a long frame carrying a
        symbol column.
    :param symbols: Optional subset of symbols to embed in the page. Only
        meaningful in static mode; the server loads symbols on demand.
    :param title: Report title.
    :param server_mode: When true, the page fetches unknown symbols from the
        review server instead of failing.
    :param plot_symbol: Symbol displayed initially.
    :param extra_symbols: Extra codes listed in the page's autocomplete even
        when their data is not embedded (used by the server mode).
    :param compact_currency: Render amounts with compact K/M/B suffixes.
    :param include_trade_kline: Include the K-line trade-review section.
    :param include_indicators: Include the recorded-indicator preview section.
    :param indicator_name: Optional indicator key filter.
    :param indicator_symbol: Optional indicator symbol filter.
    :param indicator_include_warmup: Keep warmup points in indicator preview.
    :param benchmark: Benchmark daily returns series (or a label string).
    :param curve_freq: Equity curve frequency: ``"D"`` (daily last, default)
        or ``"raw"`` (original frequency).
    :return: JSON-serializable application payload.
    """
    trades_by_symbol = extract_trades_by_symbol(result)
    frames = coerce_market_data(market_data, list(trades_by_symbol))
    if symbols is not None:
        wanted = {str(s) for s in symbols}
        frames = {k: v for k, v in frames.items() if k in wanted}

    payloads: Dict[str, Any] = {}
    for symbol, frame in frames.items():
        try:
            payloads[symbol] = build_symbol_payload(
                symbol, frame, trades_by_symbol.get(symbol, [])
            )
        except ValueError as exc:
            warnings.warn("skipping symbol %r: %s" % (symbol, exc))

    equity_series = resolve_equity_series(result, curve_freq)
    daily_returns = daily_returns_from_equity(equity_series)
    equity, drawdown = _curve_tokens(equity_series, curve_freq)

    indicators: Dict[str, Any] = {"enabled": False}
    if include_indicators:
        indicators = build_indicator_section(
            result,
            name=indicator_name,
            symbol=indicator_symbol,
            include_warmup=indicator_include_warmup,
            compact=compact_currency,
        )
        indicators["enabled"] = True

    trades_df = getattr(result, "trades_df", None)
    if server_mode:
        # 服务模式：候选 = 已内嵌 ∪ 有交易 ∪ 服务端声明可解析（均可按需加载）
        symbol_list = sorted(
            set(payloads) | set(trades_by_symbol) | set(extra_symbols or [])
        )
    else:
        # 静态模式：只列出已内嵌行情的标的，未内嵌的选中必然报错
        symbol_list = sorted(payloads)
    return {
        "title": title,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "serverMode": server_mode,
        "summary": build_summary(result, equity_series),
        "metrics": build_metric_cards(result, compact_currency),
        "equity": equity,
        "drawdown": drawdown,
        "returns": _series_tokens(daily_returns),
        "monthlyHeatmapHtml": build_monthly_heatmap_html(daily_returns),
        "yearlyReturns": build_yearly_returns(daily_returns),
        "returnsDist": build_returns_distribution(daily_returns),
        "rolling": build_rolling_metrics(daily_returns),
        "benchmark": build_benchmark_sections(daily_returns, benchmark),
        "tradesDist": build_trades_distribution(trades_df),
        "pnlDuration": build_pnl_vs_duration(trades_df),
        "includeTradeKline": include_trade_kline,
        "analysisOverviewHtml": build_analysis_overview(result, compact_currency),
        "dailyPositionsHtml": build_daily_positions_section(result, compact_currency),
        "analysisTables": build_analysis_tables(result, compact_currency),
        "risk": build_risk_sections(result, compact_currency),
        "indicators": indicators,
        "payloads": payloads,
        "symbols": symbol_list,
        "initialSymbol": pick_initial_symbol(
            payloads, trades_by_symbol, preferred=plot_symbol
        ),
    }


def render_html(title: str, app_data: Dict[str, Any]) -> str:
    """Render the final self-contained HTML document.

    :param title: Report title (HTML-escaped during rendering).
    :param app_data: Payload from :func:`build_app_data`.
    :return: Complete HTML source.
    """
    app_json = json.dumps(app_data, ensure_ascii=False, separators=(",", ":"))
    # Guard against an accidental "</script>" terminating the data island.
    app_json = app_json.replace("<", "\\u003c")
    escaped_title = _html.escape(title)
    page = HTML_TEMPLATE.replace("__TITLE__", escaped_title)
    page = page.replace("__LWC_JS__", load_standalone_js(), 1)
    page = page.replace("__APP_JSON__", app_json, 1)
    page = page.replace("__APP_JS__", APP_JS, 1)
    return page


def plot_report(
    result: Any,
    market_data: Optional[Union[pd.DataFrame, Dict[str, pd.DataFrame]]] = None,
    title: str = "AKQuant 策略回测报告 (Lightweight Charts)",
    filename: str = "akquant_lwc_report.html",
    symbols: Optional[List[str]] = None,
    plot_symbol: Optional[str] = None,
    show: bool = False,
    compact_currency: bool = True,
    include_trade_kline: bool = True,
    include_indicators: bool = False,
    indicator_name: Optional[str] = None,
    indicator_symbol: Optional[str] = None,
    indicator_include_warmup: bool = True,
    benchmark: Optional[Union[str, "pd.Series"]] = None,
    curve_freq: str = "D",
    external_data: bool = False,
) -> str:
    """Generate a static single-file backtest report.

    Feature-parity replacement of AKQuant's plotly-based ``result.report()``,
    plus an interactive trade-review section where the reviewed symbol can be
    hot-switched inside the page.

    :param result: ``BacktestResult``-like object.
    :param market_data: OHLCV data for the trade-review chart; pass a
        ``{symbol: frame}`` dict to enable in-page hot switching between
        symbols without a server.
    :param title: Report title.
    :param filename: Output HTML path.
    :param symbols: Optional subset of symbols to embed.
    :param plot_symbol: Symbol displayed initially.
    :param show: Open the report in the default browser when done.
    :param compact_currency: Render amounts with compact K/M/B suffixes.
    :param include_trade_kline: Include the K-line trade-review section.
    :param include_indicators: Include the recorded-indicator preview section.
    :param indicator_name: Optional indicator key filter.
    :param indicator_symbol: Optional indicator symbol filter.
    :param indicator_include_warmup: Keep warmup points in indicator preview.
    :param benchmark: Benchmark daily returns series (or a label string).
    :param curve_freq: Equity curve frequency: ``"D"`` (daily last, default)
        or ``"raw"`` (original frequency).
    :param external_data: When true, symbol payloads are written to a single
        companion file ``<stem>.data.json`` next to the HTML instead of being
        embedded. The page then loads that file once via a user-triggered
        file picker (browser security requires one user gesture), after which
        hot-switching works for every included symbol. Keeps the HTML small
        for large universes.
    :return: Absolute path of the generated HTML file.
    """
    app_data = build_app_data(
        result,
        market_data=market_data,
        symbols=symbols,
        title=title,
        server_mode=False,
        plot_symbol=plot_symbol,
        compact_currency=compact_currency,
        include_trade_kline=include_trade_kline,
        include_indicators=include_indicators,
        indicator_name=indicator_name,
        indicator_symbol=indicator_symbol,
        indicator_include_warmup=indicator_include_warmup,
        benchmark=benchmark,
        curve_freq=curve_freq,
    )
    out = Path(filename).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if external_data and app_data["payloads"]:
        data_file = out.with_suffix(".data.json")
        companion = {
            "payloads": app_data["payloads"],
            "symbols": sorted(app_data["payloads"]),
        }
        data_file.write_text(
            json.dumps(companion, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        app_data["externalData"] = {"file": data_file.name}
        app_data["payloads"] = {}

    page = render_html(title, app_data)
    out.write_text(page, encoding="utf-8")
    if show:
        webbrowser.open(out.as_uri())
    return str(out)
