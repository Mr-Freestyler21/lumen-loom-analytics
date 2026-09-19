"""
eda.py
======
Exploratory data analysis for the Lumen & Loom pipeline. Connects read-only to
the DuckDB warehouse built by scripts/build_database.py, pulls the analytical
views, and renders publication-quality charts to charts/.

Every chart follows one discipline (see python/viz_style.py):
  * the form is chosen by the data's job (trend, mix, magnitude, retention...);
  * categorical color is a FIXED category->hue map, never cycled;
  * magnitude uses ONE sequential blue, light->dark;
  * no dual axes: two measures of different scale become two panels;
  * text stays in ink tokens; marks stay thin; grids stay recessive.

Run:  python python/eda.py   (from the repo root, after build_database.py)
"""

from __future__ import annotations

import os
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter, MaxNLocator

import viz_style as vs

# ---------------------------------------------------------------- setup ------ #
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
os.makedirs("charts", exist_ok=True)
vs.apply_theme()

con = duckdb.connect("lumen_loom.duckdb", read_only=True)


def q(sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


# =========================================================================== #
# 1. Monthly net revenue: trend over time (line + 3-month average)
#    Job: change over time. One measure -> one hue, two shades.
# =========================================================================== #
def chart_monthly_revenue() -> None:
    m = q("SELECT * FROM v_monthly_revenue ORDER BY order_month")
    m["order_month"] = pd.to_datetime(m["order_month"])
    m["roll"] = m["net_revenue"].rolling(3, min_periods=1).mean()

    fig, ax = vs.new_fig(10.5, 5.2)
    vs.grid_y_only(ax)

    ax.fill_between(m.order_month, m.net_revenue, color=vs.BLUE, alpha=0.08, zorder=1)
    ax.plot(m.order_month, m.net_revenue, color="#9ec5f4", lw=1.5,
            zorder=2, label="Monthly net revenue")
    ax.plot(m.order_month, m.roll, color=vs.BLUE, lw=2.4,
            zorder=3, label="3-month average")

    # direct-label the final peak instead of trusting the eye to the axis
    peak = m.iloc[-1]
    ax.scatter([peak.order_month], [peak.net_revenue], s=34, color=vs.BLUE, zorder=4)
    ax.annotate(f"  {vs.usd(peak.net_revenue)}",
                (peak.order_month, peak.net_revenue),
                color=vs.INK, fontsize=10, fontweight="bold", va="center")

    ax.yaxis.set_major_formatter(FuncFormatter(vs.usd))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.set_ylim(0, m.net_revenue.max() * 1.15)
    ax.margins(x=0.01)
    ax.legend(loc="upper left", ncols=2)

    vs.titles(ax, "Net revenue nearly tripled over three years",
              "Monthly net revenue, Jan 2023 to Dec 2025  ·  seasonal Q4 peaks each November-December")
    vs.save(fig, "01_monthly_revenue")


# =========================================================================== #
# 2. Revenue by category over time: mix + seasonality (stacked area)
#    Job: composition over time. Categorical -> fixed category->hue map.
# =========================================================================== #
def chart_category_area() -> None:
    cm = q("SELECT * FROM v_category_month")
    piv = cm.pivot(index="order_month", columns="category", values="net_revenue").fillna(0)
    piv.index = pd.to_datetime(piv.index)

    order = piv.sum().sort_values(ascending=False).index.tolist()  # largest on bottom
    colors = [vs.CATEGORY_COLORS[c] for c in order]

    fig, ax = vs.new_fig(10.5, 5.6)
    vs.grid_y_only(ax)
    ax.stackplot(piv.index, [piv[c].to_numpy() for c in order],
                 colors=colors, labels=order,
                 edgecolor=vs.SURFACE, linewidth=0.5)  # 2px-ish surface gap between fills

    ax.yaxis.set_major_formatter(FuncFormatter(vs.usd))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))
    ax.set_ylim(0, piv.sum(axis=1).max() * 1.08)
    ax.margins(x=0.01)

    # legend in fixed category order (identity, matches stack colors)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], labels[::-1], loc="upper left", ncols=3,
              columnspacing=1.2, handlelength=1.1)

    vs.titles(ax, "Everyday categories drive the base; Outdoor adds a summer swell",
              "Monthly net revenue by product category  ·  stacked, Jan 2023 to Dec 2025")
    vs.save(fig, "02_category_revenue_area")


