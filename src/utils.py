"""Shared paths, timing and file helpers used across the project."""

from __future__ import annotations

import csv
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
RESULTS_DIR = PROJECT_ROOT / "results"
TABLES_DIR = RESULTS_DIR / "tables"
FIGURES_DIR = RESULTS_DIR / "figures"
JSON_DIR = RESULTS_DIR / "json"

RAW_XLSX = RAW_DIR / "Online Retail.xlsx"
RAW_CACHE = PROCESSED_DIR / "online_retail_raw.pkl"
TRANSACTIONS_JSON = PROCESSED_DIR / "transactions.json"
DATASET_SUMMARY_JSON = PROCESSED_DIR / "dataset_summary.json"

DATASET_URL = "https://archive.ics.uci.edu/dataset/352/online+retail"
DATASET_DOWNLOAD_URL = "https://archive.ics.uci.edu/static/public/352/online+retail.zip"


def ensure_dirs() -> None:
    """Create every output directory used by the project (idempotent)."""
    for d in (RAW_DIR, PROCESSED_DIR, TABLES_DIR, FIGURES_DIR, JSON_DIR):
        d.mkdir(parents=True, exist_ok=True)


@contextmanager
def timer() -> Iterator[dict]:
    """Context manager that records elapsed wall-clock seconds in ``box['seconds']``."""
    box = {"seconds": 0.0}
    start = time.perf_counter()
    try:
        yield box
    finally:
        box["seconds"] = time.perf_counter() - start


def format_itemset(itemset: Iterable[str]) -> str:
    """Render an itemset as ``{A, B, C}`` with items in alphabetical order."""
    return "{" + ", ".join(sorted(itemset)) + "}"


def save_json(obj, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_csv(rows: Sequence[dict], path: Path) -> None:
    """Write a list of dictionaries (all with the same keys) to a CSV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def markdown_table(rows: Sequence[dict], columns: Sequence[str] | None = None) -> str:
    """Build a GitHub-flavoured Markdown table from a list of dictionaries."""
    if not rows:
        return "_(no rows)_"
    columns = list(columns or rows[0].keys())
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[c]) for c in columns) + " |")
    return "\n".join(lines)
