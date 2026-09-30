# VENTURE Scorer Holdout Protocol & Design Freeze

> [!NOTE]
> **Status**: `scorer-frozen-v1` was superseded and **never evaluated on holdout data**.
> Grouped CV by company demonstrates that at n=56, free features produce marginal signal (Grouped CV-AUC ~0.54–0.57). Holdout labels will not be burned on this design. Evaluation is deferred until total labels reach $\ge 200$ (or a validated model design is chosen), at which point a fresh tag `scorer-frozen-v2` (without `-f`) will be created for the holdout run.


---

## 1. Frozen Baseline State
- **Deterministic Fit Scorer**: [`automation/composite_scorer.py`](file:///d:/JobPilot-AI/automation/composite_scorer.py)
  - Features: `rag_score`, `title_clean` (regex pos - neg), `title_sim_max`, `jd_coverage`.
  - Calibrated logistic link, soft YOE penalty (2.5 pts/yr capped at 10.0 pts), stretch boosts (+5 to +10 pts).
  - Stopword-ratio English detector (`is_english_jd`): routes non-English to `explore`/`needs_human`.
- **Learned Benchmark (5-fold Stratified CV, n=56)**:
  - `rag` alone CV-AUC: **0.552** [0.461, 0.601]
  - `all+title_clean` CV-AUC: **0.653** [0.577, 0.713]
  - In-sample hand composite AUC: **0.708**
  - Precision@10: **0.80** (lift: 1.24x, 95% bootstrap CI: [0.718, 1.575])

---

## 2. Invariant Holdout Rules
1. **Freeze Tag**: Scorer weights, penalties, feature normalizations, and thresholds are strictly FROZEN under `scorer-frozen-v1`. No modifications may occur after holdout labeling begins.
2. **Distribution Fidelity**: Holdout jobs must be collected purely from the live query distribution (e.g. real queries `Full Stack Developer`, `Software Engineer`, `Python Developer` across real target platforms). Do NOT curate artificial negative pools (e.g. collecting exclusively QA/DevOps) as that inflates AUC artificially.
3. **Blind Labeling**:
   - Use `label_tool.py` with fit scores hidden.
   - Consistent definition per `LABELING.md` (`apply` = would honestly apply / review positively; `skip` = unqualified or undesired).
   - Target holdout size: $\ge 60$ labels (natural skip rate ~35% gives ~21 skips).
4. **Data Isolation**:
   - Holdout records must be written to `eval/holdout_labels.jsonl` (strictly gitignored).
   - Tune labels in `eval/labels.jsonl` remain separate.
   - Never run replay, calibration, or ablation scripts on holdout data during the labeling phase.
5. **One-Shot Evaluation**:
   - Once labeling completes, run a single one-shot holdout evaluation script reporting:
     - ROC-AUC + 95% bootstrap CI.
     - Precision@10 + lift over base rate.
     - Review-load curve & recall at top-$K$.
   - If holdout AUC < 0.60, the conclusion is "scorer is weak / near-random" — do NOT tweak parameters; gather more real-world labels and diagnose feature representations.
