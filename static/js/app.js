/* Dashboard logic (vanilla JavaScript, no framework).
 * Talks to the Flask backend with fetch() + JSON:
 *   GET  /api/summary      -> dataset & preprocessing tables
 *   POST /api/analyze      -> run Apriori with the chosen parameters
 *   GET  /api/experiments  -> pre-computed experiment results for the charts
 */
"use strict";

const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat("en-US");
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const state = {
  n: null,                 // number of cleaned baskets
  result: null,            // latest /api/analyze response
  experiments: null,       // /api/experiments response
  charts: {},              // Chart.js instances by canvas id
  sort: {
    itemsets: { key: "support_count", dir: -1 },
    rules: { key: "confidence", dir: -1 },
  },
};

// ------------------------------------------------------------------ small helpers
async function getJSON(url, options) {
  const res = await fetch(url, options);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const pct = (x, digits = 2) => (x == null ? "–" : `${(x * 100).toFixed(digits)}%`);
const shortPct = (x) => `${+(x * 100).toFixed(2)}%`;
const chips = (items, cls = "") => items.map((i) => `<span class="item ${cls}">${escapeHtml(i)}</span>`).join("");
const minCount = (s, n) => Math.max(1, Math.ceil(s * n - 1e-9));   // same rule as src/apriori.py

/** A numeric cell with a small proportional bar. */
function cellBar(value, max, text, warm = false) {
  const w = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return `<div class="cell-bar${warm ? " warm" : ""}"><span class="track"><span class="fill" style="width:${w}%"></span></span><span class="v">${text}</span></div>`;
}

/**
 * Render rows into a <table>. columns: [{key, label, num, render, sort, cls}]
 * If `sortState` is given, headers with `sort` become clickable and re-render via `onSort`.
 */
function renderTable(table, rows, columns, sortState, onSort) {
  if (sortState) {
    const key = sortState.key;
    rows = [...rows].sort((a, b) => (a[key] < b[key] ? -1 : a[key] > b[key] ? 1 : 0) * sortState.dir);
  }
  const head = columns.map((c) => {
    const sortable = sortState && c.sort;
    const active = sortable && sortState.key === c.sort;
    const arrow = active ? (sortState.dir < 0 ? "▼" : "▲") : "";
    const aria = sortable ? ` data-sort="${c.sort}" aria-sort="${active ? (sortState.dir < 0 ? "descending" : "ascending") : "none"}"` : "";
    return `<th class="${c.num ? "num" : ""}"${aria}>${c.label}${sortable ? `<span class="arrow">${arrow}</span>` : ""}</th>`;
  }).join("");
  const body = rows.length
    ? rows.map((r) => "<tr>" + columns.map((c) => {
        const content = c.render ? c.render(r) : escapeHtml(typeof r[c.key] === "number" && c.num ? fmt.format(r[c.key]) : r[c.key] ?? "");
        return `<td class="${c.num ? "num" : ""} ${c.cls || ""}">${content}</td>`;
      }).join("") + "</tr>").join("")
    : `<tr><td colspan="${columns.length}" class="muted">No rows match.</td></tr>`;
  table.innerHTML = `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;

  if (sortState) {
    table.querySelectorAll("th[data-sort]").forEach((th) => th.addEventListener("click", () => {
      const key = th.dataset.sort;
      sortState.dir = sortState.key === key ? -sortState.dir : -1;
      sortState.key = key;
      onSort();
    }));
  }
}

function kpiTiles(container, tiles) {
  container.innerHTML = tiles
    .map(([label, value]) => `<div class="kpi"><div class="value">${value}</div><div class="label">${label}</div></div>`)
    .join("");
}

// ------------------------------------------------------------------ navigation & tabs
function setupNav() {
  const links = [...document.querySelectorAll(".nav a")];
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) {
        links.forEach((a) => a.classList.toggle("active", a.getAttribute("href") === `#${e.target.id}`));
      }
    });
  }, { rootMargin: "-45% 0px -50% 0px" });
  links.forEach((a) => observer.observe(document.querySelector(a.getAttribute("href"))));
}

