"""Memory-saving algorithms for frequent PAIRS from MMDS Chapter 6 (§6.2.2, §6.3).

This module complements :mod:`src.apriori`. A-Priori decides which pairs to count from
the frequent items alone; the algorithms here add hashing so that fewer pairs need a
counter in the pass that counts pairs:

* **Triangular matrix** (§6.2.2): pair counts kept in a 1-D array of n(n-1)/2 integers,
  after re-numbering the frequent items 1..m (the "trick" on the A-Priori slides).
* **PCY** (Park-Chen-Yu, §6.3.1): pass 1 also hashes every pair into a bucket and counts
  the bucket. A bucket whose count is below the threshold cannot hold a frequent pair,
  so pairs that hash there are not counted in pass 2.
* **Multistage** (§6.3.2): an extra pass rehashes only the pairs that survived PCY's
  conditions into a second, independent hash table -> fewer false-positive buckets.
* **Multihash** (§6.3.3): two independent hash tables (each half the size) in pass 1.

Every pass reads the baskets again, chunk by chunk, and expands each basket into its
pairs as it is read (MMDS §6.2.1). numpy is used only to make that expansion fast; the
logic of each pass is exactly the pseudocode in the comments.

All functions return the frequent pairs as well, so tests can check that every method
finds exactly the same L_2 as A-Priori: hashing only removes candidates that cannot be
frequent, it never changes the answer.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Iterator, Sequence

import numpy as np

Itemset = tuple[int, ...]

PRIME = 2_147_483_647          # 2^31 - 1, modulus for the universal hash family
# Two independent hash functions h(i, j) = ((a*i + b*j + c) mod PRIME) mod B.
HASH_PARAMS = ((1_000_003, 7_919, 12_345), (40_503, 2_654_435, 98_765))


# ---------------------------------------------------------------------------
# Basket -> pairs, streamed one chunk of baskets at a time (one "pass")
# ---------------------------------------------------------------------------
_TRIU_CACHE: dict[int, tuple[np.ndarray, np.ndarray]] = {}


def _triu(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Index arrays of all pairs (a < b) of positions 0..n-1 (cached by basket length)."""
    if n not in _TRIU_CACHE:
        _TRIU_CACHE[n] = np.triu_indices(n, k=1)
    return _TRIU_CACHE[n]


def iter_pairs(baskets: Sequence[Itemset], chunk: int = 2_000) -> Iterator[tuple[np.ndarray, np.ndarray]]:
    """One pass over the data: yield (i, j) arrays with i < j for every pair in every basket.

    Pairs are not stored in the file; like the nested loops in MMDS §6.2.1 they are
    generated from each basket as it is read.
    """
    for start in range(0, len(baskets), chunk):
        left, right = [], []
        for basket in baskets[start:start + chunk]:
            if len(basket) < 2:
                continue
            arr = np.asarray(basket, dtype=np.int64)        # baskets are sorted, so i < j
            a, b = _triu(len(arr))
            left.append(arr[a])
            right.append(arr[b])
        if left:
            yield np.concatenate(left), np.concatenate(right)


def pair_hash(i: np.ndarray, j: np.ndarray, n_buckets: int, which: int = 0) -> np.ndarray:
    """Bucket number of each pair {i, j} under hash function ``which`` (0 or 1)."""
    a, b, c = HASH_PARAMS[which]
    return ((a * i + b * j + c) % PRIME) % n_buckets


def count_items(baskets: Sequence[Itemset], n_items: int) -> np.ndarray:
    """Item counts (the A-Priori / PCY pass-1 item table)."""
    flat = np.fromiter((i for b in baskets for i in b), dtype=np.int64)
    return np.bincount(flat, minlength=n_items)


# ---------------------------------------------------------------------------
# Triangular matrix (MMDS §6.2.2)
# ---------------------------------------------------------------------------
def triangular_index(i: int, j: int, n: int) -> int:
    """1-based position of pair {i, j} (1 <= i < j <= n) in the triangular array.

    k = (i - 1)(n - i/2) + j - i   (MMDS 3rd ed., §6.2.2)

    Pairs are stored in the order {1,2}, {1,3}, ..., {1,n}, {2,3}, ..., {n-1,n}, so the
    array needs exactly n(n-1)/2 slots and no space for i >= j.
    """
    if not 1 <= i < j <= n:
        raise ValueError("need 1 <= i < j <= n")
    return int((i - 1) * (n - i / 2) + j - i)


