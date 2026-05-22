# ISSUES.md — Forecast of Potential Issues

Issues are ordered roughly by severity. Each has the **risk**, **why it matters**, and a **mitigation**. The first three are project-defining and were surfaced directly by the Day-0 data audit.

## A. Data and labelling issues (most severe)

### A1. No dataset measures cholera — and only one measures *any* pathogen
- **Risk:** *V. cholerae* appears in none of the four datasets, and only `full_dataset.csv` (25,625 rows) contains a microbial measurement at all (E. coli + faecal coliforms). The other three measure unrelated targets (potability, fish-pond quality, CCME index).
- **Why it matters:** A model literally cannot learn to detect cholera from data that never observed it. Promising "cholera prediction" would be misleading and, in a public-health context, dangerous.
- **Mitigation:** Reframe the deliverable as an **E. coli / faecal-contamination risk classifier used as a cholera-*risk* proxy** (E. coli is the standard WHO faecal-indicator organism). State this limitation prominently in the model card. Do not market it as a cholera detector. Treat the other datasets as auxiliary/unsupervised inputs, not pathogen-label sources.

### A2. The four datasets share almost no predictors
- **Risk:** The only feature common to all four is **pH**. Turbidity and temperature appear in three of four; DO/BOD/ammonia in two. A single model trained jointly on all four cannot use most features for most rows.
- **Why it matters:** "Combining" the datasets naively produces a table that is mostly missing values, and any model trained on it learns dataset-identity artefacts rather than water chemistry.
- **Mitigation:** Two-tier feature design — a **minimal tier** (pH, temperature, turbidity) supported by `full_dataset.csv` for the shipped TinyML model, and a **rich tier** for nodes with fuller sensors. Keep dataset provenance as a column to detect leakage.

### A3. Extreme target skew and class imbalance
- **Risk:** E. coli spans 0–50,000,000 /100 mL (median 678); ~95% of `risk_drinking_no_treatment` labels are "HIGH" (24,283 HIGH vs 943 Med vs 399 low).
- **Why it matters:** A model predicting "HIGH" for everything scores ~95% accuracy while being useless for distinguishing safe water. Point regression across eight orders of magnitude is unreliable on an MCU.
- **Mitigation:** Use **ordinal risk bands** on a log scale; report **per-class recall and macro-F1, never raw accuracy**; apply class weights/focal loss and threshold tuning; ensure a strong majority-class floor baseline is beaten on minority-class recall.

### A4. Missing data
- **Risk:** 17.7% of E. coli rows are blank in `full_dataset.csv`; faecal coliforms are largely empty; potability has missing pH/sulfate/trihalomethanes.
- **Why it matters:** Naive dropping shrinks an already label-scarce dataset; naive imputation of the *label* fabricates ground truth.
- **Mitigation:** Drop rows missing the *label*; median/KNN-impute *predictors* with explicit missingness-indicator features; never impute the target.

### A5. Unit and convention mismatches
- **Risk:** Turbidity in **cm (transparency)** in WQD vs **NTU** in others; concentrations per 100 mL vs per L; WQD's `pH`` column has a stray backtick; a BOM prefix on WQD's header.
- **Why it matters:** Silent unit coercion creates physically false features and corrupts the per-litre estimate the project must report.
- **Mitigation:** Unit registry with documented conversions; **no fabricated NTU↔cm conversion** (kept separate or dropped); per-100 mL → per-L only via the explicit ×10 factor with the convention stated.

### A6. Implausible / out-of-range values
- **Risk:** WQD shows Temp values like 67°C and pH ~3–5 that look synthetic or out of physical range; potability solids in the tens of thousands.
- **Why it matters:** Trains the model on noise; widens apparent input ranges so the OOD detector mis-fires.
- **Mitigation:** Physical-plausibility range checks per parameter; quarantine/winsorise outliers; document any dataset suspected to be synthetic.

## B. Modelling issues

### B1. Data leakage from repeated site measurements
- **Risk:** `full_dataset.csv` has many repeated readings per `site_id` over time. A random split puts correlated rows in both train and test.
- **Mitigation:** **Grouped + temporal split by site and date.** Expect lower but honest accuracy.

### B2. Dimensionality reduction that doesn't reduce sensor cost
- **Risk:** PCA components require every raw input to be measured, defeating the point on a TinyML node.
- **Mitigation:** Prefer feature **selection** (consensus of MI, F-test, tree importance) for the shipped model; reserve PCA for EDA/visualisation.

### B3. Weak predictive ceiling from physico-chemical features alone
- **Risk:** pH/temperature/turbidity are only loosely coupled to bacterial counts; the achievable accuracy may be modest.
- **Mitigation:** Set realistic expectations early; lean on coarse risk bands rather than precise counts; consider adding rainfall/season if obtainable (literature links rainfall to contamination spikes).

### B4. Overfitting on the small, imbalanced label set
- **Risk:** Effective labelled rows after cleaning may be well under 25k and dominated by one class.
- **Mitigation:** Regularisation, shallow trees, cross-validation, early stopping; report variance across folds.

## C. TinyML / deployment issues

### C1. Footprint and latency budget
- **Risk:** Chosen model exceeds flash/RAM or latency on a Cortex-M0+/ESP32-class device.
- **Mitigation:** Fix the budget Day 1; constrain depth/width/feature count to it; quantise to int8.

### C2. Accuracy lost to quantisation
- **Risk:** int8 quantisation can disproportionately hurt minority-class recall.
- **Mitigation:** Evaluate the *quantised* model specifically; compare float vs int8 confusion matrices; re-tune thresholds post-quantisation.

### C3. Sensor noise and drift in the field
- **Risk:** Cheap pH/turbidity sensors are noisy and drift; lab-quality training data won't reflect this.
- **Mitigation:** Train/evaluate with injected sensor noise; add input smoothing; document recalibration cadence.

### C4. Out-of-distribution inputs in the field
- **Risk:** Field water outside training ranges → silent, confident, wrong predictions.
- **Mitigation:** Range-based abstention / "uncertain — send to lab" output state; probability calibration.

### C5. Toolchain decided too early
- **Risk:** Committing to TFLite-Micro vs emlearn before knowing the winning model family wastes effort.
- **Mitigation:** Defer the toolchain choice to Day 7, conditioned on the selected model.

## D. Process and safety issues

### D1. Misuse / over-trust of a proxy model
- **Risk:** A "safe" prediction is acted on as a guarantee of potable water, risking real harm.
- **Mitigation:** Conservative thresholds biased toward flagging risk; prominent model-card disclaimer that this is a screening proxy, not a substitute for microbial lab testing; always provide the abstain state.

### D2. Reproducibility and provenance
- **Risk:** Ad-hoc cleaning makes results impossible to reproduce or audit.
- **Mitigation:** Versioned pipeline, fixed seeds, dataset checksums, provenance column throughout.

### D3. Timeline risk in a 10-day sprint
- **Risk:** Standardisation and label engineering (Days 2–3) routinely overrun, compressing modelling.
- **Mitigation:** Time-box reconciliation; if it slips, ship the **minimal-tier model on `full_dataset.csv` alone** as the guaranteed deliverable and treat multi-dataset integration as the stretch goal.

### D4. Licensing and source heterogeneity
- **Risk:** The four sources (DWS South Africa, Kaggle, Figshare, Mendeley) carry different licences and citation requirements.
- **Mitigation:** Record each licence; confirm redistribution/derivative-model terms before publishing the model.
