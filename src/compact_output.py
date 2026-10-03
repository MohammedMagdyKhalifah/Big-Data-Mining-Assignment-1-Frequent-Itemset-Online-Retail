"""Compacting the output of A-Priori: maximal and closed frequent itemsets (MMDS §6.1, slides 18-19).

* An itemset is **maximal** if it is frequent and no immediate superset is frequent.
* An itemset is **closed** if no immediate superset has the same support count.
  Only frequent closed itemsets are reported here. A superset with the same count as a
  frequent itemset is itself frequent, so it is enough to look among the frequent itemsets.

Every frequent itemset is a subset of some maximal one (so maximal sets describe *which*
sets are frequent), and every frequent itemset's count equals the count of its smallest
closed superset (so closed sets keep the exact counts as well).
"""

from __future__ import annotations

from collections import defaultdict

Itemset = tuple[int, ...]


def immediate_supersets(frequent: dict[Itemset, int]) -> dict[Itemset, list[Itemset]]:
    """For every frequent itemset, its frequent supersets with exactly one more item."""
    supersets: dict[Itemset, list[Itemset]] = defaultdict(list)
    for itemset in frequent:
        if len(itemset) < 2:
            continue
        for drop in range(len(itemset)):
            subset = itemset[:drop] + itemset[drop + 1:]
            supersets[subset].append(itemset)   # subset is frequent by monotonicity
    return supersets


def maximal_and_closed(frequent: dict[Itemset, int]) -> tuple[set[Itemset], set[Itemset]]:
    """Return (maximal, closed) subsets of the frequent itemsets."""
    sup = immediate_supersets(frequent)
    maximal = {s for s in frequent if not sup.get(s)}
    closed = {s for s, c in frequent.items() if all(frequent[t] != c for t in sup.get(s, []))}
    return maximal, closed
