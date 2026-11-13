# How NexusRaid's analysis works

This document explains every method NexusRaid uses, why it was chosen, and
where it fails. Small worked examples ("dry runs") show the arithmetic.

---

## 1. Robust statistics: median and MAD

Most methods below measure "how far from normal" a value is. The classic
tools are the **mean** and **standard deviation**, but both are pulled by the
very outliers we want to find.

Example values: `10, 11, 12, 11, 10, 95`

| Statistic | Value | Effect of the outlier 95 |
|---|---|---|
| Mean | 24.8 | dragged far upward |
| Standard deviation | 31.4 | inflated, so 95 looks only ~2.2 SD away |
| Median | 11 | unchanged |
| MAD (median of absolute deviations from the median) | median of `1,0,1,0,1,84` = 1 | unchanged |

The robust standard deviation is `1.4826 × MAD` (1.4826 makes it equal to the SD
for normally distributed data). NexusRaid uses median/MAD almost everywhere.

---

## 2. Per-column anomaly detection

For each numeric column the method is chosen automatically:

| Column shape | Method | Why |
|---|---|---|
| Roughly symmetric (abs(skewness) ≤ 1) | Modified Z-score | Robust, works for bell-shaped data |
| Skewed | IQR fences | No shape assumption |
| Strongly right-skewed and non-negative (amounts, sizes, durations) | IQR fences on log scale | Otherwise every large-but-normal value is flagged |
| Fewer than 20 values, ≤ 2 distinct values, or IQR = 0 | Skipped (with reason) | "Unusual" cannot be defined |

### Modified Z-score (dry run)

`M = 0.6745 × (x − median) / MAD`, flagged when `|M| > 3.5`.

Values `10, 11, 12, 11, 10, 95`: median 11, MAD 1.
For 95: `0.6745 × 84 / 1 = 56.7` → flagged. For 12: `0.67` → normal.

### IQR fences (dry run)