const tabListeners = [];
function setupTabs() {
  document.querySelectorAll("[data-tabs]").forEach((list) => {
    const buttons = [...list.querySelectorAll("[role=tab]")];
    buttons.forEach((btn) => btn.addEventListener("click", () => {
      buttons.forEach((b) => {
        const on = b === btn;
        b.setAttribute("aria-selected", on);
        $(b.dataset.panel).hidden = !on;
      });
      tabListeners.forEach((fn) => fn(btn.dataset.panel));
    }));
  });
}

// ------------------------------------------------------------------ dataset summary
async function loadSummary() {
  const s = await getJSON("/api/summary");
  const q = s.raw_quality;
  const b = s.baskets;
  state.n = b.transactions;
  const month = (d) => new Date(d.replace(" ", "T")).toLocaleDateString("en-GB", { month: "short", year: "numeric" });

  kpiTiles($("hero-kpis"), [
    ["Raw invoice lines", fmt.format(q.rows)],
    ["Baskets (cleaned invoices)", fmt.format(b.transactions)],
    ["Distinct products (items)", fmt.format(b.unique_items)],
    ["Median basket size", `${b.median_basket_size} <small>items (mean ${b.mean_basket_size})</small>`],
    ["Period covered", `<span style="font-size:19px">${month(q.date_range[0])} – ${month(q.date_range[1])}</span>`],
  ]);

  const maxRemoved = Math.max(...s.cleaning_steps.map((r) => r["Rows Removed"]));
  renderTable($("prep-table"), s.cleaning_steps, [
    { key: "Step", label: "Step", cls: "step" },
    { key: "Rows Before", label: "Rows before", num: true },
    { label: "Rows removed", num: true, render: (r) => cellBar(r["Rows Removed"], maxRemoved, fmt.format(r["Rows Removed"]), true) },
    { key: "Values Changed", label: "Values changed", num: true },
    { key: "Rows After", label: "Rows after", num: true },
    { key: "Reason", label: "Reason", cls: "reason" },
  ]);

  const checks = [
    ["Missing Description", q.missing_values.Description],
    ["Missing CustomerID (kept: not needed for baskets)", q.missing_values.CustomerID],
    ["Exact duplicate rows", q.exact_duplicate_rows],
    ["Cancelled-invoice rows ('C' prefix)", q.cancelled_invoice_rows],
    ["Adjustment-invoice rows ('A' prefix)", q.adjustment_invoice_rows],
    ["Quantity ≤ 0", q.quantity_le_zero],
    ["UnitPrice ≤ 0", q.unit_price_le_zero],
    ["Descriptions with extra whitespace", q.descriptions_with_extra_whitespace],
    ["Stock codes with several descriptions", q.stock_codes_with_multiple_descriptions],
    ["Non-product stock-code rows (POST, DOT, M, …)", q.non_numeric_stock_code_rows],
    ["Repeated product lines inside an invoice", q.repeated_product_lines_within_invoice],
  ].map(([check, value]) => ({ check, value }));
  const maxCheck = Math.max(...checks.map((c) => c.value));
  renderTable($("quality-table"), checks, [
    { key: "check", label: "Check" },
    { label: "Rows affected", num: true, render: (r) => cellBar(r.value, maxCheck, fmt.format(r.value)) },
  ]);

  // The sample-size controls depend on N.
  $("sample-range").max = state.n;
  $("sample-size").max = state.n;
  setValue("sample-size", state.n);
  $("sample-hint").textContent = `Random sample of 100 – ${fmt.format(state.n)} baskets (seed 42)`;
}

// ------------------------------------------------------------------ controls
const CONTROLS = {
  "min-support": { range: "support-range", out: "support-out", show: (v) => pct(v, 2), min: 0.005, max: () => 1 },
  "min-confidence": { range: "confidence-range", out: "confidence-out", show: (v) => pct(v, 0), min: 0, max: () => 1 },
  "sample-size": { range: "sample-range", out: "sample-out", show: (v) => fmt.format(v), min: 100, max: () => state.n },
};

function setValue(id, value) {
  $(id).value = value;
  $(CONTROLS[id].range).value = value;
  refreshControls();
}

function isValid(id) {
  const c = CONTROLS[id];
  const v = parseFloat($(id).value);
  return Number.isFinite(v) && v >= c.min && v <= c.max();
}

