"""Dependency-free local dashboard for saved research artifacts."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pandas as pd


@dataclass(frozen=True)
class DashboardConfig:
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8765


def serve_dashboard(config: DashboardConfig | None = None) -> None:
    dashboard_config = config or DashboardConfig()
    data_dir = dashboard_config.data_dir.resolve()
    data_dir.mkdir(parents=True, exist_ok=True)

    class Handler(_DashboardHandler):
        root_dir = data_dir

    server = ThreadingHTTPServer((dashboard_config.host, dashboard_config.port), Handler)
    print(f"Dashboard: http://{dashboard_config.host}:{dashboard_config.port}")
    print(f"Data dir:  {data_dir}")
    server.serve_forever()


def build_dashboard_payload(data_dir: str | Path) -> dict[str, Any]:
    root = Path(data_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    backtests = _discover_backtests(root)
    sweeps = _discover_sweeps(root)
    return {
        "data_dir": str(root),
        "backtests": backtests,
        "sweeps": sweeps,
        "counts": {
            "backtests": len(backtests),
            "sweeps": len(sweeps),
        },
    }


def render_dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Trader Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #1b1f23;
      --muted: #667085;
      --line: #d0d5dd;
      --accent: #0f766e;
      --accent-2: #b42318;
      --soft: #eef4f2;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 18px 24px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 { font-size: 20px; margin: 0; font-weight: 650; }
    main { max-width: 1280px; margin: 0 auto; padding: 18px 24px 32px; }
    .toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    button, select {
      min-height: 34px;
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      border-radius: 6px;
      padding: 6px 10px;
      font: inherit;
    }
    button { cursor: pointer; }
    button.primary { background: var(--accent); color: white; border-color: var(--accent); }
    .grid { display: grid; grid-template-columns: 280px minmax(0, 1fr); gap: 16px; }
    aside, section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
    }
    aside { padding: 12px; }
    section { padding: 16px; }
    h2 { font-size: 15px; margin: 0 0 10px; }
    .list { display: grid; gap: 8px; }
    .item {
      width: 100%;
      text-align: left;
      border: 1px solid var(--line);
      background: white;
      border-radius: 6px;
      padding: 9px;
    }
    .item.active { border-color: var(--accent); background: var(--soft); }
    .item strong { display: block; font-size: 13px; }
    .item span { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
    .metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
    .metric { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfd; }
    .metric span { display: block; color: var(--muted); font-size: 12px; }
    .metric strong { display: block; font-size: 18px; margin-top: 4px; overflow-wrap: anywhere; }
    .chart { width: 100%; min-height: 260px; border: 1px solid var(--line); border-radius: 8px; background: white; margin-bottom: 14px; overflow: hidden; }
    svg { display: block; width: 100%; height: 280px; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 7px 8px; text-align: right; white-space: nowrap; }
    th:first-child, td:first-child { text-align: left; }
    .table-wrap { overflow-x: auto; border: 1px solid var(--line); border-radius: 8px; }
    .muted { color: var(--muted); }
    .tabs { display: flex; gap: 8px; margin-bottom: 12px; }
    .tab.active { background: var(--ink); color: white; border-color: var(--ink); }
    @media (max-width: 860px) {
      header { align-items: flex-start; flex-direction: column; }
      main { padding: 12px; }
      .grid { grid-template-columns: 1fr; }
      .metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <h1>Trader Dashboard</h1>
    <div class="toolbar">
      <select id="kind">
        <option value="backtests">Backtests</option>
        <option value="sweeps">Sweeps</option>
      </select>
      <button class="primary" id="refresh">Refresh</button>
    </div>
  </header>
  <main>
    <div class="grid">
      <aside>
        <h2>Runs</h2>
        <div id="runs" class="list"></div>
      </aside>
      <section>
        <div class="tabs">
          <button class="tab active" data-view="overview">Overview</button>
          <button class="tab" data-view="trades">Trades</button>
          <button class="tab" data-view="files">Files</button>
        </div>
        <div id="content"></div>
      </section>
    </div>
  </main>
  <script>
    const state = { payload: null, kind: "backtests", selected: 0, view: "overview" };
    const fmt = value => {
      if (value === null || value === undefined || Number.isNaN(value)) return "";
      if (typeof value === "number") return Math.abs(value) < 10 ? value.toFixed(4) : value.toFixed(2);
      return String(value);
    };
    async function load() {
      const res = await fetch("/api/summary");
      state.payload = await res.json();
      renderRuns();
      renderContent();
    }
    function runs() { return state.payload ? state.payload[state.kind] : []; }
    function selected() { return runs()[state.selected] || null; }
    function renderRuns() {
      const box = document.getElementById("runs");
      const items = runs();
      box.innerHTML = items.length ? "" : `<p class="muted">No ${state.kind} found in data.</p>`;
      items.forEach((run, index) => {
        const button = document.createElement("button");
        button.className = "item" + (index === state.selected ? " active" : "");
        button.innerHTML = `<strong>${run.name}</strong><span>${run.label || ""}</span>`;
        button.onclick = () => { state.selected = index; renderRuns(); renderContent(); };
        box.appendChild(button);
      });
    }
    function metricCards(metrics) {
      return `<div class="metrics">${Object.entries(metrics).map(([k, v]) =>
        `<div class="metric"><span>${k}</span><strong>${fmt(v)}</strong></div>`).join("")}</div>`;
    }
    function renderContent() {
      const run = selected();
      const content = document.getElementById("content");
      if (!run) { content.innerHTML = `<p class="muted">Select a run.</p>`; return; }
      if (state.view === "files") { content.innerHTML = fileList(run); return; }
      if (state.kind === "sweeps") { content.innerHTML = sweepView(run); return; }
      if (state.view === "trades") { content.innerHTML = table(run.trades || []); return; }
      content.innerHTML = backtestView(run);
    }
    function backtestView(run) {
      return `${metricCards(run.metrics || {})}<div class="chart">${lineChart(run.equity || [])}</div>${table(run.summary || [])}`;
    }
    function sweepView(run) {
      return `${metricCards(run.metrics || {})}${table(run.winners || [])}`;
    }
    function fileList(run) {
      return `<div class="table-wrap"><table><thead><tr><th>File</th><th>Path</th></tr></thead><tbody>${Object.entries(run.files || {}).map(([k, v]) =>
        `<tr><td>${k}</td><td>${v || ""}</td></tr>`).join("")}</tbody></table></div>`;
    }
    function table(rows) {
      if (!rows.length) return `<p class="muted">No rows.</p>`;
      const keys = Object.keys(rows[0]);
      return `<div class="table-wrap"><table><thead><tr>${keys.map(k => `<th>${k}</th>`).join("")}</tr></thead><tbody>${rows.map(row =>
        `<tr>${keys.map(k => `<td>${fmt(row[k])}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    }
    function lineChart(rows) {
      if (!rows.length) return `<p class="muted">No equity curve.</p>`;
      const width = 900, height = 280, pad = 34;
      const values = rows.map(r => Number(r.equity)).filter(Number.isFinite);
      const bench = rows.map(r => Number(r.benchmark_equity)).filter(Number.isFinite);
      const all = values.concat(bench);
      const min = Math.min(...all), max = Math.max(...all);
      const scaleX = i => pad + (i / Math.max(rows.length - 1, 1)) * (width - pad * 2);
      const scaleY = v => height - pad - ((v - min) / Math.max(max - min, 1)) * (height - pad * 2);
      const path = key => rows.map((r, i) => `${i ? "L" : "M"}${scaleX(i).toFixed(1)},${scaleY(Number(r[key])).toFixed(1)}`).join(" ");
      return `<svg viewBox="0 0 ${width} ${height}" role="img">
        <line x1="${pad}" y1="${height-pad}" x2="${width-pad}" y2="${height-pad}" stroke="#d0d5dd"/>
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height-pad}" stroke="#d0d5dd"/>
        <path d="${path("equity")}" fill="none" stroke="#0f766e" stroke-width="2.5"/>
        ${bench.length ? `<path d="${path("benchmark_equity")}" fill="none" stroke="#b42318" stroke-width="2" stroke-dasharray="5 4"/>` : ""}
        <text x="${pad}" y="18" font-size="12" fill="#667085">Equity vs benchmark</text>
      </svg>`;
    }
    document.getElementById("kind").onchange = event => { state.kind = event.target.value; state.selected = 0; renderRuns(); renderContent(); };
    document.getElementById("refresh").onclick = load;
    document.querySelectorAll(".tab").forEach(tab => tab.onclick = () => {
      state.view = tab.dataset.view;
      document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t === tab));
      renderContent();
    });
    load();
  </script>
</body>
</html>"""


