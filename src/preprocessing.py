"""Data-quality inspection, cleaning and basket construction for the UCI Online Retail dataset.

Every cleaning step is recorded (rows before / removed / after / reason) so that the
report can show exactly how the raw invoice lines became market baskets.

Run as a script to (re)build ``data/processed/transactions.json``::

    python -m src.preprocessing
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from src.utils import (
    DATASET_SUMMARY_JSON,
    RAW_CACHE,
    RAW_XLSX,
    TABLES_DIR,
    TRANSACTIONS_JSON,
    ensure_dirs,
    load_json,
    markdown_table,
    save_csv,
    save_json,
)

# A regular invoice number is exactly six digits. "C" + six digits marks a cancellation
# and "A" + six digits marks an accounting adjustment ("Adjust bad debt").
REGULAR_INVOICE = re.compile(r"^\d{6}$")

# Stock codes that are not physical products: postage, carriage, fees, discounts,
# manual adjustments, samples and bank charges. Gift vouchers ("gift_0001_*") are
# handled by prefix. These were identified by inspecting every stock code that does
# not start with five digits (see data_quality_report()).
NON_PRODUCT_CODES = {
    "POST", "DOT", "C2", "M", "D", "S", "B", "BANK CHARGES", "AMAZONFEE", "CRUK",
}
NON_PRODUCT_PREFIXES = ("GIFT_",)

# Appropriateness (Halaal) filter. The shop does not sell alcoholic drinks, but a few
# giftware items are themed on alcohol or smoking (e.g. wine glasses, "GIN AND TONIC"
# signs, ashtrays). They are excluded with this explicit whole-word rule; the list of
# affected products is written to results/tables/excluded_products.csv.
EXCLUDED_KEYWORDS = ["WINE", "GIN", "CHAMPAGNE", "COCKTAIL", "BOOZE", "ASHTRAY", "CIGAR", "SPLIFF"]
EXCLUDED_PATTERN = re.compile(r"\b(?:" + "|".join(EXCLUDED_KEYWORDS) + r")\b")


@dataclass
class CleaningLog:
    """Accumulates one row per cleaning step for the preprocessing summary table."""

    steps: list[dict] = field(default_factory=list)

    def record(self, step: str, before: int, after: int, reason: str) -> None:
        """Record a step that removes rows."""
        self.steps.append({"Step": step, "Rows Before": before, "Rows Removed": before - after,
                           "Values Changed": 0, "Rows After": after, "Reason": reason})

    def record_change(self, step: str, rows: int, changed: int, reason: str) -> None:
        """Record a step that edits values but keeps every row."""
        self.steps.append({"Step": step, "Rows Before": rows, "Rows Removed": 0,
                           "Values Changed": changed, "Rows After": rows, "Reason": reason})


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def load_raw(use_cache: bool = True) -> pd.DataFrame:
    """Load the raw Excel file (a pickle cache avoids the slow Excel parse on re-runs)."""
    if use_cache and RAW_CACHE.exists():
        return pd.read_pickle(RAW_CACHE)
    if not RAW_XLSX.exists():
        raise FileNotFoundError(
            f"Dataset not found at {RAW_XLSX}. Download it from the UCI repository "
            "(see README.md, section 'Dataset')."
        )
    # InvoiceNo and StockCode are identifiers, so they are read as text to keep
    # prefixes such as "C536379" and suffixes such as "85123A" intact.
    df = pd.read_excel(RAW_XLSX, dtype={"InvoiceNo": str, "StockCode": str})
    ensure_dirs()
    df.to_pickle(RAW_CACHE)
    return df


# ---------------------------------------------------------------------------
# Data-quality inspection (no modification)
# ---------------------------------------------------------------------------
def data_quality_report(df: pd.DataFrame) -> dict:
    """Measure the quality problems of the raw data without changing it."""
    invoice = df["InvoiceNo"].astype(str).str.strip()
    stock = df["StockCode"].astype(str).str.strip().str.upper()
    desc = df["Description"].dropna().astype(str)

    non_numeric_stock = stock[~stock.str.match(r"^\d{5}")]
    desc_per_code = (
        df.dropna(subset=["Description"])
        .assign(_d=lambda x: x["Description"].astype(str).str.strip().str.upper())
        .groupby(stock)["_d"].nunique()
    )
    within_invoice_dupes = df.dropna(subset=["Description"]).duplicated(subset=["InvoiceNo", "StockCode"]).sum()

    return {
        "rows": int(len(df)),
        "columns": list(df.columns),
        "dtypes": {c: str(t) for c, t in df.dtypes.items()},
        "missing_values": {c: int(v) for c, v in df.isna().sum().items()},
        "exact_duplicate_rows": int(df.duplicated().sum()),
        "unique_invoices": int(invoice.nunique()),
        "unique_stock_codes": int(stock.nunique()),
        "unique_descriptions": int(desc.nunique()),
        "cancelled_invoice_rows": int(invoice.str.startswith("C").sum()),
        "adjustment_invoice_rows": int(invoice.str.startswith("A").sum()),
        "quantity_le_zero": int((df["Quantity"] <= 0).sum()),
        "unit_price_le_zero": int((df["UnitPrice"] <= 0).sum()),
        "unit_price_negative": int((df["UnitPrice"] < 0).sum()),
        "descriptions_with_extra_whitespace": int((desc != desc.str.strip().str.replace(r"\s+", " ", regex=True)).sum()),
        "descriptions_not_upper_case": int(desc.str.contains(r"[a-z]").sum()),
        "stock_codes_with_multiple_descriptions": int((desc_per_code > 1).sum()),
        "non_numeric_stock_code_rows": int(len(non_numeric_stock)),
        "non_numeric_stock_code_top": non_numeric_stock.value_counts().head(15).to_dict(),
        "repeated_product_lines_within_invoice": int(within_invoice_dupes),
        "date_range": [str(df["InvoiceDate"].min()), str(df["InvoiceDate"].max())],
        "countries": int(df["Country"].nunique()),
    }


# ---------------------------------------------------------------------------
# Cleaning
# ---------------------------------------------------------------------------
def normalise_text(s: pd.Series) -> pd.Series:
    """Trim, collapse repeated whitespace and upper-case a text column."""
    return s.astype(str).str.strip().str.replace(r"\s+", " ", regex=True).str.upper()


def clean(df: pd.DataFrame, apply_appropriateness_filter: bool = True) -> tuple[pd.DataFrame, CleaningLog, pd.DataFrame]:
    """Apply the documented cleaning steps.

    Returns the cleaned line-level data, the cleaning log and a table of the products
    removed by the appropriateness filter.
    """
    log = CleaningLog()
    df = df.copy()
    df["InvoiceNo"] = df["InvoiceNo"].astype(str).str.strip()
    df["StockCode"] = df["StockCode"].astype(str).str.strip().str.upper()

    n = len(df)
    df = df.drop_duplicates()
    log.record("1. Remove exact duplicate rows", n, len(df),
               "Identical invoice lines (all 8 fields equal) are data-entry duplicates and add no new purchase.")

    n = len(df)
    df = df[~df["InvoiceNo"].str.startswith("C")]
    log.record("2. Remove cancelled invoices (InvoiceNo starts with 'C')", n, len(df),
               "Cancellations/returns are not purchases; the products were not bought together.")

    n = len(df)
    df = df[df["InvoiceNo"].str.match(REGULAR_INVOICE)]
    log.record("3. Remove non-standard invoice numbers (e.g. 'A563185')", n, len(df),
               "'A' invoices are accounting adjustments ('Adjust bad debt'), not customer orders.")

    n = len(df)
    df = df.dropna(subset=["Description"])
    df = df[df["Description"].astype(str).str.strip() != ""]
    log.record("4. Remove rows with missing product description", n, len(df),
               "Without a description the item cannot be identified or interpreted.")

    n = len(df)
    df = df[df["Quantity"] > 0]
    log.record("5. Remove rows with Quantity <= 0", n, len(df),
               "Zero/negative quantities are stock corrections (e.g. 'damaged', 'lost'), not sales.")

    n = len(df)
    df = df[df["UnitPrice"] > 0]
    log.record("6. Remove rows with UnitPrice <= 0", n, len(df),
               "Free or negative-price lines are internal adjustments rather than customer purchases.")

    n = len(df)
    is_service = df["StockCode"].isin(NON_PRODUCT_CODES) | df["StockCode"].str.startswith(NON_PRODUCT_PREFIXES)
    df = df[~is_service]
    log.record("7. Remove non-product stock codes (POSTAGE, CARRIAGE, fees, vouchers, ...)", n, len(df),
               "Postage and fees appear in many baskets for administrative reasons and would create "
               "meaningless rules such as {X} -> {POSTAGE}.")

    # Step 8: text standardisation changes values but does not remove rows.
    before_desc = df["Description"].astype(str)
    df["Description"] = normalise_text(df["Description"])
    changed = int((before_desc != df["Description"]).sum())
    log.record_change("8. Standardise descriptions (trim, collapse spaces, upper-case)", len(df), changed,
                      "Leading/trailing/double spaces and mixed case make the same product look like different items.")

    # Step 9: one canonical name per StockCode (the most frequent description of that code),
    # so that small spelling variations do not split one product into several items.
    canonical = (
        df.groupby(["StockCode", "Description"]).size().reset_index(name="n")
        .sort_values(["StockCode", "n", "Description"], ascending=[True, False, True])
        .drop_duplicates("StockCode").set_index("StockCode")["Description"]
    )
    new_desc = df["StockCode"].map(canonical)
    changed = int((new_desc != df["Description"]).sum())
    df["Description"] = new_desc
    log.record_change("9. Map each StockCode to one canonical description", len(df), changed,
                      "Some stock codes have several spellings; the most frequent one is used as the item name.")

    excluded = pd.DataFrame(columns=["StockCode", "Description", "Rows"])
    if apply_appropriateness_filter:
        n = len(df)
        mask = df["Description"].str.contains(EXCLUDED_PATTERN)
        excluded = (df[mask].groupby(["StockCode", "Description"]).size()
                    .reset_index(name="Rows").sort_values("Rows", ascending=False))
        df = df[~mask]
        log.record("10. Appropriateness (Halaal) filter on descriptions", n, len(df),
                   f"Whole-word keywords {', '.join(EXCLUDED_KEYWORDS)} (alcohol- or smoking-themed items) "
                   "are excluded; the affected products are listed in excluded_products.csv.")

    return df.reset_index(drop=True), log, excluded


# ---------------------------------------------------------------------------
# Basket construction
# ---------------------------------------------------------------------------
def build_baskets(df: pd.DataFrame, log: CleaningLog | None = None) -> dict[str, list[str]]:
    """Group product lines by invoice: one invoice = one basket = one set of item names.

    Repeated lines of the same product inside one invoice collapse into one item, because
    the market-basket model only records *whether* an item is in a basket, not how many.
    """
    n = len(df)
    dedup = df.drop_duplicates(subset=["InvoiceNo", "Description"])
    if log is not None:
        log.record("11. Collapse repeated items within the same invoice", n, len(dedup),
                   "A basket is a set: buying the same product on two lines is still one item.")
    baskets = dedup.groupby("InvoiceNo")["Description"].apply(lambda s: sorted(s)).to_dict()
    return baskets


def basket_statistics(baskets: dict[str, list[str]]) -> dict:
    sizes = pd.Series([len(b) for b in baskets.values()])
    items = {i for b in baskets.values() for i in b}
    return {
        "transactions": int(len(baskets)),
        "unique_items": int(len(items)),
        "mean_basket_size": round(float(sizes.mean()), 2),
        "median_basket_size": float(sizes.median()),
        "max_basket_size": int(sizes.max()),
        "single_item_baskets": int((sizes == 1).sum()),
    }


def run_preprocessing() -> dict:
    """Full pipeline: inspect -> clean -> build baskets -> save everything."""
    ensure_dirs()
    raw = load_raw()
    quality = data_quality_report(raw)
    cleaned, log, excluded = clean(raw)
    baskets = build_baskets(cleaned, log)
    stats = basket_statistics(baskets)

    item_counts = pd.Series([i for b in baskets.values() for i in b]).value_counts()
    summary = {
        "dataset": "UCI Online Retail (Chen, 2015)",
        "raw_quality": quality,
        "cleaned_rows": int(len(cleaned)),
        "cleaning_steps": log.steps,
        "baskets": stats,
        "cleaned_countries": int(cleaned["Country"].nunique()),
        "cleaned_customers_missing_id_rows": int(cleaned["CustomerID"].isna().sum()),
        "top_items": [{"item": k, "baskets": int(v)} for k, v in item_counts.head(15).items()],
        "excluded_products": int(len(excluded)),
    }

    save_json({"invoices": list(baskets.keys()), "transactions": list(baskets.values())}, TRANSACTIONS_JSON)
    save_json(summary, DATASET_SUMMARY_JSON)
    save_csv(log.steps, TABLES_DIR / "preprocessing_summary.csv")
    save_csv(excluded.to_dict("records"), TABLES_DIR / "excluded_products.csv")
    save_csv(summary["top_items"], TABLES_DIR / "top_items.csv")
    return summary


def load_transactions() -> list[frozenset[str]]:
    """Load the cleaned baskets produced by :func:`run_preprocessing`."""
    if not TRANSACTIONS_JSON.exists():
        run_preprocessing()
    data = load_json(TRANSACTIONS_JSON)
    return [frozenset(t) for t in data["transactions"]]


def load_dataset_summary() -> dict:
    if not DATASET_SUMMARY_JSON.exists():
        return run_preprocessing()
    return load_json(DATASET_SUMMARY_JSON)


if __name__ == "__main__":
    s = run_preprocessing()
    print("Raw data-quality report:")
    for k, v in s["raw_quality"].items():
        print(f"  {k}: {v}")
    print("\nPreprocessing summary:")
    print(markdown_table(s["cleaning_steps"]))
    print("\nBasket statistics:", s["baskets"])
    print("Excluded products (appropriateness filter):", s["excluded_products"])
