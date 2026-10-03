"""Experiments for the report: minimum support, confidence, pruning and scalability.

All numbers in the report and the web dashboard come from the files this script writes:

    results/json/*.json      machine-readable results (used by the Flask app)
    results/tables/*.csv     tables (also *.md versions for pasting into the report)
    results/figures/*.png    figures

Run with::

    python -m src.experiments

Threshold choice. The thresholds below were selected after an exploratory run on the
cleaned data: the most frequent item appears in only ~11.5% of baskets, 36 items reach
5% support and 1,544 items reach 0.5%. Supports above 5% give almost no pairs, and below
0.5% the number of candidate pairs exceeds one million, so 0.5%-5% covers the useful range.
The 1% level is used as the reference setting because it still runs in about two seconds
but already produces itemsets up to size 5.
"""

from __future__ import annotations

import math
import platform
import random
import statistics
import subprocess
import sys
from importlib.metadata import version

import matplotlib

matplotlib.use("Agg")   # file output only, no GUI
import matplotlib.pyplot as plt  # noqa: E402

from src.apriori import AprioriResult, apriori, encode_transactions  # noqa: E402
from src.association_rules import generate_rules, rule_summary  # noqa: E402
from src.preprocessing import load_dataset_summary, load_transactions  # noqa: E402
from src.utils import (  # noqa: E402
    FIGURES_DIR, JSON_DIR, TABLES_DIR, ensure_dirs, format_itemset, markdown_table, save_csv, save_json,
)

SUPPORT_THRESHOLDS = [0.005, 0.0075, 0.01, 0.015, 0.02, 0.03, 0.04, 0.05]
REFERENCE_SUPPORT = 0.01
CONFIDENCE_THRESHOLDS = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
REFERENCE_CONFIDENCE = 0.5
SCALABILITY_SIZES = [2_500, 5_000, 10_000, 15_000]   # the full cleaned dataset is added automatically
REPEATS = 3            # each timing is the median of this many runs
RANDOM_SEED = 42

# Validated colour-blind-safe categorical palette (slots 1-3) and neutral inks.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def timed_apriori(transactions, min_support: float, encoded, repeats: int = REPEATS) -> tuple[AprioriResult, float]:
    """Run A-Priori ``repeats`` times; return the last result and the median run time."""
    times, result = [], None
    for _ in range(repeats):
        result = apriori(transactions, min_support, encoded=encoded)
        times.append(result.total_seconds)
    return result, statistics.median(times)


def environment_info() -> dict:
    cpu = platform.processor() or "unknown"
    ram_gb = None
    if sys.platform == "darwin":
        try:
            cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                 text=True, check=True).stdout.strip()
            ram_gb = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True,
                                        text=True, check=True).stdout) / 2**30
        except (OSError, subprocess.CalledProcessError, ValueError):
            pass
    return {
        "python": platform.python_version(),
        "os": platform.platform(),
        "cpu": cpu,
        "ram_gb": ram_gb,
        "packages": {p: version(p) for p in ("pandas", "numpy", "openpyxl", "flask", "matplotlib", "pytest")},
        "timing": f"wall-clock (time.perf_counter), median of {REPEATS} runs, single process",
    }


def _style_axes(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=11, color=INK, pad=10)
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=MUTED)


def _save(fig, name: str) -> str:
    path = FIGURES_DIR / name
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return name


def _share(part: int, whole: int) -> str:
    """Percentage as text; tiny shares use scientific notation instead of rounding to 0."""
    p = 100 * part / whole
    return f"{p:.2f}%" if p >= 0.01 else f"{p:.1e}%"


def _pct(values):
    return [f"{v * 100:g}%" for v in values]


