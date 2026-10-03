"""Unit tests for the manual A-Priori and association-rule implementation.

The tests use a tiny synthetic dataset whose answers can be checked by hand, plus a
brute-force cross-check on random baskets. They do not need the real Online Retail data.
"""

from __future__ import annotations

import random
from itertools import combinations

import pytest

from src.apriori import (
    apriori,
    apriori_join,
    count_candidates,
    count_item_support,
    encode_transactions,
    filter_frequent,
    find_infrequent_subset,
    frequent_1_itemsets,
    min_support_count,
    prune_candidates,
)
from src.association_rules import generate_rules

# Ten small baskets. Hand-computed support counts:
#   Bread 7, Milk 7, Eggs 6, Butter 4, Jam 2
#   {Bread,Milk} 4, {Bread,Eggs} 4, {Milk,Eggs} 4, {Bread,Butter} 4,
#   {Milk,Butter} 2, {Eggs,Butter} 2, {Milk,Jam} 2, {Eggs,Jam} 1, {Bread,Jam} 0
#   {Bread,Milk,Eggs} 2, {Bread,Milk,Butter} 2, {Bread,Eggs,Butter} 2, {Milk,Eggs,Butter} 1
BASKETS = [
    {"Bread", "Milk"},
    {"Bread", "Eggs", "Butter"},
    {"Milk", "Eggs", "Jam"},
    {"Bread", "Milk", "Eggs"},
    {"Bread", "Milk", "Butter"},
    {"Bread", "Eggs"},
    {"Milk", "Jam"},
    {"Bread", "Milk", "Eggs", "Butter"},
    {"Bread", "Butter"},
    {"Milk", "Eggs"},
]


@pytest.fixture
def encoded():
    return encode_transactions(BASKETS)


def ids(item_names, *names):
    """Sorted id tuple for the given item names."""
    return tuple(sorted(item_names.index(n) for n in names))


def test_encoding_is_alphabetical_and_sorted(encoded):
    baskets, names = encoded
    assert names == ["Bread", "Butter", "Eggs", "Jam", "Milk"]
    assert all(list(b) == sorted(b) for b in baskets)


def test_min_support_count_rounds_up():
    assert min_support_count(0.3, 10) == 3
    assert min_support_count(0.25, 10) == 3      # 2.5 -> 3
    assert min_support_count(0.01, 300) == 3     # float noise must not give 4
    with pytest.raises(ValueError):
        min_support_count(0, 10)


def test_item_support_counts(encoded):
    baskets, names = encoded
    counts = count_item_support(baskets)
    assert {names[i]: c for i, c in counts.items()} == {"Bread": 7, "Milk": 7, "Eggs": 6, "Butter": 4, "Jam": 2}


def test_frequent_1_itemsets(encoded):
    baskets, names = encoded
    l1 = frequent_1_itemsets(count_item_support(baskets), min_count=3)
    assert {names[s[0]] for s in l1} == {"Bread", "Milk", "Eggs", "Butter"}   # Jam (2) is dropped


def test_join_builds_all_pairs_from_l1():
    l1 = [(0,), (1,), (2,)]
    assert sorted(apriori_join(l1)) == [(0, 1), (0, 2), (1, 2)]


def test_join_only_combines_itemsets_with_same_prefix():
    l2 = [(0, 1), (0, 2), (1, 2), (1, 3)]
    # (0,1)+(0,2) -> (0,1,2); (1,2)+(1,3) -> (1,2,3); (0,*) never joins with (1,*)
    assert sorted(apriori_join(l2)) == [(0, 1, 2), (1, 2, 3)]


def test_pruning_removes_candidate_with_infrequent_subset():
    l2 = {(0, 1), (0, 2), (1, 2), (1, 3)}          # (2,3) is NOT frequent
    assert find_infrequent_subset((0, 1, 2), l2) is None
    assert find_infrequent_subset((1, 2, 3), l2) == (2, 3)
    examples: list = []
    kept, pruned = prune_candidates([(0, 1, 2), (1, 2, 3)], l2, examples, max_examples=5)
    assert kept == [(0, 1, 2)]
    assert pruned == 1
    assert examples == [{"candidate": (1, 2, 3), "infrequent_subset": (2, 3)}]


def test_count_candidates_both_strategies_agree(encoded):
    baskets, names = encoded
    cands = [ids(names, "Bread", "Milk"), ids(names, "Eggs", "Butter"), ids(names, "Milk", "Jam")]
    counts = count_candidates(baskets, cands, 2)
    assert counts[ids(names, "Bread", "Milk")] == 4
    assert counts[ids(names, "Eggs", "Butter")] == 2
    assert counts[ids(names, "Milk", "Jam")] == 2
    # A single candidate forces the "test each candidate" branch for baskets with >2 items.
    single = count_candidates(baskets, [ids(names, "Bread", "Milk")], 2)
    assert single[ids(names, "Bread", "Milk")] == 4


