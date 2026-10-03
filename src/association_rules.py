"""Association-rule generation from the frequent itemsets found by :mod:`src.apriori`.

For a frequent itemset I and a non-empty proper subset X of I, the rule is
X -> Y with Y = I \\ X (so X and Y are always disjoint and neither is empty).

    support(X -> Y)    = support(X u Y)                     = count(I) / N
    confidence(X -> Y) = support(X u Y) / support(X)        = count(I) / count(X)
    lift(X -> Y)       = confidence(X -> Y) / support(Y)
    interest(X -> Y)   = confidence(X -> Y) - support(Y)     (MMDS §6.1.3)

Because of monotonicity every subset X and Y of a frequent itemset I is itself frequent,
so their counts are already stored in the A-Priori result and no extra data scan is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from statistics import mean

from src.apriori import AprioriResult


@dataclass(frozen=True)
class AssociationRule:
    antecedent: tuple[str, ...]
    consequent: tuple[str, ...]
    support_count: int
    support: float
    confidence: float
    lift: float
    interest: float = 0.0          # confidence - support(consequent); 0 means independence

    def as_dict(self) -> dict:
        return {
            "antecedent": list(self.antecedent),
            "consequent": list(self.consequent),
            "support_count": self.support_count,
            "support": round(self.support, 5),
            "confidence": round(self.confidence, 4),
            "lift": round(self.lift, 3),
            "interest": round(self.interest, 4),
        }


def generate_rules(result: AprioriResult, min_confidence: float) -> list[AssociationRule]:
    """All rules X -> Y from frequent itemsets of size >= 2 with confidence >= ``min_confidence``.

    Rules are returned sorted by confidence, then lift (both descending).
    """
    if not 0 <= min_confidence <= 1:
        raise ValueError("min_confidence must be in [0, 1]")
    n = result.n_transactions
    rules: list[AssociationRule] = []

    for itemset, count in result.frequent.items():
        if len(itemset) < 2:
            continue
        # Every non-empty proper subset of the itemset can be an antecedent.
        for r in range(1, len(itemset)):
            for antecedent in combinations(itemset, r):
                consequent = tuple(i for i in itemset if i not in antecedent)   # disjoint by construction
                confidence = count / result.frequent[antecedent]
                if confidence < min_confidence:
                    continue
                consequent_support = result.frequent[consequent] / n
                rules.append(AssociationRule(
                    antecedent=result.names(antecedent),
                    consequent=result.names(consequent),
                    support_count=count,
                    support=count / n,
                    confidence=confidence,
                    lift=confidence / consequent_support,
                    interest=confidence - consequent_support,
                ))

    rules.sort(key=lambda r: (-r.confidence, -r.lift, r.antecedent, r.consequent))
    return rules


def rule_summary(rules: list[AssociationRule]) -> dict:
    """Aggregate statistics used in the confidence experiment."""
    if not rules:
        return {"rules": 0, "avg_confidence": None, "avg_lift": None,
                "max_confidence": None, "min_lift": None}
    return {
        "rules": len(rules),
        "avg_confidence": round(mean(r.confidence for r in rules), 4),
        "avg_lift": round(mean(r.lift for r in rules), 3),
        "max_confidence": round(max(r.confidence for r in rules), 4),
        "min_lift": round(min(r.lift for r in rules), 3),
    }