# ---------------------------------------------------------------------------
# Experiment 1 - minimum support
# ---------------------------------------------------------------------------
def run_support_experiment(transactions, encoded) -> list[dict]:
    rows = []
    for s in SUPPORT_THRESHOLDS:
        res, seconds = timed_apriori(transactions, s, encoded)
        sizes = res.count_by_size()
        rows.append({
            "min_support": s,
            "min_support_count": res.min_count,
            "frequent_1": sizes.get(1, 0),
            "frequent_2": sizes.get(2, 0),
            "frequent_3plus": sum(v for k, v in sizes.items() if k >= 3),
            "total_frequent": len(res.frequent),
            "largest_itemset": max(sizes),
            "candidates_generated": sum(l.candidates_generated for l in res.levels if l.k >= 2),
            "candidates_pruned": res.total_pruned,
            "candidates_counted": sum(l.candidates_counted for l in res.levels if l.k >= 2),
            "seconds": round(seconds, 3),
        })
        print(f"  support {s:.4f}: {rows[-1]}", flush=True)
    return rows


def plot_support(rows: list[dict]) -> list[str]:
    x = [r["min_support"] * 100 for r in rows]
    names = []

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for key, label, color in (("frequent_1", "1-itemsets", BLUE), ("frequent_2", "2-itemsets", ORANGE),
                              ("frequent_3plus", "3+-itemsets", AQUA)):
        y = [r[key] or math.nan for r in rows]   # zero cannot be drawn on a log axis: leave a gap
        ax.plot(x, y, marker="o", markersize=6, linewidth=2, color=color, label=label)
    ax.set_yscale("log")
    _style_axes(ax, "Frequent itemsets by size vs minimum support (gaps = zero itemsets)",
                "Minimum support (%)", "Frequent itemsets (log scale)")
    ax.legend(frameon=False)
    names.append(_save(fig, "fig1_support_vs_frequent_itemsets.png"))

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(x, [r["candidates_generated"] for r in rows], marker="o", linewidth=2, color=BLUE,
            label="Generated by join (C_k before pruning)")
    ax.plot(x, [r["candidates_counted"] for r in rows], marker="s", linewidth=2, color=ORANGE,
            label="Counted (after pruning)")
    ax.set_yscale("log")
    _style_axes(ax, "Candidate itemsets (k >= 2) vs minimum support",
                "Minimum support (%)", "Candidate itemsets (log scale)")
    ax.legend(frameon=False)
    names.append(_save(fig, "fig2_support_vs_candidates.png"))

    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(x, [r["seconds"] for r in rows], marker="o", linewidth=2, color=BLUE)
    for xi, r in zip(x, rows):
        ax.annotate(f"{r['seconds']:.2f}s", (xi, r["seconds"]), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8, color=MUTED)
    _style_axes(ax, "A-Priori execution time vs minimum support", "Minimum support (%)", "Seconds (median of 3)")
    names.append(_save(fig, "fig3_support_vs_time.png"))
    return names


# ---------------------------------------------------------------------------
# Experiment 2 - confidence
# ---------------------------------------------------------------------------
def run_confidence_experiment(result: AprioriResult) -> tuple[list[dict], dict[str, list[dict]]]:
    rows, top_rules = [], {}
    for c in CONFIDENCE_THRESHOLDS:
        rules = generate_rules(result, c)
        summary = rule_summary(rules)
        by_size = {}
        for r in rules:
            n = len(r.antecedent) + len(r.consequent)
            by_size[n] = by_size.get(n, 0) + 1
        strongest = rules[0] if rules else None
        rows.append({
            "min_confidence": c,
            "rules": summary["rules"],
            "rules_from_pairs": by_size.get(2, 0),
            "rules_from_3plus": sum(v for k, v in by_size.items() if k >= 3),
            "avg_confidence": summary["avg_confidence"],
            "avg_lift": summary["avg_lift"],
            "min_lift": summary["min_lift"],
            "strongest_rule": (f"{format_itemset(strongest.antecedent)} -> {format_itemset(strongest.consequent)}"
                               if strongest else ""),
        })
        top_rules[str(c)] = [r.as_dict() for r in rules[:10]]
    return rows, top_rules


def plot_confidence(rows: list[dict]) -> list[str]:
    labels = _pct([r["min_confidence"] for r in rows])
    fig, ax = plt.subplots(figsize=(7, 4.2))
    bars = ax.bar(labels, [r["rules"] for r in rows], color=BLUE, width=0.6)
    ax.bar_label(bars, padding=3, fontsize=8, color=MUTED)
    _style_axes(ax, f"Association rules vs minimum confidence (support = {REFERENCE_SUPPORT:.0%})",
                "Minimum confidence", "Number of rules")
    return [_save(fig, "fig4_confidence_vs_rules.png")]


