# Recommended Approach: Sensor-Based Data Collection and ML for Cholera Risk Prediction

*A working strategy document summarising the pivot from "modelling existing data" to "collecting purpose-built data via low-cost sensors, linking it to health records, and predicting outbreak risk."*

---

## 1. The problem we are actually solving

Our three existing datasets each fail for a different, unfixable reason:

- **WQD.csv** measures aquaculture/fish-pond chemistry (DO, BOD, plankton, ammonia). Its "Water Quality" label is an aquaculture-suitability score, not a human disease outcome — there is no cholera signal in it to find.
- **water_potability.csv** (Kaggle) is widely understood to be synthetic/imputed, with no genuine correlation structure between features and the potability label. The absence of a regression is a property of the data, not a modelling failure on our part.
- **full_dataset.csv** (South African DWS microbiological data) is the most useful — it contains E. coli and faecal coliforms, the correct faecal–oral indicators — but it is monitoring data with **no linked health outcomes**.

The genuine bottleneck is therefore **data that pairs environmental measurements with disease outcomes**, at a useful spatial and temporal resolution. That is the correct thing to attack, and it is what the new sensor-plus-linkage idea is designed to address.

## 2. What a cheap sensor can and cannot detect

This shapes the entire design and must be stated honestly up front.

- **A low-cost sensor will not detect *Vibrio cholerae*.** The pathogen requires culture and serotyping (O1/O139 antigens); toxigenic strains are not even widely distributed in water. No pH/turbidity/temperature/DO probe measures it.
- **What cheap sensors *can* measure are proxies and enabling conditions:**
  - **Faecal-contamination indicators** — E. coli / faecal coliforms are the gold-standard proxy, but in-situ detection needs optical-fluorescence or electrochemical incubation methods that take 3–24 hours and are non-trivial to build.
  - **Conditions conducive to outbreaks** — temperature, turbidity, and a plankton/chlorophyll proxy are epidemiologically meaningful covariates. *V. cholerae* prevalence falls below ~20 °C and associates with plankton/copepods; chlorophyll-a is a known strong predictor in the remote-sensing literature.

**Framing rule:** the device predicts *faecal-contamination risk and conditions conducive to outbreaks*, and the ML links those patterns to outbreak records. It is **not** "a cheap sensor that detects cholera." Reviewers and funders will reject the latter framing instantly.

## 3. Sensor targets (epidemiologically defensible, buildable)

Prioritise the three drivers that recur across every study we reviewed (Bengal Delta literature, India ECV study, the federated-learning preprint):

1. **Rainfall** (or proximity to a rainfall data feed) — the single most consistent driver.
2. **Water temperature** — cheap, reliable, mechanistically tied to *V. cholerae* survival.
3. **Plankton / turbidity / chlorophyll proxy** — an optical measurement; the most defensible "biological reservoir" signal a low-cost device can plausibly capture.

A faecal-indicator (E. coli) capability is the highest-value addition but the hardest and slowest; treat it as a stretch goal, not the baseline build.

## 4. The two hard problems (harder than the electronics)

1. **Health-records linkage and governance.** Connecting sensor data to medical records requires data governance, ethics approval, case definitions, and a functioning reporting system. This is where the project lives or dies, and it should be scoped **before** the hardware. Key unknowns: who owns the health data, what spatial/temporal resolution case reports have, and whether cases can be geolocated to specific sources.
   - *Mitigation:* **Federated learning + differential privacy** (as in the Adewumi preprint) is a clean structural answer — institutions train locally and share only model updates, never raw patient data. This sidesteps much cross-border and consent friction.

2. **Cold-start and class imbalance.** Outbreaks are rare relative to routine safe-water readings, so we face severe imbalance and a long collection period before a model is trainable. A device that must collect for two years before predicting anything is a hard sell.
   - *Mitigation:* anchor on existing environmental-suitability models and use our data to **refine** them, rather than learning from scratch.

## 5. Reframing the unit of analysis: the 7-day exposure window

This refinement is sound **as feature engineering**, and a trap **as a data filter**.

- **Do this:** change the unit of analysis from "every day at every waterhole" to "the trailing 7-day window leading up to each observation." Cholera has an incubation period (hours to ~5 days) and contamination is a process, not an instant. Aggregate sensor readings over the window into features: means, peaks, rate-of-change, and days-above-threshold. These are exactly the "lagged and rolling features" the literature uses.
- **Do NOT do this:** keep only the windows that preceded a case and discard the rest. That deletes the negative class entirely. A model cannot learn a decision boundary with only positives — the imbalance "vanishes" only because the problem vanishes. This is undersampling taken to its fatal extreme.

### The labelling reality this exposes
Labelling a window as positive presumes we can tie "someone was contaminated" back to specific days at a specific source — which *is* the core challenge. In practice a clinic case gives a person and an approximate onset date, but not the source or exact exposure moment. Positive labels will therefore be noisy in **both** source assignment and timing, and under-reporting means some "negative" windows actually contain unobserved positives. The pipeline must be robust to label noise (see §6).

## 6. Recommended ML pipeline