class _DashboardHandler(SimpleHTTPRequestHandler):
    root_dir: Path

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(render_dashboard_html())
            return
        if parsed.path == "/api/summary":
            self._send_json(build_dashboard_payload(self.root_dir))
            return
        if parsed.path == "/api/file":
            self._send_file(parse_qs(parsed.query).get("path", [""])[0])
            return
        self.send_error(404, "Not found")

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, body: str) -> None:
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, body: dict[str, Any]) -> None:
        payload = json.dumps(body, default=_json_default).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_file(self, relative_path: str) -> None:
        path = (self.root_dir / relative_path).resolve()
        if not path.is_file() or self.root_dir not in path.parents:
            self.send_error(404, "Not found")
            return
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def _discover_backtests(root: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for equity_path in sorted(root.rglob("*equity.*"), reverse=True):
        if equity_path.suffix not in {".csv", ".parquet", ".json"}:
            continue
        if "_trades" in equity_path.stem:
            continue
        try:
            equity = _read_frame(equity_path)
        except Exception:
            continue
        if not {"symbol", "equity", "time"}.issubset(equity.columns):
            continue
        trades_path = equity_path.with_name(f"{equity_path.stem}_trades.csv")
        metrics_path = equity_path.with_name(f"{equity_path.stem}_metrics.json")
        trades = _read_frame(trades_path) if trades_path.exists() else pd.DataFrame()
        metrics = _read_metrics(metrics_path) if metrics_path.exists() else {}
        portfolio = equity[equity["symbol"] == "PORTFOLIO"].sort_values("time")
        if portfolio.empty:
            portfolio = equity.sort_values("time")
        runs.append(
            {
                "name": equity_path.name,
                "label": f"{len(equity):,} rows | {equity['symbol'].nunique()} symbols",
                "files": {
                    "equity": _relative(root, equity_path),
                    "trades": _relative(root, trades_path) if trades_path.exists() else None,
                    "metrics": _relative(root, metrics_path) if metrics_path.exists() else None,
                },
                "metrics": _dashboard_metrics(metrics, portfolio, trades),
                "summary": _backtest_summary(equity),
                "trades": _table_rows(trades.sort_values("net_return").head(20))
                if "net_return" in trades.columns
                else [],
                "equity": _table_rows(
                    portfolio[["time", "equity", "benchmark_equity"]]
                    if "benchmark_equity" in portfolio.columns
                    else portfolio[["time", "equity"]]
                ),
            }
        )
    return runs


def _discover_sweeps(root: Path) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for parquet_path in sorted(root.rglob("*.parquet"), reverse=True):
        if "sweep" not in str(parquet_path.parent) and "sweep" not in parquet_path.stem:
            continue
        try:
            results = pd.read_parquet(parquet_path)
        except Exception:
            continue
        winners_path = parquet_path.with_name(f"{parquet_path.stem}_winners.json")
        winners_payload = _read_metrics(winners_path) if winners_path.exists() else {}
        winners = winners_payload.get("winners", [])
        runs.append(
            {
                "name": parquet_path.name,
                "label": f"{len(results):,} cells | {results['symbol'].nunique() if 'symbol' in results else 0} symbols",
                "files": {
                    "results": _relative(root, parquet_path),
                    "winners": _relative(root, winners_path) if winners_path.exists() else None,
                },
                "metrics": {
                    "cells": len(results),
                    "symbols": int(results["symbol"].nunique()) if "symbol" in results else 0,
                    "best_oos_sharpe": _max_or_none(results, "oos_sharpe"),
                    "eligible_winners": len(winners),
                },
                "winners": winners,
            }
        )
    return runs


def _backtest_summary(equity: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, frame in equity.groupby("symbol", sort=True):
        frame = frame.sort_values("time")
        start = float(frame["equity"].iloc[0])
        end = float(frame["equity"].iloc[-1])
        rows.append(
            {
                "symbol": symbol,
                "bars": len(frame),
                "ending_equity": end,
                "total_return": (end / start) - 1 if start > 0 else 0.0,
                "max_drawdown": float(frame["drawdown"].min())
                if "drawdown" in frame.columns
                else None,
            }
        )
    return rows


def _dashboard_metrics(
    metrics: dict[str, Any],
    portfolio: pd.DataFrame,
    trades: pd.DataFrame,
) -> dict[str, Any]:
    fallback_end = float(portfolio["equity"].iloc[-1]) if not portfolio.empty else None
    # Walk-forward runs prefix metric keys with `in_sample_` / `out_of_sample_`
    # (see backtest.run_walk_forward_backtest). Show out-of-sample numbers in
    # that case — the in-sample half is essentially fitted — and rename the
    # cards to `oos_*` so the dashboard reader knows what they represent.
    walk_forward = any(
        key.startswith("out_of_sample_") or key == "in_sample_fraction" for key in metrics
    )
    prefix = "out_of_sample_" if walk_forward else ""
    label_prefix = "oos_" if walk_forward else ""

    def pick(field: str, fallback: Any = None) -> Any:
        return metrics.get(f"{prefix}{field}", metrics.get(field, fallback))

    return {
        f"{label_prefix}ending_capital": pick("ending_capital", fallback_end),
        f"{label_prefix}total_return": pick("total_return"),
        f"{label_prefix}sharpe": pick("sharpe"),
        f"{label_prefix}max_drawdown": pick("max_drawdown"),
        f"{label_prefix}trades": pick("trade_count", len(trades)),
        f"{label_prefix}benchmark_return": pick("benchmark_total_return"),
        f"{label_prefix}win_rate": pick("win_rate"),
        f"{label_prefix}profit_factor": pick("profit_factor"),
    }


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".csv":
        return pd.read_csv(path)
    if path.suffix == ".json":
        return pd.read_json(path)
    raise ValueError(f"Unsupported frame file: {path}")


def _read_metrics(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _table_rows(frame: pd.DataFrame, limit: int = 1000) -> list[dict[str, Any]]:
    out = frame.head(limit).copy()
    for column in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[column]):
            out[column] = out[column].astype(str)
    return out.where(pd.notna(out), None).to_dict(orient="records")


def _max_or_none(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame.columns or frame.empty:
        return None
    value = frame[column].max()
    return float(value) if pd.notna(value) else None


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return html.escape(str(path))


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)
