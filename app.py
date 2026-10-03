"""Flask web application for the Online Retail frequent-itemset mining project.

Endpoints
---------
GET  /                  dashboard page (templates/index.html)
GET  /api/summary       dataset description, data-quality checks and preprocessing steps
POST /api/analyze       run A-Priori + rule generation with user-selected parameters
GET  /api/experiments   pre-computed experiment results (results/json/analysis_summary.json)

Run with ``python app.py`` and open http://127.0.0.1:5050
(port 5050 because macOS uses port 5000 for the AirPlay Receiver; set PORT to change it).
"""

from __future__ import annotations

import os
import random

from flask import Flask, jsonify, render_template, request

from src.apriori import apriori
from src.association_rules import generate_rules, rule_summary
from src.experiments import RANDOM_SEED
from src.preprocessing import load_dataset_summary, load_transactions
from src.utils import JSON_DIR, load_json

# Limits that keep one interactive request to a few seconds on a laptop.
MIN_SUPPORT_LIMIT = 0.005
MAX_ROWS_RETURNED = 200

app = Flask(__name__)

# The cleaned baskets are loaded once at start-up and shared by all requests.
TRANSACTIONS = load_transactions()
DATASET_SUMMARY = load_dataset_summary()
_SHUFFLED = list(range(len(TRANSACTIONS)))
random.Random(RANDOM_SEED).shuffle(_SHUFFLED)   # same sampling as the scalability experiment


class BadRequest(ValueError):
    pass


def _number(payload: dict, key: str, default: float, low: float, high: float, cast=float):
    try:
        value = cast(payload.get(key, default))
    except (TypeError, ValueError):
        raise BadRequest(f"'{key}' must be a number")
    if not low <= value <= high:
        raise BadRequest(f"'{key}' must be between {low} and {high}")
    return value


@app.errorhandler(BadRequest)
def handle_bad_request(err):
    return jsonify({"error": str(err)}), 400


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/summary")
def summary():
    return jsonify(DATASET_SUMMARY)


@app.post("/api/analyze")
def analyze():
    payload = request.get_json(silent=True) or {}
    min_support = _number(payload, "min_support", 0.02, MIN_SUPPORT_LIMIT, 1.0)
    min_confidence = _number(payload, "min_confidence", 0.5, 0.0, 1.0)
    sample_size = _number(payload, "sample_size", len(TRANSACTIONS), 100, len(TRANSACTIONS), int)

    baskets = [TRANSACTIONS[i] for i in _SHUFFLED[:sample_size]]
    result = apriori(baskets, min_support)
    rules = generate_rules(result, min_confidence)

    itemsets = result.top_itemsets(MAX_ROWS_RETURNED, min_size=1)
    multi_item = result.top_itemsets(MAX_ROWS_RETURNED, min_size=2)
    return jsonify({
        "parameters": {"min_support": min_support, "min_confidence": min_confidence,
                       "sample_size": sample_size, "min_support_count": result.min_count},
        "seconds": round(result.total_seconds, 3),
        "levels": result.level_table(),
        "by_size": result.count_by_size(),
        "total_frequent": len(result.frequent),
        "pruned_examples": result.pruned_examples,
        "itemsets": itemsets,
        "multi_item_itemsets": multi_item,
        "rules": [r.as_dict() for r in rules[:MAX_ROWS_RETURNED]],
        "rule_summary": rule_summary(rules),
        "rows_limit": MAX_ROWS_RETURNED,
    })


@app.get("/api/experiments")
def experiments():
    path = JSON_DIR / "analysis_summary.json"
    if not path.exists():
        return jsonify({"error": "Experiments have not been run yet. Run: python -m src.experiments"}), 404
    return jsonify(load_json(path))


if __name__ == "__main__":
    app.run(debug=False, port=int(os.environ.get("PORT", 5050)))
