"""akquant-lwc 单元测试（合成桩对象）与可选真实数据端到端测试.

单元测试使用手工构造的 duck-typed 结果对象（合成测试夹具，仅用于验证
渲染/格式化逻辑，不作为真实行情数据）。端到端测试默认跳过，设置环境
变量 ``AKQUANT_LWC_E2E=1`` 并提供真实 CSV/akquant 环境后启用。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
import pytest

from akquant_lwc import build_app_data, plot_report, render_html


class _Metrics:
    """合成指标袋（测试夹具）."""

    total_return_pct = 12.34
    annualized_return = 0.061
    max_drawdown_pct = 8.5
    max_drawdown_value = 85000.0
    sharpe_ratio = 1.23
    sortino_ratio = 1.5
    calmar_ratio = 0.72
    volatility = 0.18
    win_rate = 55.5


class _TradeMetrics:
    """合成交易统计袋（测试夹具）."""

    total_closed_trades = 2
    profit_factor = 1.8
    avg_pnl = 500.0
    kelly_criterion = 0.21


class _StubResult:
    """合成回测结果（duck-typed 测试夹具）."""

    metrics = _Metrics()
    trade_metrics = _TradeMetrics()
    initial_cash = 1_000_000.0

    @property
    def equity_curve(self) -> pd.Series:
        idx = pd.date_range("2024-01-02", periods=160, freq="B")
        values = [1_000_000.0 * (1 + i / 1000) for i in range(160)]
        return pd.Series(values, index=idx)

    @property
    def trades_df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": ["AAA", "AAA"],
                "entry_time": pd.to_datetime(["2024-01-03", "2024-01-09"]),
                "exit_time": pd.to_datetime(["2024-01-05", "2024-01-11"]),
                "entry_price": [100.0, 101.0],
                "exit_price": [102.0, 99.0],
                "quantity": [100, 100],
                "side": ["long", "long"],
                "pnl": [2000.0, -2000.0],
                "net_pnl": [1990.0, -2010.0],
                "return_pct": [0.0199, -0.0201],
                "duration": [pd.Timedelta(days=2), pd.Timedelta(days=2)],
            }
        )


class _PositionsStubResult(_StubResult):
    """合成结果（测试夹具）：附带逐日持仓快照."""

    @property
    def positions_df(self) -> pd.DataFrame:
        idx = pd.to_datetime(["2024-01-03", "2024-01-04"]).tz_localize("UTC")
        return pd.DataFrame(
            {
                "date": idx,
                "symbol": ["AAA", "AAA"],
                "long_shares": [100.0, 100.0],
                "short_shares": [0.0, 0.0],
                "close": [100.0, 101.0],
                "equity": [1_001_000.0, 1_002_000.0],
                "market_value": [10_000.0, 10_100.0],
                "unrealized_pnl": [100.0, 200.0],
                "entry_price": [99.0, 99.0],
            }
        )


def _market_frame() -> pd.DataFrame:
    idx = pd.date_range("2024-01-02", periods=60, freq="B")
    base = [100.0 + (i % 7) for i in range(60)]
    return pd.DataFrame(
        {
            "date": idx,
            "open": base,
            "high": [v + 1.5 for v in base],
            "low": [v - 1.5 for v in base],
            "close": [v + 0.5 for v in base],
            "volume": [1_000_000 + i * 1000 for i in range(60)],
        }
    )


def test_build_app_data_structure() -> None:
    """Payload 顶层结构与关键区块存在."""
    app = build_app_data(_StubResult(), market_data={"AAA": _market_frame()}, title="t")
    assert app["serverMode"] is False
    assert app["summary"]["initial_cash"] == "1,000,000.00"
    assert app["summary"]["duration"].endswith("天")
    labels = [c["label"] for c in app["metrics"]]
    assert any("Total Return" in label for label in labels)
    assert any("Sharpe" in label for label in labels)
    assert len(app["equity"]) == len(app["drawdown"]) > 0
    assert app["yearlyReturns"], "yearlyReturns 为空"
    assert app["returnsDist"]["bins"], "returnsDist 为空"
    assert app["tradesDist"]["bins"], "tradesDist 为空"
    assert app["pnlDuration"]["points"], "pnlDuration 为空"
    assert app["monthlyHeatmapHtml"].startswith("<table")
    assert app["benchmark"]["available"] is False
    assert "AAA" in app["payloads"]
    assert app["payloads"]["AAA"]["markers"], "买卖点标记为空"
    assert app["risk"]["emptyReason"], "风控空态文案为空"


def test_metric_card_colors() -> None:
    """指标卡颜色类：正红负绿、回撤警示."""
    app = build_app_data(_StubResult(), title="t")
    cards = {c["label"]: c for c in app["metrics"]}
    assert cards["累计收益率 (Total Return)"]["cls"] == "pos"
    assert cards["最大回撤 (Max DD)"]["cls"] == "warn"


def test_daily_positions_section() -> None:
    """每日持仓总览按权益日期补齐空仓日，并展示持仓权重."""
    app = build_app_data(_PositionsStubResult(), title="t")
    html = app["dailyPositionsHtml"]
    assert "每日持仓" not in html  # 卡片标题在模板里，不进入 fragment
    assert "<td>2024-01-02</td>" in html
    assert "<td>2024-01-03</td>" in html
    assert "AAA" in html
    assert "1.01%" in html
    assert "<th>总资产(万)</th>" in html
    assert "1.01万" in html
    assert "100.20万" in html
    assert "空仓" in html


def test_benchmark_section() -> None:
    """基准对比：超额收益与三线曲线."""
    result = _StubResult()
    bench = result.equity_curve.pct_change().dropna() * 0.8
    bench.name = "BENCH"
    app = build_app_data(result, benchmark=bench, title="t")
    bm = app["benchmark"]
    assert bm["available"] is True
    assert bm["cards"][0]["value"] == "BENCH"
    assert len(bm["strategy"]) == len(bm["benchmark"]) == len(bm["excess"])
    assert bm["cards"][1]["value"].endswith("%")


def test_plot_report_writes_html(tmp_path: Path) -> None:
    """plot_report 写出自包含 HTML（内嵌图表库与 payload）."""
    out = plot_report(
        _StubResult(),
        market_data={"AAA": _market_frame()},
        filename=str(tmp_path / "r.html"),
        title="单元测试",
    )
    page = Path(out).read_text(encoding="utf-8")
    assert "LightweightCharts" in page
    assert '"serverMode":false' in page
    assert "交易复盘" in page and "AAA" in page
    assert "<script src" not in page  # 无外部脚本引用，完全自包含


def test_render_html_escapes_script_close() -> None:
    """Payload 中的 '</script' 必须被转义，防止数据岛提前闭合."""
    app = build_app_data(_StubResult(), title="t")
    app["payloads"]["X</script>"] = {}
    page = render_html("t", app)
    assert "X</script>" not in page
    assert "X\\u003c/script>" in page


@pytest.mark.skipif(
    os.environ.get("AKQUANT_LWC_E2E") != "1",
    reason="端到端测试需设置 AKQUANT_LWC_E2E=1 并具备 akquant 环境",
)
def test_e2e_with_real_backtest() -> None:
    """真实数据端到端（opt-in）：akquant 回测 + 报告生成."""
    pytest.importorskip("akquant")
    # 由调用方在 E2E 环境中提供真实数据与策略；此处仅占位说明。


def test_patch_injects_methods_without_shadowing_upstream() -> None:
    """补丁仅注入 report_lwc/serve_review，不注入同名 report 影子方法."""
    pytest.importorskip("akquant")
    from akquant.backtest.result import BacktestResult

    from akquant_lwc._patch import patch_result_methods

    assert patch_result_methods() is True
    assert callable(getattr(BacktestResult, "report_lwc", None))
    assert callable(getattr(BacktestResult, "serve_review", None))
    # 遵循上游纯净断裂原则：插件绝不定义/覆盖 ``report`` 同名方法
    if hasattr(BacktestResult, "report"):
        assert BacktestResult.report is not BacktestResult.report_lwc


def test_plot_report_external_data(tmp_path: Path) -> None:
    """external_data=True：HTML 不内嵌行情，伴随写出 data.json 且含外置标记."""
    out = plot_report(
        _StubResult(),
        market_data={"AAA": _market_frame()},
        filename=str(tmp_path / "r_ext.html"),
        title="外置测试",
        external_data=True,
    )
    page = Path(out).read_text(encoding="utf-8")
    assert '"externalData":{"file":"r_ext.data.json"}' in page
    assert '"payloads":{}' in page  # 页面本身不再内嵌行情
    data_file = tmp_path / "r_ext.data.json"
    assert data_file.exists()
    companion = json.loads(data_file.read_text(encoding="utf-8"))
    assert "AAA" in companion["payloads"]
    assert companion["symbols"] == ["AAA"]
    assert companion["payloads"]["AAA"]["candles"], "外置行情为空"
