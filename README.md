# Frequent Itemset Mining and Association Rule Analysis in Online Retail Transactions Using the Apriori Algorithm

CSD 5113 Big Data Mining, Assignment 1 (Chapter 6: Frequent Itemsets), Semester I 2026-2027.

This mini project mines the **UCI Online Retail** dataset. Each invoice is treated as a basket and each product as an item. A **manually implemented Apriori algorithm** (`src/apriori.py`) finds the frequent itemsets. Association rules with support, confidence and lift are then generated (`src/association_rules.py`). The project runs four experiments (minimum support, minimum confidence, Apriori pruning and scalability) and shows everything in a small Flask + HTML/CSS/vanilla-JavaScript dashboard.

# Project Setup

## Requirements

* Python **3.10 or newer** (developed and tested with Python 3.13.3 on macOS)
* Internet access once, to download the dataset (about 23 MB)
* Nothing else needs to be installed globally. All packages go into a virtual environment.

## Installation

```bash
python -m venv .venv
```

Mac/Linux:

```bash
source .venv/bin/activate
```

Windows:

```bat
.venv\Scripts\activate
```

Then:

```bash
pip install -r requirements.txt
```

## Dataset

* Name: Online Retail. Donor: Daqing Chen (London South Bank University), 2015. Licence: CC BY 4.0
* Official page: <https://archive.ics.uci.edu/dataset/352/online+retail>
* DOI: <https://doi.org/10.24432/C5BW33>
* Direct download: <https://archive.ics.uci.edu/static/public/352/online+retail.zip>

Put the Excel file at **`data/raw/Online Retail.xlsx`**:

Mac/Linux:

```bash
mkdir -p data/raw
curl -L -o data/raw/online_retail.zip "https://archive.ics.uci.edu/static/public/352/online+retail.zip"
unzip -o data/raw/online_retail.zip -d data/raw
```

Windows (PowerShell):

```powershell
New-Item -ItemType Directory -Force data\raw
Invoke-WebRequest "https://archive.ics.uci.edu/static/public/352/online+retail.zip" -OutFile data\raw\online_retail.zip
Expand-Archive data\raw\online_retail.zip -DestinationPath data\raw -Force
```

## Running preprocessing

```bash
python -m src.preprocessing
```

This command:

* prints the data-quality report
* writes `data/processed/transactions.json` (19,766 cleaned baskets) and `data/processed/dataset_summary.json`
* writes `results/tables/preprocessing_summary.csv` and `results/tables/excluded_products.csv`

The first run reads the Excel file, which takes about 15 s. It also creates a pickle cache, so later runs are fast.

## Running experiments

```bash
python -m src.experiments
```

This takes about 1 minute on an Apple M2 Max, because every timing is the median of 3 runs. It writes:

* `results/json/analysis_summary.json`: all results. The web app reads this file.
* `results/tables/*.csv` and `*.md`: support, confidence, pruning and scalability tables, plus the top itemsets and rules
* `results/figures/fig1…fig6*.png`: the report figures

Execution times depend on the machine, so re-running gives slightly different seconds. All counts are deterministic.

## Running the Chapter 6 extension experiments

```bash
python -m src.chapter6_experiments
```

This takes about 2 minutes. It runs experiments 5-9: the lecture examples, triangular matrix vs triples, PCY / Multistage / Multihash bucket sweeps, maximal and closed itemsets, and rule interest. It writes `results/json/chapter6_summary.json`, `results/tables/ch6_*.csv|md` and figures `fig7`-`fig9`.

## Running tests

```bash
python -m pytest -q
```

The tests (`tests/test_apriori.py`) use a tiny synthetic dataset plus a brute-force cross-check on random data. They do not need the real dataset.

## Running the web application

```bash
python app.py
```

Then visit:

```
http://127.0.0.1:5050
```

> Port **5050** is used because macOS reserves port 5000 for the AirPlay Receiver, which answers with *403 Forbidden*. To use a different port: `PORT=8000 python app.py` (Mac/Linux) or `set PORT=8000 && python app.py` (Windows cmd).

The app needs the outputs of `src.preprocessing`, which it creates automatically if they are missing. The experiment charts need `src.experiments` to have been run once.

## Project structure

```
app.py                     Flask backend (JSON API + page)
src/preprocessing.py       data-quality checks, cleaning, basket construction
src/apriori.py             manual Apriori: join, prune, count, filter
src/association_rules.py   rules X -> Y with support, confidence, lift, interest
src/pcy.py                 triangular matrix, PCY, Multistage, Multihash (frequent pairs)
src/compact_output.py      maximal and closed frequent itemsets
src/chapter6_experiments.py experiments 5-9 (Chapter 6 techniques beyond A-Priori)
src/experiments.py         4 experiments, tables and figures
src/utils.py               paths and small helpers
templates/index.html       dashboard page
static/css/style.css       styles (no CSS framework)
static/js/app.js           fetch() calls, tables, Chart.js charts
tests/                     unit tests (35)
results/                   generated tables, figures, JSON
report/                    English report + Arabic study notes
references/references.bib  BibTeX references
```