function refreshControls() {
  for (const [id, c] of Object.entries(CONTROLS)) {
    const v = parseFloat($(id).value);
    const ok = isValid(id);
    $(id).classList.toggle("invalid", !ok);
    $(c.out).textContent = ok ? c.show(v) : "invalid";
    document.querySelectorAll(`.presets[data-target="${id}"] button`).forEach((b) => {
      const preset = b.dataset.value === "all" ? state.n : parseFloat(b.dataset.value);
      b.classList.toggle("on", preset === v);
    });
  }
  const s = parseFloat($("min-support").value);
  const n = parseInt($("sample-size").value, 10);
  $("mincount-hint").textContent = isValid("min-support") && isValid("sample-size")
    ? `An itemset needs ≥ ⌈${s} × ${fmt.format(n)}⌉ = ${fmt.format(minCount(s, n))} baskets`
    : "Support must be between 0.005 and 1";
}

function setupControls() {
  for (const [id, c] of Object.entries(CONTROLS)) {
    $(c.range).addEventListener("input", () => { $(id).value = $(c.range).value; refreshControls(); });
    $(id).addEventListener("input", () => { $(c.range).value = $(id).value; refreshControls(); });
  }
  document.querySelectorAll(".presets button").forEach((b) => b.addEventListener("click", () => {
    setValue(b.parentElement.dataset.target, b.dataset.value === "all" ? state.n : b.dataset.value);
  }));
  $("analyze-form").addEventListener("submit", runAnalysis);
  refreshControls();
}