# ---------------------------------------------------------------------------
# Experiment 3 - pruning (monotonicity)
# ---------------------------------------------------------------------------
def run_pruning_experiment(result: AprioriResult) -> dict:
    """Per-level candidate counts at the reference support, compared with brute force.

    "Brute force" is the number of k-itemsets that would have to be counted if every
    combination of the distinct items were considered, i.e. C(n_items, k).
    """
    n_items = len(result.item_names)
    levels = []
    for lv in result.levels:
        brute = math.comb(n_items, lv.k)
        levels.append({
            "k": lv.k,
            "brute_force_itemsets": brute,
            "generated_by_join": lv.candidates_generated,
            "pruned_by_subset_check": lv.candidates_pruned,
            "counted_after_pruning": lv.candidates_counted,
            "frequent": lv.frequent_itemsets,
            "pruned_pct_of_join": round(100 * lv.candidates_pruned / lv.candidates_generated, 1)
            if lv.candidates_generated else 0.0,
            "counted_pct_of_brute_force": _share(lv.candidates_counted, brute),
            "seconds": round(lv.seconds, 3),
        })
    return {"min_support": result.min_support, "min_count": result.min_count, "n_items": n_items,
            "levels": levels, "examples": result.pruned_examples}


def plot_pruning(pruning: dict) -> list[str]:
    levels = [lv for lv in pruning["levels"] if lv["k"] >= 2]
    ks = [lv["k"] for lv in levels]
    width = 0.26
    fig, ax = plt.subplots(figsize=(7, 4.2))
    series = (("generated_by_join", "Generated by join", BLUE),
              ("counted_after_pruning", "Counted after pruning", ORANGE),
              ("frequent", "Frequent (L_k)", AQUA))
    for i, (key, label, color) in enumerate(series):
        xs = [k + (i - 1) * width for k in ks]
        ax.bar(xs, [lv[key] or math.nan for lv in levels], width=width - 0.03, color=color, label=label)
    ax.set_yscale("log")
    ax.set_xticks(ks, [f"k = {k}" for k in ks])
    _style_axes(ax, f"Candidates per level before/after pruning (support = {pruning['min_support']:.0%})",
                "Itemset size", "Itemsets (log scale)")
    ax.legend(frameon=False)
    return [_save(fig, "fig5_pruning_per_level.png")]


# ---------------------------------------------------------------------------
# Experiment 4 - scalability
# ---------------------------------------------------------------------------
def run_scalability_experiment(transactions) -> list[dict]:
    order = list(range(len(transactions)))
    random.Random(RANDOM_SEED).shuffle(order)
    sizes = [s for s in SCALABILITY_SIZES if s < len(transactions)] + [len(transactions)]
    rows = []
    for n in sizes:
        # Nested random samples: every sample contains all baskets of the smaller ones.
        sample = [transactions[i] for i in order[:n]]
        encoded = encode_transactions(sample)
        res, seconds = timed_apriori(sample, REFERENCE_SUPPORT, encoded)
        rows.append({
            "transactions": n,
            "min_support_count": res.min_count,
            "distinct_items": len(res.item_names),
            "item_occurrences": sum(len(b) for b in encoded[0]),
            "candidates_counted": sum(l.candidates_counted for l in res.levels if l.k >= 2),
            "frequent_itemsets": len(res.frequent),
            "seconds": round(seconds, 3),
            "ms_per_1000_transactions": round(1000 * seconds / (n / 1000), 1),
        })
        print(f"  n={n}: {rows[-1]}", flush=True)
    return rows