def triangular_pair_counts(baskets: Sequence[Itemset], frequent_items: Sequence[int]
                           ) -> tuple[np.ndarray, dict[int, int]]:
    """A-Priori pass 2 with a triangular matrix over the RE-NUMBERED frequent items.

    The frequent items get new numbers 1..m (table ``new_id``), so the matrix needs only
    m(m-1)/2 counters instead of n(n-1)/2 for all n items. Returns the count array
    (index k-1 holds the count of the pair at position k) and the re-numbering table.
    """
    new_id = {old: new for new, old in enumerate(sorted(frequent_items), start=1)}
    m = len(new_id)
    lookup = np.zeros(max(frequent_items, default=0) + 1, dtype=np.int64)  # 0 = not frequent
    for old, new in new_id.items():
        lookup[old] = new
    counts = np.zeros(m * (m - 1) // 2, dtype=np.int64)
    for i, j in iter_pairs(baskets):
        keep = (i < len(lookup)) & (j < len(lookup))
        ni, nj = lookup[i[keep]], lookup[j[keep]]
        both = (ni > 0) & (nj > 0)
        ni, nj = ni[both], nj[both]                       # re-numbering keeps i < j
        k = (ni - 1) * (2 * m - ni) // 2 + nj - ni        # integer form of the formula
        counts += np.bincount(k - 1, minlength=len(counts))
    return counts, new_id


def triangular_frequent_pairs(counts: np.ndarray, new_id: dict[int, int], min_count: int) -> dict[Itemset, int]:
    """Read L_2 back out of the triangular array, translating to the original item ids."""
    old_of = {new: old for old, new in new_id.items()}
    m = len(new_id)
    out = {}
    for pos in np.nonzero(counts >= min_count)[0]:
        k = int(pos) + 1
        # invert k -> (i, j): walk the rows (m is small, so this is cheap)
        i, start = 1, 1
        while start + (m - i) <= k:
            start += m - i
            i += 1
        j = i + (k - start) + 1
        out[(old_of[i], old_of[j])] = int(counts[pos])
    return out


# ---------------------------------------------------------------------------
# PCY, Multistage, Multihash
# ---------------------------------------------------------------------------
@dataclass
class PairMiningStats:
    """What one run of a pair-mining algorithm did, for the report tables."""

    algorithm: str
    min_count: int
    n_buckets: int                 # total buckets over all hash tables
    passes: int
    frequent_items: int
    apriori_candidate_pairs: int   # C(m, 2): every pair of frequent items (A-Priori's C_2)
    occurring_frequent_item_pairs: int  # of those, the ones that occur in at least one basket
    candidate_pairs: int           # occurring pairs that pass ALL the algorithm's conditions
    frequent_buckets_pct: float    # share of buckets in the FIRST hash table with count >= min_count
    frequent_buckets_pct_table2: float | None  # same for the second table (Multistage/Multihash)
    avg_bucket_count: float        # pair occurrences hashed into the first table / its buckets
    frequent_pairs: int            # |L_2|
    false_positive_candidates: int # candidate pairs that turn out NOT to be frequent
    memory_pass2_bytes: int        # bitmaps + 12-byte triples for the counted candidates
    seconds: float

    def as_dict(self) -> dict:
        t2 = self.frequent_buckets_pct_table2
        return asdict(self) | {"frequent_buckets_pct": round(self.frequent_buckets_pct, 2),
                               "frequent_buckets_pct_table2": None if t2 is None else round(t2, 2),
                               "avg_bucket_count": round(self.avg_bucket_count, 1),
                               "seconds": round(self.seconds, 3)}


def _count_selected_pairs(baskets: Sequence[Itemset], n_items: int, keep_fn) -> dict[int, int]:
    """Final pass: count, as (pair code -> count) triples, only pairs for which keep_fn is True."""
    codes = []
    for i, j in iter_pairs(baskets):
        mask = keep_fn(i, j)
        codes.append(i[mask] * n_items + j[mask])
    if not codes:
        return {}
    uniq, cnt = np.unique(np.concatenate(codes), return_counts=True)
    return dict(zip(uniq.tolist(), cnt.tolist()))


def _finish(name, baskets, n_items, min_count, n_buckets, passes, item_freq, keep_fn,
            bucket_counts, start) -> tuple[PairMiningStats, dict[Itemset, int]]:
    counted = _count_selected_pairs(baskets, n_items, keep_fn)
    frequent = {(c // n_items, c % n_items): v for c, v in counted.items() if v >= min_count}
    seconds = time.perf_counter() - start    # the algorithm ends here; the rest is diagnostics
    # For comparison: occurring pairs whose two items are both frequent (A-Priori with triples).
    occurring = _count_selected_pairs(baskets, n_items, lambda i, j: item_freq[i] & item_freq[j])
    m = int(item_freq.sum())
    n_bitmaps = len(bucket_counts)
    bitmap_bytes = sum(math.ceil(len(t) / 8) for t in bucket_counts)
    first = bucket_counts[0]
    total_pair_occurrences = sum(len(i) for i, _ in iter_pairs(baskets))
    stats = PairMiningStats(
        algorithm=name, min_count=min_count, n_buckets=sum(len(t) for t in bucket_counts),
        passes=passes, frequent_items=m, apriori_candidate_pairs=math.comb(m, 2),
        occurring_frequent_item_pairs=len(occurring), candidate_pairs=len(counted),
        frequent_buckets_pct=100 * float((first >= min_count).mean()),
        frequent_buckets_pct_table2=(100 * float((bucket_counts[1] >= min_count).mean())
                                     if n_bitmaps > 1 else None),
        avg_bucket_count=total_pair_occurrences / len(first),
        frequent_pairs=len(frequent), false_positive_candidates=len(counted) - len(frequent),
        memory_pass2_bytes=bitmap_bytes + 12 * len(counted),
        seconds=seconds,
    )
    return stats, frequent


def pcy(baskets: Sequence[Itemset], n_items: int, min_count: int, n_buckets: int
        ) -> tuple[PairMiningStats, dict[Itemset, int]]:
    """PCY: 2 passes.

    Pass 1   FOR each basket: add 1 to each item's count;
                              FOR each pair: hash it to a bucket, add 1 to that bucket.
    Between  bitmap[b] = 1 iff bucket b's count >= s ; frequent items = count >= s.
    Pass 2   count pair {i, j} only if i and j are frequent AND bitmap[h(i, j)] = 1.
    """
    start = time.perf_counter()
    item_freq = count_items(baskets, n_items) >= min_count
    buckets = np.zeros(n_buckets, dtype=np.int64)
    for i, j in iter_pairs(baskets):                                   # pass 1 (pairs part)
        buckets += np.bincount(pair_hash(i, j, n_buckets), minlength=n_buckets)
    bitmap = buckets >= min_count                                      # between passes
    keep = lambda i, j: item_freq[i] & item_freq[j] & bitmap[pair_hash(i, j, n_buckets)]  # noqa: E731
    return _finish("PCY", baskets, n_items, min_count, n_buckets, 2, item_freq, keep, [buckets], start)


def multistage(baskets: Sequence[Itemset], n_items: int, min_count: int, n_buckets: int
               ) -> tuple[PairMiningStats, dict[Itemset, int]]:
    """Multistage: 3 passes. Pass 1 = PCY pass 1 (hash h1).

    Pass 2   rehash with an INDEPENDENT h2 only the pairs that qualify for PCY's pass 2
             (both items frequent, h1-bucket frequent) -> bitmap 2.
    Pass 3   count {i, j} only if both items frequent, bitmap1[h1] = 1 AND bitmap2[h2] = 1.
    """
    start = time.perf_counter()
    item_freq = count_items(baskets, n_items) >= min_count
    t1 = np.zeros(n_buckets, dtype=np.int64)
    for i, j in iter_pairs(baskets):
        t1 += np.bincount(pair_hash(i, j, n_buckets, 0), minlength=n_buckets)
    bm1 = t1 >= min_count
    t2 = np.zeros(n_buckets, dtype=np.int64)
    for i, j in iter_pairs(baskets):
        ok = item_freq[i] & item_freq[j] & bm1[pair_hash(i, j, n_buckets, 0)]
        t2 += np.bincount(pair_hash(i[ok], j[ok], n_buckets, 1), minlength=n_buckets)
    bm2 = t2 >= min_count
    keep = lambda i, j: (item_freq[i] & item_freq[j] & bm1[pair_hash(i, j, n_buckets, 0)]  # noqa: E731
                         & bm2[pair_hash(i, j, n_buckets, 1)])
    return _finish("Multistage", baskets, n_items, min_count, n_buckets, 3, item_freq, keep, [t1, t2], start)


def multihash(baskets: Sequence[Itemset], n_items: int, min_count: int, n_buckets: int
              ) -> tuple[PairMiningStats, dict[Itemset, int]]:
    """Multihash: 2 passes, the same memory as PCY split into two tables of n_buckets/2.

    Pass 1   every pair is hashed with h1 into table 1 AND with h2 into table 2.
    Pass 2   count {i, j} only if both items frequent and BOTH of its buckets are frequent.
    """
    start = time.perf_counter()
    half = n_buckets // 2
    item_freq = count_items(baskets, n_items) >= min_count
    t1 = np.zeros(half, dtype=np.int64)
    t2 = np.zeros(half, dtype=np.int64)
    for i, j in iter_pairs(baskets):
        t1 += np.bincount(pair_hash(i, j, half, 0), minlength=half)
        t2 += np.bincount(pair_hash(i, j, half, 1), minlength=half)
    bm1, bm2 = t1 >= min_count, t2 >= min_count
    keep = lambda i, j: (item_freq[i] & item_freq[j] & bm1[pair_hash(i, j, half, 0)]  # noqa: E731
                         & bm2[pair_hash(i, j, half, 1)])
    return _finish("Multihash", baskets, n_items, min_count, n_buckets, 2, item_freq, keep, [t1, t2], start)