# =========================================================================== #
# 3. Category seasonality: where each category's year lands (heatmap)
#    Job: magnitude across two categoricals -> sequential blue.
# =========================================================================== #
def chart_seasonality_heatmap() -> None:
    cs = q("SELECT * FROM v_category_seasonality")
    piv = cs.pivot(index="category", columns="month_no", values="pct_of_annual")
    row_order = ["Outdoor", "Furniture", "Textiles", "Kitchen & Dining", "Lighting", "Decor"]
    piv = piv.reindex([r for r in row_order if r in piv.index])
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    fig, ax = vs.new_fig(10.5, 4.8)
    vs.grid_off(ax)
    data = piv.to_numpy(dtype=float)
    im = ax.imshow(data, cmap=vs.SEQ_BLUE, aspect="auto",
                   vmin=np.nanmin(data), vmax=np.nanmax(data))

    ax.set_xticks(range(12), months)
    ax.set_yticks(range(len(piv.index)), piv.index)
    ax.tick_params(length=0)

    thresh = np.nanmin(data) + 0.62 * (np.nanmax(data) - np.nanmin(data))
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            val = data[i, j]
            ax.text(j, i, f"{val:.0f}", ha="center", va="center", fontsize=8.5,
                    color=("#ffffff" if val >= thresh else vs.INK2))

    cbar = fig.colorbar(im, ax=ax, fraction=0.028, pad=0.02)
    cbar.set_label("% of category's annual revenue", color=vs.INK2, fontsize=9)
    cbar.ax.tick_params(color=vs.MUTED, labelcolor=vs.MUTED, length=0)
    cbar.outline.set_edgecolor(vs.GRID)

    vs.titles(ax, "Outdoor peaks in summer; everything else peaks in Q4",
              "Share of each category's annual revenue by calendar month (avg. across years)")
    vs.save(fig, "03_category_seasonality_heatmap")


# =========================================================================== #
# 4. Cohort retention: quarterly acquisition cohorts (heatmap)
#    Job: magnitude across cohort x age -> sequential blue. Month 0 (=100%)
#    omitted so the decay gradient is legible.
# =========================================================================== #
def chart_cohort_heatmap() -> None:
    co = q("SELECT * FROM v_cohort_retention")
    co["cohort_month"] = pd.to_datetime(co["cohort_month"])
    co["cohort_q"] = co["cohort_month"].dt.to_period("Q")

    # roll monthly cohorts up to quarters: customers are distinct across
    # different cohort months, so summing actives and sizes is valid.
    sizes = (co[["cohort_month", "cohort_size"]].drop_duplicates()
             .assign(cohort_q=lambda d: d.cohort_month.dt.to_period("Q"))
             .groupby("cohort_q")["cohort_size"].sum())
    agg = (co.groupby(["cohort_q", "month_offset"])["active_customers"].sum()
           .reset_index().merge(sizes.rename("size"), on="cohort_q"))
    agg["ret"] = agg.active_customers / agg["size"]

    piv = agg.pivot(index="cohort_q", columns="month_offset", values="ret")
    piv = piv.reindex(columns=[c for c in piv.columns if 1 <= c <= 12])
    piv = piv.sort_index()

    data = piv.to_numpy(dtype=float)
    fig, ax = vs.new_fig(10.5, 6.0)
    vs.grid_off(ax)
    im = ax.imshow(data, cmap=vs.SEQ_BLUE, aspect="auto",
                   vmin=0, vmax=np.nanmax(data))

    ax.set_xticks(range(data.shape[1]), [str(c) for c in piv.columns])
    ax.set_xlabel("Months since first purchase")
    ylabels = [f"{p}  (n={int(sizes[p]):,})" for p in piv.index]
    ax.set_yticks(range(len(piv.index)), ylabels)
    ax.tick_params(length=0)

    thresh = 0.62 * np.nanmax(data)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            val = data[i, j]
            if np.isnan(val):
                continue
            ax.text(j, i, f"{val*100:.0f}", ha="center", va="center", fontsize=7.5,
                    color=("#ffffff" if val >= thresh else vs.INK2))

    cbar = fig.colorbar(im, ax=ax, fraction=0.028, pad=0.02,
                        format=FuncFormatter(lambda x, _: f"{x*100:.0f}%"))
    cbar.set_label("of cohort ordering again", color=vs.INK2, fontsize=9)
    cbar.ax.tick_params(color=vs.MUTED, labelcolor=vs.MUTED, length=0)
    cbar.outline.set_edgecolor(vs.GRID)

    vs.titles(ax, "Repeat purchasing settles at a stable 3-6% monthly",
              "Quarterly acquisition cohorts · % ordering again N months later (month 0 = 100% omitted)")
    vs.save(fig, "04_cohort_retention_heatmap")


# =========================================================================== #
# 5. RFM segments: revenue contribution by segment (horizontal bars)
#    Job: magnitude across identity -> sequential blue by value; direct labels.
# =========================================================================== #
def chart_rfm_segments() -> None:
    seg = q("SELECT * FROM v_rfm_segments ORDER BY revenue")
    n = len(seg)
    # shade by rank: bigger revenue -> darker blue
    shades = [vs.BLUE_RAMP[int(round(i * (len(vs.BLUE_RAMP) - 1) / (n - 1)))]
              for i in range(n)]

    fig, ax = vs.new_fig(10.5, 5.2)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    y = np.arange(n)
    ax.barh(y, seg.revenue, color=shades, height=0.68, zorder=3)
    ax.set_yticks(y, seg.segment)

    span = seg.revenue.max()
    for yi, (_, row) in zip(y, seg.iterrows()):
        ax.text(row.revenue + span * 0.01, yi,
                f"{vs.usd(row.revenue)}   ·   {int(row.customers):,} customers   ·   {vs.usd(row.avg_ltv)} avg LTV",
                va="center", ha="left", fontsize=9, color=vs.INK2)

    ax.xaxis.set_major_formatter(FuncFormatter(vs.usd))
    ax.set_xlim(0, span * 1.42)
    ax.tick_params(axis="y", length=0)

    vs.titles(ax, "Champions and Loyal customers drive most revenue",
              "Net revenue by RFM segment  ·  bar shade = revenue rank")
    vs.save(fig, "05_rfm_segments")


