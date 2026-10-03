"""A manual, level-wise implementation of the A-Priori algorithm.

Terminology (Leskovec, Rajaraman & Ullman, *Mining of Massive Datasets*, Ch. 6):

* C_k : candidate k-itemsets that must be counted in pass k
* L_k : frequent k-itemsets, i.e. candidates whose support count >= the threshold

Each pass k performs four clearly separated steps:

1. **Join**   - combine pairs of frequent (k-1)-itemsets that share their first k-2 items.
2. **Prune**  - drop any candidate that has an infrequent (k-1)-subset (monotonicity).
3. **Count**  - one scan over the baskets to count the surviving candidates.
4. **Filter** - keep candidates with count >= minimum support count  ->  L_k.

The algorithm stops when L_k is empty (no candidates can be formed for k+1).

Items are mapped to integers before mining, and every itemset is stored as a *sorted
tuple of integers*. Sorted tuples make the join step a simple prefix comparison and make
itemsets hashable so they can be used as dictionary keys for counting.
"""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from itertools import combinations
from typing import Iterable, Sequence

Itemset = tuple[int, ...]


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------
@dataclass
class LevelStats:
    """Statistics for one pass (level k) of A-Priori."""

    k: int
    candidates_generated: int      # |C_k| straight after the join step
    candidates_pruned: int         # removed by the subset (monotonicity) check
    candidates_counted: int        # |C_k| after pruning = candidates whose support is counted
    frequent_itemsets: int         # |L_k|
    seconds: float                 # wall-clock time for join + prune + count + filter


@dataclass
class AprioriResult:
    """Everything produced by one run of :func:`apriori`."""

    n_transactions: int
    min_support: float
    min_count: int
    item_names: list[str]
    frequent: dict[Itemset, int]                  # all frequent itemsets -> support count
    levels: list[LevelStats]
    pruned_examples: list[dict] = field(default_factory=list)
    total_seconds: float = 0.0

    # -- convenience accessors --------------------------------------------
    def support(self, itemset: Itemset) -> float:
        return self.frequent[itemset] / self.n_transactions

    def names(self, itemset: Iterable[int]) -> tuple[str, ...]:
        return tuple(self.item_names[i] for i in itemset)

    def count_by_size(self) -> dict[int, int]:
        sizes = Counter(len(s) for s in self.frequent)
        return dict(sorted(sizes.items()))

    @property
    def total_candidates(self) -> int:
        return sum(level.candidates_counted for level in self.levels)

    @property
    def total_pruned(self) -> int:
        return sum(level.candidates_pruned for level in self.levels)

    def top_itemsets(self, n: int = 20, min_size: int = 1) -> list[dict]:
        """The ``n`` frequent itemsets with the highest support (ties broken by name)."""
        rows = [(s, c) for s, c in self.frequent.items() if len(s) >= min_size]
        rows.sort(key=lambda sc: (-sc[1], self.names(sc[0])))
        return [
            {"itemset": list(self.names(s)), "size": len(s), "support_count": c,
             "support": round(c / self.n_transactions, 5)}
            for s, c in rows[:n]
        ]

    def level_table(self) -> list[dict]:
        return [asdict(level) | {"seconds": round(level.seconds, 4)} for level in self.levels]


# ---------------------------------------------------------------------------
# Step 0: transaction preparation
# ---------------------------------------------------------------------------
def encode_transactions(transactions: Sequence[Iterable[str]]) -> tuple[list[Itemset], list[str]]:
    """Map item names to integer ids (alphabetical order) and each basket to a sorted id tuple.

    Integer ids are the compact basket representation recommended in MMDS §6.2.2.
    """
    item_names = sorted({item for t in transactions for item in t})
    index = {name: i for i, name in enumerate(item_names)}
    encoded = [tuple(sorted({index[item] for item in t})) for t in transactions]
    return encoded, item_names


def min_support_count(min_support: float, n_transactions: int) -> int:
    """Convert a relative threshold s into an absolute count: ceil(s * N).

    An itemset I is frequent when support_count(I) / N >= s, i.e. support_count(I) >= s * N.
    The small epsilon protects against floating-point results such as 0.01 * 300 = 3.0000000000000004.
    """
    if not 0 < min_support <= 1:
        raise ValueError("min_support must be in (0, 1]")
    return max(1, math.ceil(min_support * n_transactions - 1e-9))