def test_filter_frequent():
    assert filter_frequent({(0, 1): 4, (0, 2): 2}, 3) == {(0, 1): 4}


def test_full_apriori_result():
    res = apriori(BASKETS, min_support=0.2)            # min count = 2
    named = {frozenset(res.names(s)): c for s, c in res.frequent.items()}
    expected = {
        frozenset({"Bread"}): 7, frozenset({"Milk"}): 7, frozenset({"Eggs"}): 6,
        frozenset({"Butter"}): 4, frozenset({"Jam"}): 2,
        frozenset({"Bread", "Milk"}): 4, frozenset({"Bread", "Eggs"}): 4,
        frozenset({"Milk", "Eggs"}): 4, frozenset({"Bread", "Butter"}): 4,
        frozenset({"Milk", "Butter"}): 2, frozenset({"Eggs", "Butter"}): 2,
        frozenset({"Milk", "Jam"}): 2,
        frozenset({"Bread", "Milk", "Eggs"}): 2, frozenset({"Bread", "Milk", "Butter"}): 2,
        frozenset({"Bread", "Eggs", "Butter"}): 2,
    }
    assert named == expected
    assert res.min_count == 2
    # Level 3: the join makes 4 candidates, none pruned, 3 frequent ({Milk,Eggs,Butter} has count 1).
    level3 = res.levels[2]
    assert (level3.candidates_generated, level3.candidates_pruned, level3.frequent_itemsets) == (4, 0, 3)
    # Level 4: {Bread,Butter,Eggs,Milk} is joined but pruned, because its subset
    # {Butter,Eggs,Milk} is not frequent - it is never counted in the data.
    level4 = res.levels[3]
    assert (level4.candidates_generated, level4.candidates_pruned, level4.candidates_counted) == (1, 1, 0)
    assert res.pruned_examples[0]["infrequent_subset"] == ["Butter", "Eggs", "Milk"]
    assert res.pruned_examples[0]["infrequent_subset_count"] == 1


def test_monotonicity_every_subset_of_a_frequent_itemset_is_frequent():
    res = apriori(BASKETS, min_support=0.2)
    for itemset in res.frequent:
        for r in range(1, len(itemset)):
            for sub in combinations(itemset, r):
                assert sub in res.frequent
                assert res.frequent[sub] >= res.frequent[itemset]


def test_rule_confidence_and_lift():
    res = apriori(BASKETS, min_support=0.2)
    rules = {(r.antecedent, r.consequent): r for r in generate_rules(res, min_confidence=0.0)}
    r = rules[(("Eggs",), ("Bread",))]
    assert r.confidence == pytest.approx(4 / 6)             # count{Bread,Eggs} / count{Eggs}
    assert r.support == pytest.approx(4 / 10)
    assert r.lift == pytest.approx((4 / 6) / (7 / 10))
    assert rules[(("Butter",), ("Bread",))].confidence == pytest.approx(1.0)   # every Butter basket has Bread
    r2 = rules[(("Bread", "Milk"), ("Eggs",))]
    assert r2.confidence == pytest.approx(2 / 4)
    # Antecedent and consequent are always disjoint and non-empty.
    assert all(set(a).isdisjoint(c) and a and c for a, c in rules)


def test_higher_confidence_threshold_gives_subset_of_rules():
    res = apriori(BASKETS, min_support=0.2)
    low = {(r.antecedent, r.consequent) for r in generate_rules(res, 0.3)}
    high = {(r.antecedent, r.consequent) for r in generate_rules(res, 0.7)}
    assert high <= low
    assert all(r.confidence >= 0.7 for r in generate_rules(res, 0.7))


def brute_force_frequent(baskets, min_count):
    """Reference answer: count every possible itemset (only feasible for tiny data)."""
    items = sorted({i for b in baskets for i in b})
    result = {}
    for k in range(1, len(items) + 1):
        found = False
        for combo in combinations(items, k):
            c = sum(1 for b in baskets if set(combo) <= b)
            if c >= min_count:
                result[frozenset(combo)] = c
                found = True
        if not found:
            break
    return result


@pytest.mark.parametrize("seed", range(5))
def test_matches_brute_force_on_random_data(seed):
    rng = random.Random(seed)
    items = [f"item{i}" for i in range(9)]
    baskets = [set(rng.sample(items, rng.randint(1, 6))) for _ in range(60)]
    res = apriori(baskets, min_support=0.15)
    mined = {frozenset(res.names(s)): c for s, c in res.frequent.items()}
    assert mined == brute_force_frequent(baskets, res.min_count)
