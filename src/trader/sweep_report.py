"""Visual report for sweep results.

Loads a sweep parquet and renders heatmaps + scatter plots that surface
the structure of the parameter landscape: where Sharpe is high, where
trade counts collapse, and whether winners sit at the edge of the grid.

matplotlib is imported lazily so this module is importable without the
``docs`` Poetry group, but the rendering functions require it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure


def aggregate_landscape(
    results: pd.DataFrame,
    metric: str,
    statistic: str = "mean",
) -> pd.DataFrame:
    """Average ``metric`` across symbols and ATR axes per (cohort, tf, pullback, rsi).

    Returns one row per (cohort, timeframe, pullback_tolerance, long_rsi_floor)
    with columns ``value`` (the chosen statistic) and ``trade_count_mean``.
    """
    if metric not in results.columns:
        raise ValueError(f"metric '{metric}' nicht im Sweep-Frame.")

    grouped = results.groupby(["cohort", "timeframe", "pullback_tolerance", "long_rsi_floor"])
    summary = grouped.agg(
        value=(metric, statistic),
        trade_count_mean=("oos_trade_count", "mean"),
        cell_count=(metric, "size"),
    ).reset_index()
    return summary


def _pivot_for_heatmap(landscape: pd.DataFrame, value_column: str) -> pd.DataFrame:
    return landscape.pivot(
        index="long_rsi_floor",
        columns="pullback_tolerance",
        values=value_column,
    ).sort_index()


def plot_landscape_heatmap(
    results: pd.DataFrame,
    metric: str = "oos_sharpe",
    *,
    min_trades: int = 30,
    title: str | None = None,
) -> Figure:
    """4-panel heatmap (equity/crypto x 1d/1h) of the chosen metric.

    A `*` overlay marks cells whose mean OOS trade count meets ``min_trades``.
    Axes are ``pullback_tolerance`` (x) and ``long_rsi_floor`` (y); the
    ATR-clip axes are averaged over.
    """
    import matplotlib.pyplot as plt

    landscape = aggregate_landscape(results, metric)
    panel_keys = sorted({(row["cohort"], row["timeframe"]) for _, row in landscape.iterrows()})
    rows = 2
    cols = max(1, len(panel_keys) // rows + (1 if len(panel_keys) % rows else 0))
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), squeeze=False)

    vmin, vmax = _value_range(landscape["value"])
    for idx, key in enumerate(panel_keys):
        ax = axes[idx // cols][idx % cols]
        cohort, timeframe = key
        sub = landscape[(landscape["cohort"] == cohort) & (landscape["timeframe"] == timeframe)]
        value_grid = _pivot_for_heatmap(sub, "value")
        trade_grid = _pivot_for_heatmap(sub, "trade_count_mean")

        im = ax.imshow(value_grid.values, aspect="auto", cmap="RdYlGn", vmin=vmin, vmax=vmax)
        ax.set_xticks(np.arange(value_grid.shape[1]))
        ax.set_xticklabels([f"{c:g}" for c in value_grid.columns])
        ax.set_yticks(np.arange(value_grid.shape[0]))
        ax.set_yticklabels([f"{r:g}" for r in value_grid.index])
        ax.set_xlabel("pullback_tolerance")
        ax.set_ylabel("long_rsi_floor")
        ax.set_title(f"{cohort}/{timeframe}")

        # Annotate value + eligibility marker.
        for i, row_idx in enumerate(value_grid.index):
            for j, col in enumerate(value_grid.columns):
                v = value_grid.loc[row_idx, col]
                tc = trade_grid.loc[row_idx, col]
                eligible = "*" if tc >= min_trades else ""
                if pd.notna(v):
                    ax.text(
                        j,
                        i,
                        f"{v:.2f}{eligible}",
                        ha="center",
                        va="center",
                        fontsize=8,
                        color="black",
                    )
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)

    # Hide unused panels.
    for spare in range(len(panel_keys), rows * cols):
        axes[spare // cols][spare % cols].axis("off")

    if title is None:
        title = f"{metric} (mean across ATR axes; * = trade_count_mean ≥ {min_trades})"
    fig.suptitle(title, fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig


def plot_trade_count_distribution(results: pd.DataFrame) -> Figure:
    """Box plots of OOS trade counts per (cohort, timeframe).

    Shows visually why 1d cohorts may fail ``min_trades`` filtering.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(9, 4))
    grouped = results.groupby(["cohort", "timeframe"])
    labels = []
    data = []
    for (cohort, timeframe), sub in grouped:
        labels.append(f"{cohort}\n{timeframe}")
        data.append(sub["oos_trade_count"].to_numpy())
    ax.boxplot(data, tick_labels=labels, showmeans=True)
    ax.set_ylabel("OOS trade count per cell")
    ax.set_title("Trade-count distribution by cohort/timeframe")
    ax.axhline(30, color="red", linestyle="--", linewidth=1, label="min_trades=30")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    return fig


