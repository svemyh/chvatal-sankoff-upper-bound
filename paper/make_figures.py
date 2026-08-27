#!/usr/bin/env python3
"""Regenerate the two literature/result figures used by the manuscript."""

from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


ROOT = Path(__file__).resolve().parent
GREEN = "#1f6f57"
GOLD = "#a66a16"
REPORT = "#8c5a2b"
RESULT = "#aa3f24"
GRAY = "#777777"

mpl.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "pdf.fonttype": 42,
    }
)


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(
        ROOT / name,
        bbox_inches="tight",
        metadata={
            "Title": name,
            "Author": "Ara and Sven Myhre",
            "Creator": "paper/make_figures.py",
            "CreationDate": None,
            "ModDate": None,
        },
    )
    plt.close(fig)


def history() -> None:
    fig, ax = plt.subplots(figsize=(5.25, 2.75))

    upper_years = [1975, 1983, 1995, 2009, 2026]
    upper = [0.86660, 0.85750, 0.837623, 0.826280, 0.824443]
    lower_years = [1975, 1983, 1994, 2009, 2025]
    lower = [0.727273, 0.7615, 0.773911, 0.788071, 0.792665992]

    ax.step(
        upper_years,
        upper,
        where="post",
        color=GREEN,
        linewidth=1.8,
        label="peer-reviewed/certified upper record",
    )
    ax.plot(upper_years[:-1], upper[:-1], "o", color=GREEN, markersize=4)
    ax.step(
        lower_years,
        lower,
        where="post",
        color=GOLD,
        linewidth=1.8,
        label="peer-reviewed lower record",
    )
    ax.plot(lower_years, lower, "o", color=GOLD, markersize=4)

    ax.plot(
        2018,
        0.825101,
        marker="D",
        markersize=5,
        markerfacecolor="white",
        markeredgewidth=1.3,
        color=REPORT,
        linestyle="none",
        label="Liu 2018 report (unaudited)",
    )
    ax.annotate(
        "0.825101 reported",
        xy=(2018, 0.825101),
        xytext=(0, -9),
        textcoords="offset points",
        ha="center",
        color=REPORT,
        fontsize=8,
    )

    ax.plot(
        2026,
        0.824443,
        marker="*",
        markersize=9,
        color=RESULT,
        linestyle="none",
        label="this certified result",
    )
    ax.annotate(
        "0.824443",
        xy=(2026, 0.824443),
        xytext=(-4, 10),
        textcoords="offset points",
        ha="right",
        color=RESULT,
        fontsize=8,
    )

    ax.axhline(0.8122, color=GRAY, linestyle=":", linewidth=1.2)
    ax.text(1976, 0.8137, "simulation estimate ≈ 0.8122", color=GRAY, fontsize=8)

    ax.set_xlim(1972.5, 2028.5)
    ax.set_ylim(0.72, 0.875)
    ax.set_xlabel("year")
    ax.set_ylabel(r"bounds on $\gamma_2$")
    ax.legend(loc="lower right", frameon=False, fontsize=7.3, handlelength=2.6)
    fig.tight_layout()
    save(fig, "fig_history.pdf")


def scaling() -> None:
    fig, ax = plt.subplots(figsize=(5.25, 2.75))

    histories = [2, 8, 10]
    certified = [0.852985, 0.826280, 0.824443]
    ax.plot(
        histories,
        certified,
        color=GREEN,
        marker="o",
        linewidth=1.8,
        markersize=5,
        label=r"certified at $z=3209/10000$",
    )
    for h, value, offset, align in [
        (2, 0.852985, (8, 5), "left"),
        (8, 0.826280, (8, 5), "left"),
        (10, 0.824443, (-4, -9), "right"),
    ]:
        ax.annotate(
            f"{value:.6f}",
            xy=(h, value),
            xytext=offset,
            textcoords="offset points",
            ha=align,
            fontsize=8,
        )

    ax.axhline(
        0.826280,
        color=RESULT,
        linestyle="--",
        linewidth=1.2,
        label="previous certified record",
    )
    ax.axhline(
        0.825101,
        color=REPORT,
        linestyle=":",
        linewidth=1.4,
        label="Liu 2018 report (unaudited)",
    )

    ax.set_xlim(1.6, 10.8)
    ax.set_ylim(0.8215, 0.8545)
    ax.set_xticks(histories)
    ax.set_xlabel(r"history length $h$")
    ax.set_ylabel("certified upper bound")
    ax.legend(loc="upper right", frameon=False, fontsize=7.4)
    fig.tight_layout()
    save(fig, "fig_scaling.pdf")


if __name__ == "__main__":
    history()
    scaling()
