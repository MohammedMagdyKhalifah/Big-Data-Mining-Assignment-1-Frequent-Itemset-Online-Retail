"""Experiments 5-9: the Chapter 6 techniques beyond plain A-Priori.

    5. Lecture example check (slides 11, 14, 17, 36)
    6. Pair-counting memory: triangular matrix vs triples (with re-numbering)
    7. PCY / Multistage / Multihash vs A-Priori for frequent pairs (bucket sweep)
    8. Compacting the output: maximal and closed frequent itemsets
    9. Interest of association rules vs confidence and lift

Run with::

    python -m src.chapter6_experiments

Writes results/json/chapter6_summary.json, results/tables/ch6_*.csv|md and figures fig7-fig9.
All counts are deterministic; seconds depend on the machine.
"""

from __future__ import annotations

import math
import statistics
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from src.apriori import apriori, encode_transactions, min_support_count  # noqa: E402
from src.association_rules import generate_rules  # noqa: E402
from src.compact_output import maximal_and_closed  # noqa: E402
from src.experiments import BLUE, GRID, INK, MUTED, ORANGE, AQUA, _save, _style_axes, _write_table  # noqa: E402
from src.pcy import multihash, multistage, pcy, triangular_frequent_pairs, triangular_pair_counts  # noqa: E402
from src.preprocessing import load_transactions  # noqa: E402
from src.utils import JSON_DIR, ensure_dirs, format_itemset, save_json  # noqa: E402
from tests.test_chapter6 import SLIDE_BASKETS  # noqa: E402

REFERENCE_SUPPORT = 0.01
MEMORY_SUPPORTS = [0.005, 0.01, 0.02]
BUCKET_SIZES = [10_000, 100_000, 300_000, 1_000_000, 4_000_000]
PCY_SUPPORTS = [0.005, 0.0075, 0.01, 0.015, 0.02]
PCY_SUPPORT_BUCKETS = 1_000_000
COMPACT_SUPPORTS = [0.005, 0.0075, 0.01, 0.015, 0.02]
REPEATS = 3


def median_run(fn, *args):
    """Run a pair-mining function REPEATS times; keep the last output and the median time."""
    runs = [fn(*args) for _ in range(REPEATS)]
    stats, l2 = runs[-1]
    stats.seconds = statistics.median(r[0].seconds for r in runs)
    return stats, l2


# ---------------------------------------------------------------------------
# 5. Lecture examples
# ---------------------------------------------------------------------------
def lecture_examples() -> dict:
    res = apriori(SLIDE_BASKETS, 3 / 8)
    levels = res.level_table()
    rule_res = apriori(SLIDE_BASKETS, 2 / 8)
    rule = next(r for r in generate_rules(rule_res, 0.0)
                if set(r.antecedent) == {"b", "m"} and r.consequent == ("c",))
    return {
        "frequent_itemsets_s3": sorted(format_itemset(res.names(s)) for s in res.frequent),
        "levels_s3": levels,
        "rule_mb_to_c": {"confidence": rule.confidence, "interest": round(rule.interest, 4)},
    }


# ---------------------------------------------------------------------------
# 6. Triangular matrix vs triples
# ---------------------------------------------------------------------------
def memory_experiment(encoded, names, l2_by_support) -> list[dict]:
    rows = []
    n_all = len(names)
    for s in MEMORY_SUPPORTS:
        min_count = min_support_count(s, len(encoded))
        l2_ref, freq_items = l2_by_support[s]
        t0 = time.perf_counter()
        counts, new_id = triangular_pair_counts(encoded, freq_items)
        l2 = triangular_frequent_pairs(counts, new_id, min_count)
        seconds = time.perf_counter() - t0
        assert l2 == l2_ref, "triangular matrix must reproduce A-Priori's L2"
        m = len(freq_items)
        occurring = int((counts > 0).sum())
        rows.append({
            "min_support": s,
            "frequent_items_m": m,
            "pairs_all_items": math.comb(n_all, 2),
            "triangular_all_items_MB": round(4 * math.comb(n_all, 2) / 1e6, 2),
            "pairs_frequent_items": math.comb(m, 2),
            "triangular_renumbered_MB": round(4 * math.comb(m, 2) / 1e6, 3),
            "occurring_pairs": occurring,
            "occurring_pct": round(100 * occurring / math.comb(m, 2), 1),
            "triples_MB": round(12 * occurring / 1e6, 3),
            "better_method": "triangular" if occurring > math.comb(m, 2) / 3 else "triples",
            "frequent_pairs": len(l2),
            "seconds": round(seconds, 3),
        })
        print("  memory", rows[-1], flush=True)
    return rows