// ------------------------------------------------------------------ interactive analysis
async function runAnalysis(event) {
  event.preventDefault();
  const btn = $("run-btn");
  const label = btn.querySelector(".btn-label");
  const status = $("run-status");
  if (!Object.keys(CONTROLS).every(isValid)) {
    status.className = "status error";
    status.textContent = "Please correct the highlighted values.";
    return;
  }
  const body = {
    min_support: parseFloat($("min-support").value),
    min_confidence: parseFloat($("min-confidence").value),
    sample_size: parseInt($("sample-size").value, 10),
  };
  btn.disabled = true;
  btn.classList.add("loading");
  label.textContent = "Running…";
  status.className = "status";
  status.textContent = body.min_support < 0.01 ? "Low support: this can take several seconds." : "";
  try {
    state.result = await getJSON("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    status.textContent = `Mined in ${state.result.seconds.toFixed(2)} s`;
    renderRun();
  } catch (err) {
    status.className = "status error";
    status.textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.classList.remove("loading");
    label.textContent = "Run Analysis";
  }
}

function renderRun() {
  const r = state.result;
  const p = r.parameters;
  $("analysis-results").hidden = false;
  const largest = Math.max(...Object.keys(r.by_size).map(Number));
  kpiTiles($("run-kpis"), [
    ["Baskets analysed", fmt.format(p.sample_size)],
    ["Min support count", fmt.format(p.min_support_count)],
    ["Frequent itemsets", fmt.format(r.total_frequent)],
    ["Largest itemset", `${largest} <small>items</small>`],
    ["Association rules", fmt.format(r.rule_summary.rules)],
    ["Mining time", `${r.seconds.toFixed(2)} <small>s</small>`],
  ]);
  renderLevels();
  renderPrunedExample();
  $("itemsets-count").textContent = fmt.format(r.total_frequent);
  $("rules-count").textContent = fmt.format(r.rule_summary.rules);
  renderItemsets();
  renderRules();
}

/** One row per level k: a bar split into frequent / counted-not-frequent / pruned, relative to the join output. */
function renderLevels() {
  const seg = (cls, value, total, title) => (value
    ? `<span class="seg ${cls}" style="flex:0 0 ${(value / total) * 100}%;min-width:3px" title="${title}: ${fmt.format(value)}"></span>`
    : "");
  $("levels").innerHTML = state.result.levels.map((lv) => {
    const joined = lv.candidates_generated;
    const counted = lv.candidates_counted;
    const pruned = lv.candidates_pruned;
    const frequent = lv.frequent_itemsets;
    const prunedPct = joined ? ((pruned / joined) * 100).toFixed(1) : "0.0";
    const counts = lv.k === 1
      ? `<span><b>${fmt.format(joined)}</b> distinct items counted</span>`
      : `<span><b>${fmt.format(joined)}</b> joined</span><span class="pr"><b>${fmt.format(pruned)}</b> pruned (${prunedPct}%)</span><span><b>${fmt.format(counted)}</b> counted</span>`;
    const name = lv.k === 1 ? "items" : lv.k === 2 ? "pairs" : `${lv.k}-itemsets`;
    return `<div class="level">
      <div class="level-k">k = ${lv.k}<small>${name}</small></div>
      <div>
        <div class="bar" role="img" aria-label="Level ${lv.k}: ${frequent} frequent, ${counted - frequent} counted but not frequent, ${pruned} pruned, out of ${joined}">
          ${seg("frequent", frequent, joined, "Frequent")}${seg("counted", counted - frequent, joined, "Counted, not frequent")}${seg("pruned", pruned, joined, "Pruned")}
        </div>
        <div class="level-stats">${counts}<span><b>${fmt.format(frequent)}</b> frequent</span><span>${lv.seconds.toFixed(3)} s</span></div>
      </div>
    </div>`;
  }).join("");
}

function renderPrunedExample() {
  const ex = state.result.pruned_examples[0];
  const p = state.result.parameters;
  $("pruned-example").innerHTML = ex
    ? `<div class="callout"><span class="icon" aria-hidden="true">✂︎</span><div><strong>Pruning in action.</strong>
       The candidate ${chips(ex.candidate)} was removed <em>without counting it</em>, because its subset
       ${chips(ex.infrequent_subset, "cons")} occurs in only <b>${fmt.format(ex.infrequent_subset_count)}</b> baskets
       (&lt; ${fmt.format(p.min_support_count)}). Every basket containing the candidate also contains that subset, so the candidate cannot be frequent.</div></div>`
    : `<p class="muted small">No candidate needed pruning at this threshold.</p>`;
}

const matches = (items, q) => !q || items.some((i) => i.toLowerCase().includes(q));

function renderItemsets() {
  if (!state.result) return;
  const q = $("itemset-filter").value.trim().toLowerCase();
  const source = $("multi-only").checked ? state.result.multi_item_itemsets : state.result.itemsets;
  const maxSup = Math.max(0, ...source.map((r) => r.support));
  renderTable($("itemsets-table"), source.filter((r) => matches(r.itemset, q)), [
    { label: "Itemset", render: (r) => chips(r.itemset) },
    { key: "size", label: "k", num: true, sort: "size" },
    { key: "support_count", label: "Baskets", num: true, sort: "support_count" },
    { label: "Support", num: true, sort: "support", render: (r) => cellBar(r.support, maxSup, pct(r.support)) },
  ], state.sort.itemsets, renderItemsets);
}

function renderRules() {
  if (!state.result) return;
  const s = state.result.rule_summary;
  const shown = Math.min(s.rules, state.result.rows_limit);
  $("rule-summary").textContent = s.rules
    ? `${fmt.format(s.rules)} rules with confidence ≥ ${pct(state.result.parameters.min_confidence, 0)} · average confidence ${pct(s.avg_confidence, 1)} · average lift ${s.avg_lift}` +
      (s.rules > shown ? ` · showing the ${shown} most confident` : "")
    : "No rules satisfy these thresholds. Try a lower support or confidence.";
  const q = $("rule-filter").value.trim().toLowerCase();
  renderTable($("rules-table"), state.result.rules.filter((r) => matches(r.antecedent.concat(r.consequent), q)), [
    { label: "Rule X → Y", render: (r) => `${chips(r.antecedent)}<span class="rule-arrow">→</span>${chips(r.consequent, "cons")}` },
    { label: "Support", num: true, sort: "support", render: (r) => pct(r.support) },
    { label: "Confidence", num: true, sort: "confidence", render: (r) => cellBar(r.confidence, 1, pct(r.confidence, 1)) },
    { label: "Lift", num: true, sort: "lift", render: (r) => `<span class="lift">${r.lift.toFixed(2)}</span>` },
  ], state.sort.rules, renderRules);
}

// ------------------------------------------------------------------ experiments
function palette() {
  return {
    s1: cssVar("--series-1"), s2: cssVar("--series-2"), s3: cssVar("--series-3"),
    grid: cssVar("--border"), ink: cssVar("--text-2"),
  };
}

function baseOptions({ x, y, logY = false, legend = true, yFormat, xLinear = false, yMax }) {
  const c = palette();
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: legend, position: "bottom", labels: { color: c.ink, boxWidth: 8, boxHeight: 8, usePointStyle: true } },
      tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${yFormat ? yFormat(ctx.parsed.y) : fmt.format(ctx.parsed.y)}` } },
    },
    scales: {
      x: {
        type: xLinear ? "linear" : "category",
        title: { display: true, text: x, color: c.ink },
        grid: { display: false },
        // Only the numeric axis needs a formatter; category axes keep Chart.js's default labels.
        ticks: xLinear ? { color: c.ink, callback: (v) => fmt.format(v) } : { color: c.ink },
      },
      y: {
        type: logY ? "logarithmic" : "linear",
        beginAtZero: !logY,
        min: logY ? 0.5 : undefined,   // so that a count of 1 is still visible
        max: yMax,
        title: { display: true, text: y, color: c.ink },
        grid: { color: c.grid },
        ticks: {
          color: c.ink,
          // On a log axis, label only the powers of ten to keep the axis readable.
          callback: logY ? (v) => (Number.isInteger(Math.log10(v)) ? fmt.format(v) : "") : (v) => (yFormat ? yFormat(v) : fmt.format(v)),
        },
      },
    },
  };
}

const lineDs = (label, data, color) => ({ label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6 });
const barDs = (label, data, color) => ({ label, data, backgroundColor: color, borderRadius: 4, maxBarThickness: 46 });
const nullIfZero = (v) => (v === 0 ? null : v);   // zero cannot be drawn on a log axis
const secs = (v) => `${v.toFixed(2)} s`;

// Chart definitions per experiment tab. Charts are created when their tab is first shown,
// because a chart created inside a hidden element would have zero size.
const CHARTS = {
  "exp-support": (e, c) => {
    const sup = e.support_experiment;
    const labels = sup.map((r) => shortPct(r.min_support));
    return {
      "chart-support-itemsets": { type: "line", data: { labels, datasets: [
        lineDs("1-itemsets", sup.map((r) => nullIfZero(r.frequent_1)), c.s1),
        lineDs("2-itemsets", sup.map((r) => nullIfZero(r.frequent_2)), c.s2),
        lineDs("3+-itemsets", sup.map((r) => nullIfZero(r.frequent_3plus)), c.s3),
      ] }, options: baseOptions({ x: "Minimum support", y: "Frequent itemsets", logY: true }) },
      "chart-support-candidates": { type: "line", data: { labels, datasets: [
        lineDs("Generated by join", sup.map((r) => r.candidates_generated), c.s1),
        lineDs("Counted after pruning", sup.map((r) => r.candidates_counted), c.s2),
      ] }, options: baseOptions({ x: "Minimum support", y: "Candidates", logY: true }) },
      "chart-support-time": { type: "line", data: { labels, datasets: [lineDs("Time", sup.map((r) => r.seconds), c.s1)] },
        options: baseOptions({ x: "Minimum support", y: "Seconds", legend: false, yFormat: secs }) },
    };
  },
  "exp-confidence": (e, c) => {
    const conf = e.confidence_experiment;
    const labels = conf.map((r) => pct(r.min_confidence, 0));
    return {
      "chart-confidence": { type: "bar", data: { labels, datasets: [barDs("Rules", conf.map((r) => r.rules), c.s1)] },
        options: baseOptions({ x: "Minimum confidence", y: "Number of rules", legend: false }) },
      "chart-confidence-avg": { type: "line", data: { labels, datasets: [lineDs("Average confidence", conf.map((r) => r.avg_confidence * 100), c.s1)] },
        options: baseOptions({ x: "Minimum confidence", y: "Average confidence", legend: false, yFormat: (v) => `${v.toFixed(0)}%`, yMax: 100 }) },
    };
  },
  "exp-pruning": (e, c) => {
    const lv = e.pruning_experiment.levels.filter((r) => r.k >= 2);
    const labels = lv.map((r) => `k = ${r.k}`);
    return {
      "chart-pruning": { type: "bar", data: { labels, datasets: [
        barDs("Generated by join", lv.map((r) => r.generated_by_join), c.s1),
        barDs("Counted after pruning", lv.map((r) => nullIfZero(r.counted_after_pruning)), c.s2),
        barDs("Frequent", lv.map((r) => nullIfZero(r.frequent)), c.s3),
      ] }, options: baseOptions({ x: "Itemset size", y: "Itemsets", logY: true }) },
      "chart-pruning-pct": { type: "bar", data: { labels, datasets: [barDs("Pruned", lv.map((r) => r.pruned_pct_of_join), c.s2)] },
        options: baseOptions({ x: "Itemset size", y: "% of joined candidates", legend: false, yFormat: (v) => `${v.toFixed(0)}%`, yMax: 100 }) },
    };
  },
  "exp-scalability": (e, c) => {
    const sc = e.scalability_experiment;
    return {
      "chart-scalability": { type: "line", data: { datasets: [lineDs("Time", sc.map((r) => ({ x: r.transactions, y: r.seconds })), c.s1)] },
        options: baseOptions({ x: "Transactions (baskets)", y: "Seconds", legend: false, yFormat: secs, xLinear: true }) },
      "chart-scalability-rate": { type: "bar", data: { labels: sc.map((r) => fmt.format(r.transactions)),
        datasets: [barDs("ms per 1,000 baskets", sc.map((r) => r.ms_per_1000_transactions), c.s1)] },
        options: baseOptions({ x: "Transactions (baskets)", y: "ms per 1,000 baskets", legend: false }) },
    };
  },
};

function showExperimentCharts(panelId) {
  const build = CHARTS[panelId];
  if (!build || !state.experiments) return;
  for (const [id, cfg] of Object.entries(build(state.experiments, palette()))) {
    if (!state.charts[id]) state.charts[id] = new Chart($(id), cfg);
  }
}

/** One-sentence key finding per experiment, computed from the saved results. */
function renderFindings(e) {
  const sup = e.support_experiment, lo = sup[0], hi = sup[sup.length - 1];
  $("finding-support").innerHTML =
    `Raising minimum support from <b>${shortPct(lo.min_support)}</b> to <b>${shortPct(hi.min_support)}</b> cut frequent itemsets from ` +
    `<b>${fmt.format(lo.total_frequent)}</b> to <b>${fmt.format(hi.total_frequent)}</b> and run time from <b>${secs(lo.seconds)}</b> to ` +
    `<b>${secs(hi.seconds)}</b>. Larger itemsets disappear first: the largest itemset shrinks from ${lo.largest_itemset} items to ${hi.largest_itemset}.`;

  const conf = e.confidence_experiment, c0 = conf[0], c1 = conf[conf.length - 1];
  $("finding-confidence").innerHTML =
    `From <b>${pct(c0.min_confidence, 0)}</b> to <b>${pct(c1.min_confidence, 0)}</b> minimum confidence, the rules fall from <b>${fmt.format(c0.rules)}</b> to ` +
    `<b>${fmt.format(c1.rules)}</b>, while their average confidence rises from ${pct(c0.avg_confidence, 1)} to ${pct(c1.avg_confidence, 1)}. ` +
    `Strongest rule: <span class="muted">${escapeHtml(c1.strongest_rule)}</span>.`;

  const lv = e.pruning_experiment.levels;
  const l2 = lv.find((r) => r.k === 2);
  const higher = lv.filter((r) => r.k >= 3).map((r) => `${r.pruned_pct_of_join}% at k = ${r.k}`).join(", ");
  $("finding-pruning").innerHTML =
    `At ${shortPct(e.pruning_experiment.min_support)} support, pairing only frequent items leaves <b>${fmt.format(l2.counted_after_pruning)}</b> of ` +
    `${fmt.format(l2.brute_force_itemsets)} possible pairs (${l2.counted_pct_of_brute_force}). The subset check then removes <b>${higher}</b> of the joined candidates without counting them.`;

  const sc = e.scalability_experiment, s0 = sc[0], s1 = sc[sc.length - 1];
  $("finding-scalability").innerHTML =
    `Growing the data <b>${(s1.transactions / s0.transactions).toFixed(1)}×</b> (${fmt.format(s0.transactions)} → ${fmt.format(s1.transactions)} baskets) ` +
    `increased the run time <b>${(s1.seconds / s0.seconds).toFixed(1)}×</b> (${secs(s0.seconds)} → ${secs(s1.seconds)}), which is close to linear. ` +
    `The number of candidates stays near ${fmt.format(Math.round(s1.candidates_counted / 1000))}k because the support threshold is relative.`;
}

function renderExperimentTables(e) {
  renderTable($("table-support"), e.support_experiment, [
    { label: "Min support", render: (r) => shortPct(r.min_support) },
    { key: "min_support_count", label: "Min count", num: true },
    { key: "frequent_1", label: "L1", num: true },
    { key: "frequent_2", label: "L2", num: true },
    { key: "frequent_3plus", label: "L3+", num: true },
    { key: "total_frequent", label: "Total", num: true },
    { key: "candidates_generated", label: "Joined", num: true },
    { key: "candidates_pruned", label: "Pruned", num: true },
    { key: "candidates_counted", label: "Counted", num: true },
    { label: "Time", num: true, render: (r) => secs(r.seconds) },
  ]);
  renderTable($("table-confidence"), e.confidence_experiment, [
    { label: "Min confidence", render: (r) => pct(r.min_confidence, 0) },
    { key: "rules", label: "Rules", num: true },
    { key: "rules_from_pairs", label: "From pairs", num: true },
    { key: "rules_from_3plus", label: "From 3+", num: true },
    { label: "Avg confidence", num: true, render: (r) => pct(r.avg_confidence, 1) },
    { key: "avg_lift", label: "Avg lift", num: true },
    { key: "min_lift", label: "Min lift", num: true },
  ]);
  renderTable($("table-pruning"), e.pruning_experiment.levels, [
    { key: "k", label: "k", num: true },
    { key: "brute_force_itemsets", label: "All possible C(n,k)", num: true },
    { key: "generated_by_join", label: "Joined", num: true },
    { label: "Pruned", num: true, render: (r) => cellBar(r.pruned_pct_of_join, 100, `${fmt.format(r.pruned_by_subset_check)} · ${r.pruned_pct_of_join}%`, true) },
    { key: "counted_after_pruning", label: "Counted", num: true },
    { key: "frequent", label: "Frequent", num: true },
  ]);
  renderTable($("table-scalability"), e.scalability_experiment, [
    { key: "transactions", label: "Transactions", num: true },
    { key: "min_support_count", label: "Min count", num: true },
    { key: "distinct_items", label: "Distinct items", num: true },
    { key: "candidates_counted", label: "Candidates", num: true },
    { key: "frequent_itemsets", label: "Frequent", num: true },
    { label: "Time", num: true, render: (r) => secs(r.seconds) },
    { key: "ms_per_1000_transactions", label: "ms / 1,000 baskets", num: true },
  ]);
}

async function loadExperiments() {
  try {
    state.experiments = await getJSON("/api/experiments");
  } catch (err) {
    $("exp-env").textContent = err.message;
    return;
  }
  const e = state.experiments;
  const env = e.environment;
  $("exp-env").textContent = `Full cleaned dataset (${fmt.format(e.dataset.transactions)} baskets, ${fmt.format(e.dataset.unique_items)} items) · ` +
    `${env.cpu}, Python ${env.python} · times are the median of 3 runs.`;
  renderFindings(e);
  renderExperimentTables(e);
  showExperimentCharts("exp-support");
  // Deep link: /#exp-pruning (etc.) opens that experiment tab.
  const tab = document.querySelector(`[role=tab][data-panel="${location.hash.slice(1)}"]`);
  if (tab) {
    tab.click();
    document.getElementById("experiments").scrollIntoView();
  }
}

// ------------------------------------------------------------------ start-up
document.addEventListener("DOMContentLoaded", () => {
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  setupNav();
  setupTabs();
  tabListeners.push(showExperimentCharts);
  setupControls();
  $("multi-only").addEventListener("change", renderItemsets);
  $("itemset-filter").addEventListener("input", renderItemsets);
  $("rule-filter").addEventListener("input", renderRules);

  // Load the dataset summary, then run one analysis with the default parameters.
  loadSummary()
    .then(() => $("analyze-form").requestSubmit())
    .catch((err) => { $("hero-kpis").textContent = err.message; });
  loadExperiments();
});