# =========================================================================== #
# 6. Channel value: volume vs. loyalty (two panels, shared channel order)
#    Job: two measures of different scale -> NO dual axis. Two aligned panels,
#    with owned channels (Email/Referral) emphasized in both.
# =========================================================================== #
def chart_channel_value() -> None:
    ch = q("SELECT * FROM v_channel_performance ORDER BY avg_ltv")
    highlight = {"Email", "Referral"}
    colors = [vs.ACCENT if c in highlight else "#c7c6c0" for c in ch.channel]

    fig, (ax1, ax2) = vs.plt.subplots(1, 2, figsize=(11, 5.2), sharey=True)
    for ax in (ax1, ax2):
        ax.grid(axis="x")
        ax.grid(axis="y", visible=False)
        ax.tick_params(length=0)

    y = np.arange(len(ch))
    ax1.barh(y, ch.customers, color=colors, height=0.66, zorder=3)
    ax1.set_yticks(y, ch.channel)
    ax1.set_title("Customers acquired", loc="left", color=vs.INK2, fontsize=11)
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x/1000:.0f}k"))
    for yi, v in zip(y, ch.customers):
        ax1.text(v * 0.98, yi, f"{int(v):,}", va="center", ha="right",
                 fontsize=8.5, color="#ffffff" if True else vs.INK2)

    ax2.barh(y, ch.avg_ltv, color=colors, height=0.66, zorder=3)
    ax2.set_title("Average lifetime revenue", loc="left", color=vs.INK2, fontsize=11)
    ax2.xaxis.set_major_formatter(FuncFormatter(vs.usd))
    for yi, v in zip(y, ch.avg_ltv):
        ax2.text(v + ch.avg_ltv.max() * 0.02, yi, vs.usd(v), va="center",
                 ha="left", fontsize=8.5, color=vs.INK2)
    ax2.set_xlim(0, ch.avg_ltv.max() * 1.18)

    fig.suptitle("Owned channels buy loyalty; paid channels buy volume",
                 x=0.125, y=1.00, ha="left", fontsize=15, fontweight="bold", color=vs.INK)
    fig.text(0.125, 0.94,
             "By acquisition channel · Email & Referral (highlighted) convert fewer customers but far higher lifetime value",
             ha="left", fontsize=10.5, color=vs.INK2)
    fig.subplots_adjust(top=0.86, wspace=0.08)
    vs.save(fig, "06_channel_value")


# =========================================================================== #
# 7. Top products: the revenue leaders (horizontal bars)
#    Job: magnitude across identity -> sequential blue by value.
# =========================================================================== #
def chart_top_products() -> None:
    tp = q("SELECT * FROM v_top_products LIMIT 10").sort_values("net_revenue")
    n = len(tp)
    shades = [vs.BLUE_RAMP[int(round(i * (len(vs.BLUE_RAMP) - 1) / (n - 1)))]
              for i in range(n)]

    fig, ax = vs.new_fig(10.5, 5.4)
    ax.grid(axis="x")
    ax.grid(axis="y", visible=False)
    y = np.arange(n)
    ax.barh(y, tp.net_revenue, color=shades, height=0.7, zorder=3)
    labels = [f"{name}  ·  {cat}" for name, cat in zip(tp.product_name, tp.category)]
    ax.set_yticks(y, labels)
    ax.tick_params(axis="y", length=0)

    span = tp.net_revenue.max()
    for yi, v in zip(y, tp.net_revenue):
        ax.text(v + span * 0.01, yi, vs.usd(v), va="center", ha="left",
                fontsize=9, color=vs.INK2)
    ax.xaxis.set_major_formatter(FuncFormatter(vs.usd))
    ax.set_xlim(0, span * 1.16)

    vs.titles(ax, "The ten products that generate the most revenue",
              "Net revenue by product, all-time  ·  bar shade = revenue rank")
    vs.save(fig, "07_top_products")


def main() -> None:
    charts = [
        chart_monthly_revenue,
        chart_category_area,
        chart_seasonality_heatmap,
        chart_cohort_heatmap,
        chart_rfm_segments,
        chart_channel_value,
        chart_top_products,
    ]
    for fn in charts:
        fn()
        print(f"  rendered  charts/{fn.__name__}")
    con.close()
    print(f"\nDone. {len(charts)} charts written to charts/")


if __name__ == "__main__":
    main()