# ---------------------------------------------------------------------------
# 7. PCY family
# ---------------------------------------------------------------------------
def pcy_bucket_experiment(encoded, names, l2_ref, apriori_pass12_seconds) -> list[dict]:
    min_count = min_support_count(REFERENCE_SUPPORT, len(encoded))
    rows = []
    for b in BUCKET_SIZES:
        for algo in (pcy, multistage, multihash):
            stats, l2 = median_run(algo, encoded, len(names), min_count, b)
            assert l2 == l2_ref, f"{stats.algorithm} must find exactly A-Priori's L2"
            row = stats.as_dict()
            row["candidates_vs_apriori_pct"] = round(100 * stats.candidate_pairs / stats.apriori_candidate_pairs, 2)
            row["apriori_seconds"] = round(apriori_pass12_seconds, 3)
            rows.append(row)
            print("  ", row["algorithm"], b, row["candidate_pairs"], row["seconds"], flush=True)
    return rows


def pcy_support_experiment(encoded, names, l2_by_support) -> list[dict]:
    rows = []
    for s in PCY_SUPPORTS:
        min_count = min_support_count(s, len(encoded))
        stats, l2 = median_run(pcy, encoded, len(names), min_count, PCY_SUPPORT_BUCKETS)
        assert l2 == l2_by_support[s][0]
        rows.append({
            "min_support": s, "min_count": min_count, "frequent_items": stats.frequent_items,
            "apriori_candidate_pairs": stats.apriori_candidate_pairs,
            "pcy_candidate_pairs": stats.candidate_pairs,
            "frequent_buckets_pct": round(stats.frequent_buckets_pct, 2),
            "frequent_pairs": stats.frequent_pairs,
            "reduction_factor": round(stats.apriori_candidate_pairs / stats.candidate_pairs, 1),
        })
        print("  pcy support", rows[-1], flush=True)
    return rows


# ---------------------------------------------------------------------------
# 8. Maximal / closed
# ---------------------------------------------------------------------------
def compact_experiment(transactions, encoded) -> list[dict]:
    rows = []
    for s in COMPACT_SUPPORTS:
        res = apriori(transactions, s, encoded=encoded)
        maximal, closed = maximal_and_closed(res.frequent)
        rows.append({"min_support": s, "frequent_itemsets": len(res.frequent),
                     "closed": len(closed), "maximal": len(maximal),
                     "maximal_pct": round(100 * len(maximal) / len(res.frequent), 1)})
        print("  compact", rows[-1], flush=True)
    return rows


def compact_examples(result) -> list[dict]:
    """Concrete frequent itemsets that are / are not closed or maximal, for the report."""
    maximal, closed = maximal_and_closed(result.frequent)
    out = []
    wanted = [("REGENCY TEA PLATE GREEN",), ("REGENCY TEA PLATE GREEN", "REGENCY TEA PLATE PINK"),
              ("REGENCY TEA PLATE GREEN", "REGENCY TEA PLATE PINK", "REGENCY TEA PLATE ROSES"),
              ("HERB MARKER ROSEMARY", "HERB MARKER THYME")]
    index = {n: i for i, n in enumerate(result.item_names)}
    for names in wanted:
        s = tuple(sorted(index[n] for n in names))
        if s in result.frequent:
            supers = [(format_itemset(result.names(t)), c) for t, c in result.frequent.items()
                      if len(t) == len(s) + 1 and set(s) < set(t)]
            out.append({"itemset": format_itemset(names), "count": result.frequent[s],
                        "closed": s in closed, "maximal": s in maximal,
                        "frequent_immediate_supersets": supers})
    return out


# ---------------------------------------------------------------------------
# 9. Interest
# ---------------------------------------------------------------------------
def interest_experiment(result) -> dict:
    rules = generate_rules(result, 0.5)
    high = [r for r in rules if r.interest > 0.5]
    by_conf = rules[:1]
    lowest = sorted(rules, key=lambda r: r.interest)[:5]
    top = sorted(rules, key=lambda r: -r.interest)[:10]
    fmt = lambda r: r.as_dict() | {"antecedent": format_itemset(r.antecedent),  # noqa: E731
                                   "consequent": format_itemset(r.consequent)}
    bands = []
    for lo, hi in ((0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.0)):
        bands.append({"interest_band": f"{lo:.1f}-{hi:.1f}",
                      "rules": sum(1 for r in rules if lo <= r.interest < hi)})
    return {"rules_at_conf_50": len(rules), "rules_interest_gt_0_5": len(high),
            "negative_interest_rules": sum(1 for r in rules if r.interest < 0),
            "min_interest": round(min(r.interest for r in rules), 4),
            "max_interest": round(max(r.interest for r in rules), 4),
            "bands": bands, "top_by_interest": [fmt(r) for r in top],
            "lowest_interest": [fmt(r) for r in lowest],
            "scatter": [{"confidence": round(r.confidence, 4), "interest": round(r.interest, 4),
                         "consequent_support": round(r.confidence - r.interest, 4)} for r in rules],
            "highest_confidence": [fmt(r) for r in by_conf]}