`Q1 − k×IQR` and `Q3 + k×IQR`, with k = 3 by default (Tukey's "far out" fence).

Values `2, 4, 4, 5, 6, 7, 8, 40`: Q1 = 4, Q3 = 7.25, IQR = 3.25.
Upper fence = `7.25 + 3 × 3.25 = 17` → 40 is flagged.

Why k = 3 and not the textbook 1.5? On 5,000 normally distributed values, k = 1.5
flags about 0.7% (35 rows) of perfectly normal data. k = 3 flags almost none.

### Log scale for skewed columns

Transaction amounts typically look like `20, 35, 50, 80, 120, 300, 900, 25,000`.
On the raw scale, IQR fences flag 900 and many other ordinary purchases. On the
log scale (`log(1 + x)`) the spacing becomes even and only the true extremes are flagged.

### Known false-positive rate

Thresholds are statistical, so pure noise is sometimes flagged. In a test with
200,000 rows of random normal data in 11 columns, about 0.05% of values per
column were flagged (~1,000 rows in total). That is expected multiple-testing
behaviour: with many values, some fall far from the median by chance. Findings
where more than 5% of a column is flagged are marked **low confidence**.

---

## 3. Row-level (multivariate) detection

Some rows are unusual only as a combination ("high CPU with low network"),
even though each value alone is normal.

### Isolation Forest (default)

Idea: build random trees that split the data with random cuts. An unusual row
is separated ("isolated") after only a few cuts; a typical row needs many.

```
Typical row: needs ~10 random cuts to be alone
Outlier row: alone after ~3 cuts  ->  short average path  ->  high anomaly score
```

Preparation: missing values → column median (this step only), strongly skewed
columns → log scale, then robust scaling `(x − median) / IQR`.

### The threshold, and a finding from building this project

scikit-learn's default (`contamination="auto"`) was measured on clean,
outlier-free random data:

| Test data | Rows flagged by the library default |
|---|---|
| 2,000 clean normal rows, 4 columns | **334 (17%)** |

A fixed contamination percentage (e.g. 1%) is no better: it forces exactly 1% of
rows to be "anomalies" even in clean data. NexusRaid instead flags a row when
its score is more than **6 robust SDs** above the typical row's score.
Measured on synthetic data:

| Columns | Rows | Clean data flagged | Injected outliers found |
|---|---|---|---|
| 2 | 500 / 2,000 / 10,000 | 0.2% / 0% / 0.05% | 20/20 each |
| 4 | 500 / 2,000 / 10,000 | 0% / 0% / 0% | 20/20 each |
| 8 | 500 / 2,000 / 10,000 | 0% / 0% / 0% | 20/20 each |

A first version used 4 robust SDs; the test suite caught that it flagged 5.3%
of clean 2-column data, which is why the default is 6.

### Local Outlier Factor and DBSCAN (optional)

* **LOF** compares a row's local density with its neighbours' densities. It finds
  rows unusual *within their cluster*. Cost grows quickly with size, so it is
  limited to 20,000 rows.
* **DBSCAN** groups dense regions into clusters; rows in no cluster are flagged.
  `eps` is set to the 95th percentile of each row's distance to its k-th
  neighbour. Limited to 10,000 rows. Its result depends heavily on `eps`, so it
  is not the default.

### Validation against labels

If a dataset has a yes/no label column such as `is_anomaly` or `incident`, the
detectors never see it. Afterwards, flags are compared with it:

```
                labelled yes   labelled no
flagged             TP             FP
not flagged         FN             TN

precision = TP / (TP + FP)    recall = TP / (TP + FN)
F1 = 2 × precision × recall / (precision + recall)
```

On the synthetic IoT sample: precision 0.67, recall 0.89. These are in-sample
numbers on synthetic data and therefore optimistic.

---

## 4. Trends, drift and sudden changes

Trend analysis only runs when a real time column exists. **Row order is never
assumed to be time**: shuffling the rows of a table must not create a trend.

### Kendall's tau (dry run)

Compare every pair of points: does the later one have a higher value?

Values over time: `3, 5, 4, 6`
Pairs (earlier, later): (3,5)+ (3,4)+ (3,6)+ (5,4)− (5,6)+ (4,6)+ → 5 concordant, 1 discordant
`tau = (5 − 1) / 6 = 0.67` (a mostly increasing series).

A trend is reported only when p < 0.001, |tau| ≥ 0.3 and the change is
practically meaningful. The strict p-value is deliberate: neighbouring time
points are correlated, which makes ordinary p-values look stronger than they are.

### Drift

`drift = (median of last 15% − median of first 25%) / robust SD of first 25%`

Drift answers "how far has the recent level moved from the start", measured in
the series' own early variability. A drift of 7.5 means the recent level is 7.5
early-period spreads above where it started.

### Spikes versus level shifts

* **Spike**: one point far from the median of its 11 neighbours.
* **Level shift**: the median of the 5 points after a moment differs from the 5
  points before, *and* the jump persists when 10 points are compared on each
  side, *and* no data gap lies inside the windows.

Noise is estimated from point-to-point differences:
`sigma = 1.4826 × MAD(differences) / √2`, which is not inflated by slow trends.

Two lessons from testing:

1. A 3-bucket burst first appeared as a "down shift" (the burst sat inside the
   "before" window). The persistence check fixes this: short bursts are spikes.
2. On almost noise-free data (disk % that rises by 0.001 per sample), sigma is
   nearly zero and every tiny step looked like a jump. Changes must therefore
   also be at least 10% of the series' usual range (p5–p95).

### Time-series modes

| Mode | When | How |
|---|---|---|
| regular | one row per timestamp at a steady interval | each row is a point |
| grouped | several devices share timestamps | one series per device |
| events | irregular timestamps (transactions, connections) | counted and averaged per time bucket |

---

## 5. Domain detection

Each domain analyzer lists column roles and keywords. Column names are split
into words (`avgResponseTime_ms` → `avg, response, time, ms`) and matched.
Longer keyword matches win (`dst port` beats `dst`).

| Evidence | Rule | What runs |
|---|---|---|
| strong | ≥ 2 core roles matched | all domain checks |
| partial | 1 core role, or ≥ 2 supporting roles | only checks the columns support |
| none | nothing matched | universal analysis only |

No percentage confidence is reported: counting keyword matches cannot
honestly produce a probability.

---

## 6. Risk engine (worked example)

Risk is only computed for server, website and IoT data, and only with a time
column. Each signal scores 0 (none) to 3 (severe):

* **Level signals** compare the recent level with configured thresholds
  (e.g. CPU warning 80%, critical 95%). Only these can reach 3.
* **Trend signals** score drift: 1 = worsening trend, 2 = drift ≥ 3 spreads.
  A trend alone is capped at 2, because "much worse than its own baseline" does
  not prove "unacceptable". That needs a threshold such as a latency target.
* **Recent anomaly concentration**: flagged-row rate in the last 10% of time
  versus the whole period.
* **Co-movement**: several stress metrics worsening together.

Server sample (synthetic):

| Signal | Score | Weight |
|---|---|---|
| CPU, memory, disk, response time, errors trends | 2 each | 1 |
| Recent anomaly concentration | 2 | 1 |
| Signals worsening together | 2 | 1 |
| Memory level (75%, warning 85%) | 1 | 1 |
| CPU level, disk level | 0 | 1 |

`ratio = (5×2 + 2 + 2 + 1) / (10 × 3) = 15/30 = 0.50` → **High**
(medium ≥ 0.2, high ≥ 0.4, critical ≥ 0.6; any severe signal → at least High;
two severe → Critical).

The result is a transparent concern indicator, not a probability of failure,
and the thresholds are defaults that have not been calibrated against real incidents.

---

## 7. Live monitoring rules

* **Threshold alerts**: latest CPU/memory/disk % against warning and critical levels.
* **Statistical alerts**: latest value more than 6 robust SDs above the machine's
  last 120 readings, and at least 10 percentage points (or 2× and 100 KB/s for rates)
  above its median, so tiny absolute jumps are ignored.
* **Cooldown**: the same alert is not repeated within 15 minutes unless it escalates.
* **Heartbeat**: no data for `max(60 s, 3 × reporting interval)` → "No recent data".

---

## 8. Complexity (n rows, d numeric columns)

| Step | Time | Notes |
|---|---|---|
| Profiling | O(n·d) | one pass per column |
| Per-column detection | O(n log n · d) | percentiles need sorting |
| Isolation Forest | O(t·ψ·log ψ) to fit, O(n·t·log ψ) to score | t = 100 trees, ψ = 256 samples per tree |
| LOF | about O(n²) worst case | hence the 20,000-row limit |
| Kendall's tau | O(m log m) | m ≤ 5,000 points after down-sampling |
| Rolling medians | O(n·w) | w = 5–11 |

Measured: 200,000 rows × 12 columns took about 6 s on the development sandbox.
Expect several times longer on a dual-core laptop CPU.