def plot_scalability(rows: list[dict]) -> list[str]:
    x = [r["transactions"] for r in rows]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(x, [r["seconds"] for r in rows], marker="o", linewidth=2, color=BLUE)
    for r in rows:
        ax.annotate(f"{r['seconds']:.2f}s", (r["transactions"], r["seconds"]), textcoords="offset points",
                    xytext=(0, 8), ha="center", fontsize=8, color=MUTED)
    ax.set_xlim(0, max(x) * 1.05)
    ax.set_ylim(0, max(r["seconds"] for r in rows) * 1.2)
    _style_axes(ax, f"Execution time vs number of transactions (support = {REFERENCE_SUPPORT:.0%})",
                "Transactions (baskets)", "Seconds (median of 3)")
    return [_save(fig, "fig6_scalability_time.png")]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def _write_table(rows: list[dict], name: str) -> None:
    save_csv(rows, TABLES_DIR / f"{name}.csv")
    (TABLES_DIR / f"{name}.md").write_text(markdown_table(rows) + "\n", encoding="utf-8")


def run_all() -> dict:
    ensure_dirs()
    transactions = load_transactions()
    encoded = encode_transactions(transactions)
    dataset = load_dataset_summary()

    print("Experiment 1: minimum support")
    support_rows = run_support_experiment(transactions, encoded)

    print("Reference run (support = 1%)")
    reference, ref_seconds = timed_apriori(transactions, REFERENCE_SUPPORT, encoded)

    print("Experiment 2: confidence")
    confidence_rows, top_rules_by_conf = run_confidence_experiment(reference)

    print("Experiment 3: pruning")
    pruning = run_pruning_experiment(reference)

    print("Experiment 4: scalability")
    scalability_rows = run_scalability_experiment(transactions)

    top_itemsets = reference.top_itemsets(25, min_size=2)
    top_rules = [r.as_dict() for r in generate_rules(reference, REFERENCE_CONFIDENCE)[:25]]
    top_lift_rules = sorted((r.as_dict() for r in generate_rules(reference, REFERENCE_CONFIDENCE)),
                            key=lambda r: -r["lift"])[:10]

    figures = (plot_support(support_rows) + plot_confidence(confidence_rows)
               + plot_pruning(pruning) + plot_scalability(scalability_rows))

    # ---- save tables -------------------------------------------------------
    _write_table(support_rows, "support_experiment")
    _write_table(confidence_rows, "confidence_experiment")
    _write_table(pruning["levels"], "pruning_experiment")
    _write_table(scalability_rows, "scalability_experiment")
    _write_table(reference.level_table(), "apriori_levels_reference")
    flat = lambda rows: [r | {"itemset": format_itemset(r["itemset"])} for r in rows]  # noqa: E731
    _write_table(flat(top_itemsets), "top_itemsets")
    flat_rule = lambda rows: [  # noqa: E731
        r | {"antecedent": format_itemset(r["antecedent"]), "consequent": format_itemset(r["consequent"])}
        for r in rows]
    _write_table(flat_rule(top_rules), "top_rules")
    _write_table(flat_rule(top_lift_rules), "top_rules_by_lift")

    results = {
        "environment": environment_info(),
        "dataset": {"transactions": len(transactions), "unique_items": len(encoded[1]),
                    "raw_rows": dataset["raw_quality"]["rows"]},
        "settings": {"support_thresholds": SUPPORT_THRESHOLDS, "reference_support": REFERENCE_SUPPORT,
                     "confidence_thresholds": CONFIDENCE_THRESHOLDS,
                     "reference_confidence": REFERENCE_CONFIDENCE, "repeats": REPEATS,
                     "random_seed": RANDOM_SEED},
        "support_experiment": support_rows,
        "confidence_experiment": confidence_rows,
        "top_rules_by_confidence_threshold": top_rules_by_conf,
        "pruning_experiment": pruning,
        "scalability_experiment": scalability_rows,
        "reference_run": {"seconds": round(ref_seconds, 3), "levels": reference.level_table(),
                          "by_size": reference.count_by_size(), "total_frequent": len(reference.frequent)},
        "top_itemsets": top_itemsets,
        "top_rules": top_rules,
        "top_rules_by_lift": top_lift_rules,
        "figures": figures,
    }
    save_json(results, JSON_DIR / "analysis_summary.json")
    for key in ("support_experiment", "confidence_experiment", "pruning_experiment", "scalability_experiment"):
        save_json(results[key], JSON_DIR / f"{key}.json")
    return results


if __name__ == "__main__":
    out = run_all()
    print("\nSaved results to results/ (json, tables, figures).")
    print("Figures:", ", ".join(out["figures"]))