# ---------------------------------------------------------------------------
# Pass 1: frequent single items
# ---------------------------------------------------------------------------
def count_item_support(encoded: Sequence[Itemset]) -> Counter:
    """Support count of every individual item (C_1): one scan over the baskets."""
    counts: Counter = Counter()
    for basket in encoded:
        counts.update(basket)
    return counts


def frequent_1_itemsets(item_counts: Counter, min_count: int) -> dict[Itemset, int]:
    """L_1: single items whose support count reaches the threshold."""
    return {(item,): c for item, c in item_counts.items() if c >= min_count}


# ---------------------------------------------------------------------------
# Pass k >= 2: candidate generation (join + prune)
# ---------------------------------------------------------------------------
def apriori_join(prev_frequent: Iterable[Itemset]) -> list[Itemset]:
    """Join step: build C_k from L_{k-1}.

    Two frequent (k-1)-itemsets are joined when they agree on their first k-2 items
    (their "prefix"); the new candidate is the prefix plus both last items.
    Example (k=3): {A,B} and {A,C} share prefix {A}  ->  candidate {A,B,C}.
    For k=2 the prefix is empty, so every pair of frequent items is produced.
    """
    by_prefix: dict[Itemset, list[int]] = defaultdict(list)
    for itemset in prev_frequent:
        by_prefix[itemset[:-1]].append(itemset[-1])

    candidates: list[Itemset] = []
    for prefix, last_items in by_prefix.items():
        last_items.sort()
        for a, b in combinations(last_items, 2):     # a < b, so the result stays sorted
            candidates.append(prefix + (a, b))
    return candidates


def find_infrequent_subset(candidate: Itemset, prev_frequent: set[Itemset]) -> Itemset | None:
    """Return one (k-1)-subset of ``candidate`` that is NOT frequent, or None if all are.

    The two subsets obtained by dropping the last or second-to-last item are the ones the
    join step started from, so they are frequent by construction; the check therefore
    only needs to look at the subsets that drop one of the first k-2 items.
    """
    k = len(candidate)
    for drop in range(k - 2):
        subset = candidate[:drop] + candidate[drop + 1:]
        if subset not in prev_frequent:
            return subset
    return None


def prune_candidates(candidates: Iterable[Itemset], prev_frequent: set[Itemset],
                     examples: list[dict] | None = None, max_examples: int = 0
                     ) -> tuple[list[Itemset], int]:
    """Prune step (A-Priori / monotonicity property).

    If an itemset is frequent, every one of its subsets is frequent. Contrapositive: if
    ANY (k-1)-subset of a candidate is infrequent, the candidate cannot be frequent, so it
    is removed here *without ever counting it* in the data.

    Returns the surviving candidates and the number pruned. When ``examples`` is given,
    up to ``max_examples`` pruned candidates are stored together with the infrequent
    subset that justified removing them.
    """
    kept: list[Itemset] = []
    pruned = 0
    for cand in candidates:
        bad_subset = find_infrequent_subset(cand, prev_frequent)
        if bad_subset is None:
            kept.append(cand)
        else:
            # PRUNING HAPPENS HERE: cand has an infrequent subset -> cannot be frequent.
            pruned += 1
            if examples is not None and len(examples) < max_examples:
                examples.append({"candidate": cand, "infrequent_subset": bad_subset})
    return kept, pruned


def generate_candidates(prev_frequent: dict[Itemset, int], examples: list[dict] | None = None,
                        max_examples: int = 0) -> tuple[list[Itemset], int, int]:
    """C_k = prune(join(L_{k-1})). Returns (candidates, generated_by_join, pruned)."""
    joined = apriori_join(prev_frequent.keys())
    kept, pruned = prune_candidates(joined, set(prev_frequent), examples, max_examples)
    return kept, len(joined), pruned