# ---------------------------------------------------------------------------
# Figures
# ---------------------------------------------------------------------------
def plot_buckets(rows, apriori_pairs) -> str:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for name, color in (("PCY", BLUE), ("Multistage", ORANGE), ("Multihash", AQUA)):
        pts = [r for r in rows if r["algorithm"] == name]
        # n_buckets is the total over all tables; Multistage has two full-size tables,
        # so divide by 2 to plot every method against the size of ONE table.
        per_table = [r["n_buckets"] // (2 if name == "Multistage" else 1) for r in pts]
        ax.plot(per_table, [r["candidate_pairs"] for r in pts],
                marker="o", linewidth=2, color=color, label=name)
    ax.axhline(apriori_pairs, color=MUTED, linestyle="--", linewidth=1)
    ax.text(BUCKET_SIZES[0], apriori_pairs * 1.15, f"A-Priori C2 = {apriori_pairs:,} pairs", color=MUTED, fontsize=8)
    ax.set_xscale("log")
    ax.set_yscale("log")
    _style_axes(ax, "Candidate pairs counted in the last pass vs hash-table size (support = 1%)",
                "Buckets per hash table (log scale)", "Candidate pairs (log scale)")
    ax.legend(frameon=False)
    return _save(fig, "fig7_pcy_buckets_vs_candidates.png")


def plot_compact(rows) -> str:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    x = [r["min_support"] * 100 for r in rows]
    for key, label, color in (("frequent_itemsets", "All frequent", BLUE), ("closed", "Closed", ORANGE),
                              ("maximal", "Maximal", AQUA)):
        ax.plot(x, [r[key] for r in rows], marker="o", linewidth=2, color=color, label=label)
    ax.set_yscale("log")
    _style_axes(ax, "Frequent vs closed vs maximal itemsets", "Minimum support (%)", "Itemsets (log scale)")
    ax.legend(frameon=False)
    return _save(fig, "fig8_maximal_closed.png")


def plot_interest(scatter) -> str:
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.scatter([p["confidence"] for p in scatter], [p["interest"] for p in scatter], s=8, color=BLUE, alpha=0.5)
    ax.axhline(0.5, color=MUTED, linestyle="--", linewidth=1)
    ax.plot([0.5, 1], [0.5, 1], color=GRID, linewidth=1)
    ax.text(0.97, 0.475, "interest = 0.5", color=MUTED, fontsize=8, ha="right", va="top")
    _style_axes(ax, "Interest vs confidence for the 962 rules (support 1%, confidence >= 50%)",
                "Confidence", "Interest = confidence - support(Y)")
    ax.title.set_color(INK)
    return _save(fig, "fig9_interest_vs_confidence.png")


# ---------------------------------------------------------------------------
def run_all() -> dict:
    ensure_dirs()
    transactions = load_transactions()
    encoded = encode_transactions(transactions)
    baskets, names = encoded

    print("Experiment 5: lecture examples")
    lecture = lecture_examples()

    # A-Priori reference L2 (and L1) per support, used to verify every other method.
    l2_by_support, ref_results = {}, {}
    for s in sorted(set(MEMORY_SUPPORTS + PCY_SUPPORTS)):
        res = apriori(transactions, s, encoded=encoded, max_k=2)
        l2_by_support[s] = ({k: c for k, c in res.frequent.items() if len(k) == 2},
                            [k[0] for k in res.frequent if len(k) == 1])
        ref_results[s] = res
    apriori_times = [apriori(transactions, REFERENCE_SUPPORT, encoded=encoded, max_k=2).total_seconds
                     for _ in range(REPEATS)]

    print("Experiment 6: triangular matrix vs triples")
    memory = memory_experiment(baskets, names, l2_by_support)

    print("Experiment 7: PCY / Multistage / Multihash")
    buckets = pcy_bucket_experiment(baskets, names, l2_by_support[REFERENCE_SUPPORT][0],
                                    statistics.median(apriori_times))
    pcy_support = pcy_support_experiment(baskets, names, l2_by_support)

    print("Experiment 8: maximal / closed")
    compact = compact_experiment(transactions, encoded)
    full_ref = apriori(transactions, REFERENCE_SUPPORT, encoded=encoded)
    compact_ex = compact_examples(full_ref)

    print("Experiment 9: interest")
    interest = interest_experiment(full_ref)

    figures = [plot_buckets(buckets, buckets[0]["apriori_candidate_pairs"]), plot_compact(compact),
               plot_interest(interest["scatter"])]

    _write_table(memory, "ch6_memory_triangular_vs_triples")
    _write_table(buckets, "ch6_pcy_bucket_sweep")
    _write_table(pcy_support, "ch6_pcy_support_sweep")
    _write_table(compact, "ch6_maximal_closed")
    _write_table(interest["bands"], "ch6_interest_bands")
    _write_table(interest["top_by_interest"], "ch6_top_rules_by_interest")

    out = {"lecture_examples": lecture, "memory": memory, "pcy_buckets": buckets,
           "apriori_pass12_seconds": round(statistics.median(apriori_times), 3),
           "pcy_support": pcy_support, "compact": compact, "compact_examples": compact_ex,
           "interest": {k: v for k, v in interest.items() if k != "scatter"},
           "figures": figures}
    save_json(out, JSON_DIR / "chapter6_summary.json")
    return out


if __name__ == "__main__":
    run_all()
    print("Saved results/json/chapter6_summary.json, ch6_* tables and figures fig7-fig9.")
