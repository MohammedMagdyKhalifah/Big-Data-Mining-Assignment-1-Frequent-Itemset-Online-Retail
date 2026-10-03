"""Tests for the Chapter 6 extensions: lecture examples, triangular matrix, PCY family,
interest, maximal/closed itemsets. No real dataset needed."""

from __future__ import annotations

import random
from itertools import combinations

import pytest

from src.apriori import apriori, encode_transactions, min_support_count
from src.association_rules import generate_rules
from src.compact_output import maximal_and_closed
from src.pcy import (
    multihash, multistage, pcy, triangular_frequent_pairs, triangular_index, triangular_pair_counts,
)

# Lecture slides 11 and 14 (MMDS Example 6.1): 8 baskets, support threshold 3 baskets.
SLIDE_BASKETS = [
    {"m", "c", "b"}, {"m", "p", "j"}, {"m", "b"}, {"c", "j"},
    {"m", "p", "b"}, {"m", "c", "b", "j"}, {"c", "b", "j"}, {"b", "c"},
]


def named(result):
    return {frozenset(result.names(s)) for s in result.frequent}


def test_slide_example_frequent_itemsets():
    res = apriori(SLIDE_BASKETS, 3 / 8)
    assert res.min_count == 3
    expected = [{"m"}, {"c"}, {"b"}, {"j"}, {"m", "b"}, {"b", "c"}, {"c", "j"}]
    assert named(res) == {frozenset(e) for e in expected}


def test_slide_example_confidence_and_interest():
    # {m,b} -> c has support 2 < 3, so lower the threshold to 2 baskets to get the rule.
    res = apriori(SLIDE_BASKETS, 2 / 8)
    rule = next(r for r in generate_rules(res, 0.0)
                if set(r.antecedent) == {"b", "m"} and r.consequent == ("c",))
    assert rule.confidence == pytest.approx(2 / 4)
    assert rule.interest == pytest.approx(0.5 - 5 / 8)     # slide 14: |interest| = 1/8


def test_triangular_index_is_a_bijection():
    n = 7
    positions = [triangular_index(i, j, n) for i in range(1, n) for j in range(i + 1, n + 1)]
    assert positions == list(range(1, n * (n - 1) // 2 + 1))


def random_baskets(seed=1, n=300, items=25):
    rng = random.Random(seed)
    return [set(rng.sample(range(items), rng.randint(1, 9))) for _ in range(n)]


@pytest.mark.parametrize("support", [0.03, 0.06, 0.1])
def test_triangular_counts_match_apriori(support):
    baskets = random_baskets()
    encoded, names = encode_transactions(baskets)
    res = apriori(baskets, support, encoded=(encoded, names))
    min_count = min_support_count(support, len(encoded))
    freq_items = [s[0] for s in res.frequent if len(s) == 1]
    counts, new_id = triangular_pair_counts(encoded, freq_items)
    l2 = triangular_frequent_pairs(counts, new_id, min_count)
    assert l2 == {s: c for s, c in res.frequent.items() if len(s) == 2}


@pytest.mark.parametrize("algo", [pcy, multistage, multihash])
@pytest.mark.parametrize("buckets", [7, 50, 1000])
def test_hashing_algorithms_find_exactly_apriori_pairs(algo, buckets):
    baskets = random_baskets(seed=3)
    encoded, names = encode_transactions(baskets)
    res = apriori(baskets, 0.05, encoded=(encoded, names))
    stats, l2 = algo(encoded, len(names), res.min_count, buckets)
    assert l2 == {s: c for s, c in res.frequent.items() if len(s) == 2}
    # hashing can only remove candidates, never add them
    assert stats.candidate_pairs <= stats.occurring_frequent_item_pairs <= stats.apriori_candidate_pairs


def test_maximal_and_closed_slide_19():
    # Supports from slide 19 with s = 3; only the frequent itemsets are passed in.
    A, B, C = 0, 1, 2
    frequent = {(A,): 4, (B,): 5, (C,): 3, (A, B): 4, (B, C): 3}
    maximal, closed = maximal_and_closed(frequent)
    assert maximal == {(A, B), (B, C)}
    assert closed == {(B,), (A, B), (B, C)}


def test_maximal_and_closed_against_brute_force():
    baskets = random_baskets(seed=5, n=200, items=12)
    res = apriori(baskets, 0.08)
    maximal, closed = maximal_and_closed(res.frequent)
    for s, c in res.frequent.items():
        supers = [t for t in res.frequent if len(t) == len(s) + 1 and set(s) < set(t)]
        assert (s in maximal) == (not supers)
        assert (s in closed) == all(res.frequent[t] != c for t in supers)
    # every frequent itemset is contained in some maximal one
    assert all(any(set(s) <= set(m) for m in maximal) for s in res.frequent)