# ---------------------------------------------------------------------------
# Pass k >= 2: support counting and filtering
# ---------------------------------------------------------------------------
def count_candidates(encoded: Sequence[Itemset], candidates: Sequence[Itemset], k: int) -> dict[Itemset, int]:
    """Count the support of each candidate k-itemset with one scan over the baskets.

    For each basket we first discard items that appear in no candidate (they cannot
    contribute). Then we use whichever of two equivalent strategies is cheaper:

    * enumerate the k-subsets of the basket and look each one up in the candidate hash
      table (cheap for ordinary baskets), or
    * test every candidate for containment in the basket (cheaper for the few very large
      wholesale baskets, where C(|basket|, k) would exceed the number of candidates).
    """
    counts: dict[Itemset, int] = dict.fromkeys(candidates, 0)
    if not counts:
        return counts
    relevant_items = {item for cand in candidates for item in cand}
    n_candidates = len(counts)

    for basket in encoded:
        items = [i for i in basket if i in relevant_items]   # stays sorted
        if len(items) < k:
            continue
        if math.comb(len(items), k) <= n_candidates:
            for subset in combinations(items, k):
                if subset in counts:
                    counts[subset] += 1
        else:
            basket_set = set(items)
            for cand in counts:
                if basket_set.issuperset(cand):
                    counts[cand] += 1
    return counts


def filter_frequent(counts: dict[Itemset, int], min_count: int) -> dict[Itemset, int]:
    """L_k: candidates whose support count is at least the minimum support count."""
    return {itemset: c for itemset, c in counts.items() if c >= min_count}


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def apriori(transactions: Sequence[Iterable[str]], min_support: float, max_k: int | None = None,
            max_pruned_examples: int = 5, encoded: tuple[list[Itemset], list[str]] | None = None
            ) -> AprioriResult:
    """Mine all frequent itemsets with support >= ``min_support``.

    Parameters
    ----------
    transactions : baskets, each an iterable of item names
    min_support : relative minimum support s, 0 < s <= 1
    max_k : optional maximum itemset size (None = run until L_k is empty)
    max_pruned_examples : how many pruned candidates to keep as evidence of pruning
    encoded : pre-computed output of :func:`encode_transactions` (saves time in experiments)
    """
    start = time.perf_counter()
    baskets, item_names = encoded if encoded is not None else encode_transactions(transactions)
    n = len(baskets)
    min_count = min_support_count(min_support, n)

    # ---- Pass 1: C_1 = all distinct items, L_1 = frequent items ----------
    t0 = time.perf_counter()
    item_counts = count_item_support(baskets)
    current = frequent_1_itemsets(item_counts, min_count)
    levels = [LevelStats(1, len(item_counts), 0, len(item_counts), len(current), time.perf_counter() - t0)]
    frequent: dict[Itemset, int] = dict(current)
    pruned_examples: list[dict] = []

    # ---- Passes k = 2, 3, ...: C_k from L_{k-1}, then count -> L_k -------
    k = 2
    while current and (max_k is None or k <= max_k):
        t0 = time.perf_counter()
        candidates, generated, pruned = generate_candidates(current, pruned_examples, max_pruned_examples)
        counts = count_candidates(baskets, candidates, k)
        current = filter_frequent(counts, min_count)
        frequent.update(current)
        if generated == 0:
            break   # L_{k-1} could not be joined: no level k exists
        levels.append(LevelStats(k, generated, pruned, len(candidates), len(current), time.perf_counter() - t0))
        k += 1

    result = AprioriResult(n, min_support, min_count, item_names, frequent, levels,
                           total_seconds=time.perf_counter() - start)
    result.pruned_examples = [
        {
            "candidate": list(result.names(ex["candidate"])),
            "infrequent_subset": list(result.names(ex["infrequent_subset"])),
            "infrequent_subset_count": _count_itemset(baskets, ex["infrequent_subset"]),
        }
        for ex in pruned_examples
    ]
    return result


def _count_itemset(encoded: Sequence[Itemset], itemset: Itemset) -> int:
    """Support count of a single itemset (used only to document pruned examples)."""
    target = set(itemset)
    return sum(1 for basket in encoded if target.issubset(basket))