Synthesised from the Tanzania (Leo et al. 2019), Nigeria CORP (Amshi et al. 2024), and federated-learning studies.

1. **Windowed feature construction** — trailing 7-day aggregates per (site, date), keeping both classes.
2. **Matched case–control sampling** — keep all labellable positive windows; rather than keeping every negative, sample matched negatives from the **same sites and seasons** so the ratio is workable but both classes survive. Matching on season/location prevents the model learning "rainy season = case" instead of learning about the water itself.
3. **Outlier removal first** — DBSCAN-style cleaning *before* any resampling, so synthetic points are not generated around mislabeled/anomalous observations.
4. **Oversampling on the training fold only** — ADASYN (preferred over plain SMOTE; it concentrates synthetic samples near the hard decision boundary) **or** class-weighting the loss. Apply **only inside** cross-validation folds, never to the test set.
5. **Model ladder** — Negative Binomial regression (interpretable baseline) → Random Forest / XGBoost (non-linear, with SHAP for interpretability) → LSTM for short-horizon (7–14 day) temporal forecasting.
6. **Imbalance-aware evaluation** — report balanced accuracy, macro-F1, positive-class sensitivity/recall, and PR-AUC. **Never** raw accuracy: with ~7% positives, "always predict no outbreak" scores ~93% and is useless.

### Critical discipline: avoid leakage
Suspiciously high published scores (e.g. the 99.6% CORP accuracy) often indicate **resampling leakage** — oversampling *before* the train/test split lets synthetic copies of test points leak into training. Resample only the training fold, inside CV. Build this in from day one.

## 7. Where to pilot: site selection

The Asia/Africa split in outbreak *predictability* directly determines where usable labelled data accrues fastest.

- **Bengal Delta (Bangladesh / West Bengal) — recommended for the data-collection pilot.** Cholera is endemic and seasonal with reliable annual recurrence; cases occur every month in Dhaka and the outbreak is effectively continuous. Timing is predictable and geographically decomposable (Dhaka peaks around the monsoon; north ~Oct–Nov; south ~Mar–Apr), and the weather-driven mechanism is already modelled. Critically, **icddr,b in Dhaka** is a world-class surveillance partner with continuous hospital records — directly addressing the linkage problem. Devices sited in known high-risk districts ahead of a predictable peak should capture outbreak-period data within a **single season**.
- **Sub-Saharan Africa — greatest humanitarian need, but harder to learn from.** Carries ~83% of deaths, but transmission is episodic and lineage-driven: intermittent outbreaks, elimination, then reintroduction. A device at a given waterhole may sit through a whole year with no local outbreak to label.

**Strategy:** train where data is dense and predictable (Bengal Delta), then port to African settings via **transfer learning / domain adaptation** (flagged as future work in the preprint), rather than cold-starting where positives are sparse and irregular.

## 8. Scope decision (still open — needs answering)

The next steps differ sharply depending on the goal:

- **Research prototype / proof-of-concept** — build one device, show it produces sensible readings, demonstrate the data pipeline end-to-end. Highly achievable; well-suited to a dissertation or pilot grant.
- **Deployable system** linked to real health surveillance — a multi-year, multi-stakeholder programme requiring on-the-ground partners.

Recommendation: **commit explicitly to the proof-of-concept first**, using Bengal Delta data (or icddr,b collaboration) as the target context, with the deployable system as a clearly separated phase 2.

## 9. Immediate next steps

1. **Decide the scope** (proof-of-concept vs deployable) — gates everything else.
2. **Scope the linkage layer early** — identify the surveillance partner (icddr,b is the natural candidate) and confirm what case resolution and geolocation are realistically available.
3. **Lock the sensor target set** — rainfall, temperature, plankton/turbidity proxy as baseline; E. coli capability as stretch goal. Confirm which are buildable on a microcontroller budget.
4. **Prototype the labelled-dataset schema** — windowed features, positive/negative matching logic — so the eventual sensor data can be shaped into a trainable form.
5. **Stand up the ML pipeline on a proxy dataset** (e.g. the open California FIB or DWS data) to validate the imbalance-handling and leakage-avoidance discipline *before* real sensor data exists.

---

## Key references drawn on

- Leo, Luhanga & Michael (2019), *Machine Learning Model for Imbalanced Cholera Dataset in Tanzania* — ADASYN + PCA; imbalance-aware metrics; XGBoost selected.
- Amshi et al. (2024), *How can machine learning predict cholera* (J. Water & Health) — CORP model; DBSCAN + SMOTE + NMF.
- Adewumi (2025 preprint, Research Square), *AI for Cholera Outbreak Prediction … Federated and Privacy-Preserving ML* — model ladder, TinyML edge deployment, federated learning framing. *(Preprint; internal performance figures inconsistent — use for method/structure, not for reported metrics.)*
- *Contrasting Epidemiology of Cholera in Bangladesh and Africa* (J. Infect. Dis., 2021) — the predictability split underpinning site selection.
- WHO / ECDC cholera situation reports (2024–2026) — global burden and seasonality context.

*Document reflects the working conclusions of an ongoing discussion; figures and framing should be revisited as the linkage partner and scope are confirmed.*