def plot_sharpe_vs_trades(
    results: pd.DataFrame,
    *,
    min_trades: int = 30,
) -> Figure:
    """Scatter of OOS Sharpe vs OOS trade count, per (cohort, timeframe).

    A vertical guide at ``min_trades`` separates filterable from
    eligible cells; helps eyeball whether high-Sharpe cells are
    overfit (low trade count) or robust (high trade count).
    """
    import matplotlib.pyplot as plt

    panel_keys = sorted(
        {(c, t) for c, t in results[["cohort", "timeframe"]].itertuples(index=False)}
    )
    rows = 2
    cols = max(1, (len(panel_keys) + rows - 1) // rows)
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), squeeze=False)

    for idx, (cohort, timeframe) in enumerate(panel_keys):
        ax = axes[idx // cols][idx % cols]
        sub = results[(results["cohort"] == cohort) & (results["timeframe"] == timeframe)]
        ax.scatter(
            sub["oos_trade_count"],
            sub["oos_sharpe"],
            s=14,
            alpha=0.5,
            c="tab:blue",
        )
        ax.axvline(min_trades, color="red", linestyle="--", linewidth=1)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.set_xlabel("OOS trade count")
        ax.set_ylabel("OOS Sharpe")
        ax.set_title(f"{cohort}/{timeframe}")
        ax.grid(True, alpha=0.3)

    for spare in range(len(panel_keys), rows * cols):
        axes[spare // cols][spare % cols].axis("off")

    fig.suptitle(f"OOS Sharpe vs trade count (red: min_trades={min_trades})")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return fig


def top_cells_table(
    results: pd.DataFrame,
    *,
    min_trades: int = 30,
    top_n: int = 5,
) -> pd.DataFrame:
    """Top-N cells by mean OOS Sharpe per (cohort, timeframe), eligible only."""
    landscape = (
        results.groupby(
            [
                "cohort",
                "timeframe",
                "pullback_tolerance",
                "long_rsi_floor",
                "atr_pct_floor",
                "atr_pct_ceiling",
            ]
        )
        .agg(
            oos_sharpe_mean=("oos_sharpe", "mean"),
            oos_trade_count_mean=("oos_trade_count", "mean"),
        )
        .reset_index()
    )
    eligible = landscape[landscape["oos_trade_count_mean"] >= min_trades].copy()
    if eligible.empty:
        return eligible
    return (
        eligible.sort_values("oos_sharpe_mean", ascending=False)
        .groupby(["cohort", "timeframe"], sort=True)
        .head(top_n)
        .reset_index(drop=True)
    )


def render_report(
    parquet_path: str | Path,
    out_dir: str | Path,
    *,
    min_trades: int = 30,
) -> Path:
    """Render the full PNG report into ``out_dir``. Returns the directory.

    Files written:
    - ``sharpe_heatmap.png``
    - ``trade_count_heatmap.png``
    - ``trade_count_distribution.png``
    - ``sharpe_vs_trades.png``
    - ``top_cells.csv``
    - ``REPORT.md`` (index)
    """
    import matplotlib.pyplot as plt

    parquet = Path(parquet_path)
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    results = pd.read_parquet(parquet)

    fig = plot_landscape_heatmap(results, metric="oos_sharpe", min_trades=min_trades)
    fig.savefig(target / "sharpe_heatmap.png", dpi=120)
    plt.close(fig)

    fig = plot_landscape_heatmap(
        results,
        metric="oos_trade_count",
        min_trades=min_trades,
        title=f"OOS trade count (mean; * = mean ≥ {min_trades})",
    )
    fig.savefig(target / "trade_count_heatmap.png", dpi=120)
    plt.close(fig)

    fig = plot_trade_count_distribution(results)
    fig.savefig(target / "trade_count_distribution.png", dpi=120)
    plt.close(fig)

    fig = plot_sharpe_vs_trades(results, min_trades=min_trades)
    fig.savefig(target / "sharpe_vs_trades.png", dpi=120)
    plt.close(fig)

    top = top_cells_table(results, min_trades=min_trades, top_n=10)
    top.to_csv(target / "top_cells.csv", index=False)

    _write_report_index(target, parquet, results, top, min_trades)
    return target


def _write_report_index(
    out_dir: Path,
    parquet: Path,
    results: pd.DataFrame,
    top: pd.DataFrame,
    min_trades: int,
) -> None:
    eligible_count = len(top)
    cohort_summary = (
        results.groupby(["cohort", "timeframe"])
        .agg(
            cell_count=("oos_sharpe", "size"),
            trade_count_median=("oos_trade_count", "median"),
            sharpe_median=("oos_sharpe", "median"),
            sharpe_max=("oos_sharpe", "max"),
        )
        .reset_index()
    )

    md = [
        f"# Sweep Report — {parquet.name}",
        "",
        f"Source: `{parquet}`",
        f"min_trades filter: {min_trades}",
        "",
        "## Per cohort × timeframe",
        "",
        "```",
        cohort_summary.to_string(index=False, float_format=lambda v: f"{v:.3f}"),
        "```",
        "",
        "## Top eligible cells",
        "",
    ]
    if top.empty:
        md.append(f"_None — no cell met `oos_trade_count_mean >= {min_trades}`._")
    else:
        md.append("```")
        md.append(top.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
        md.append("```")
    md.extend(
        [
            "",
            f"Eligible cells in top: {eligible_count}",
            "",
            "## Plots",
            "",
            "- ![Sharpe heatmap](sharpe_heatmap.png)",
            "- ![Trade-count heatmap](trade_count_heatmap.png)",
            "- ![Trade-count distribution](trade_count_distribution.png)",
            "- ![Sharpe vs trades](sharpe_vs_trades.png)",
        ]
    )
    (out_dir / "REPORT.md").write_text("\n".join(md), encoding="utf-8")


def _value_range(series: pd.Series) -> tuple[float, float]:
    finite = series[np.isfinite(series)]
    if finite.empty:
        return -1.0, 1.0
    lo = float(finite.min())
    hi = float(finite.max())
    if lo == hi:
        return lo - 0.5, hi + 0.5
    return lo, hi


def _ax_label_to_str(ax: Axes) -> str:  # pragma: no cover - debug helper
    return ax.get_title()
