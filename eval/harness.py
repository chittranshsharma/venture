import os
import sys
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score, confusion_matrix

# Ensure workspace root is in sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from automation.llm_evaluator import evaluate_job_with_qwen, prompt_version, PROMPT_TEMPLATE
from core.db_manager import compute_content_hash, compute_dedup_key
from core.config_manager import load_config
from core.resume_parser import extract_resume_text
from eval.common import split_of, truncate_jd, get_dedup_key, profile_hash


def load_labels(path: str = "eval/labels.jsonl") -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    records = []
    for line in p.open(encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rec = json.loads(line)
                if not rec.get("dedup_key"):
                    rec["dedup_key"] = get_dedup_key(rec)
                records.append(rec)
            except Exception:
                pass
    return records


def _get_cache_path(model: str, prompt_tag: str) -> Path:
    runs_dir = Path("eval/runs")
    runs_dir.mkdir(parents=True, exist_ok=True)
    safe_model = model.replace(":", "_").replace("/", "_").replace("\\", "_")
    safe_prompt = prompt_tag.replace(":", "_").replace("/", "_")
    return runs_dir / f"{safe_model}_{safe_prompt}.jsonl"


def assert_no_fewshot_leakage(rows: List[Dict[str, Any]]):
    """A7. Few-shot leakage guard: Assert no labeled dedup_key appears in prompt examples."""
    # Prompts contain canonical example titles
    fewshot_titles = [
        "Senior Go Developer, 7+ years, fintech background required",
        "Full Stack Engineer (React/Node.js), 2-4 years, startup environment",
    ]
    fewshot_keys = {
        compute_dedup_key("", t) for t in fewshot_titles
    }
    eval_keys = {r.get("dedup_key") for r in rows if r.get("dedup_key")}
    overlap = fewshot_keys & eval_keys
    if overlap:
        raise AssertionError(f"Few-shot leakage detected! Overlapping keys: {overlap}")


def score_rows(
    rows: List[Dict[str, Any]],
    model: str,
    prompt_tag: str,
    seed: int = 42,
    use_cache: bool = True
) -> List[Tuple[Dict[str, Any], int, str]]:
    """
    Score JDs using evaluate_job_with_qwen with run-caching to eval/runs/{model}_{prompt}.jsonl.
    Returns list of (row, score, reason).
    """
    cache_path = _get_cache_path(model, prompt_tag)
    cached_entries: Dict[str, Tuple[int, str]] = {}

    if use_cache and cache_path.exists():
        for line in cache_path.open(encoding="utf-8"):
            line = line.strip()
            if line:
                try:
                    c = json.loads(line)
                    sc = int(c.get("score", 50))
                    re = c.get("reason", "")
                    if "cache_key" in c:
                        cached_entries[c["cache_key"]] = (sc, re)
                    if "url" in c:
                        cached_entries[c["url"]] = (sc, re)
                except Exception:
                    pass

    out: List[Tuple[Dict[str, Any], int, str]] = []

    cfg = load_config()
    resume_text = extract_resume_text() or ""
    prof_h = profile_hash(cfg, resume_text)

    for r in rows:
        url = r.get("url", "")
        jd = truncate_jd(r.get("jd_text", ""), 2500)
        ch = compute_content_hash(jd)
        cache_key = f"{model}|{prompt_tag}|{ch}|{prof_h}|seed{seed}"

        if use_cache and (cache_key in cached_entries or url in cached_entries):
            sc, re = cached_entries.get(cache_key) or cached_entries[url]
            out.append((r, sc, re))
            continue

        print(f"Scoring [{len(out)+1}/{len(rows)}]: {r.get('title', '')} @ {r.get('company', '')}...", flush=True)
        res = evaluate_job_with_qwen(
            title=r.get("title", ""),
            company=r.get("company", ""),
            description=jd,
            url=url,
            model=model,
            use_cache=False,  # Bypass DB evaluation_cache for pure eval harness
            skip_prefilter=True,
            options={"seed": seed, "temperature": 0.1},
        )
        score = int(res.get("score", 50))
        reason = res.get("reason", "")
        out.append((r, score, reason))
        cached_entries[cache_key] = (score, reason)
        cached_entries[url] = (score, reason)

        entry = {
            "cache_key": cache_key,
            "url": url,
            "dedup_key": r.get("dedup_key", ""),
            "title": r.get("title", ""),
            "company": r.get("company", ""),
            "score": score,
            "reason": reason,
            "model": model,
            "prompt": prompt_tag,
        }
        with cache_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()

    return out


def boot_auc(y: List[int], s: List[int], n: int = 1000, seed: int = 0) -> Tuple[float, float]:
    """Bootstrap 95% confidence interval for ROC-AUC."""
    rng = np.random.default_rng(seed)
    y_arr = np.array(y)
    s_arr = np.array(s)
    vals = []
    for _ in range(n):
        i = rng.integers(0, len(y_arr), len(y_arr))
        if len(set(y_arr[i])) < 2:
            continue
        vals.append(roc_auc_score(y_arr[i], s_arr[i]))
    if not vals:
        return (0.0, 0.0)
    return tuple(np.percentile(vals, [2.5, 97.5]))


def dump_errors(scored: List[Tuple[Dict[str, Any], int, str]], min_score: int, k: int = 5):
    """A4. Print top-k false positives and false negatives with model reasoning."""
    filtered = [x for x in scored if x[0].get("human_label") != "borderline"]
    fp = sorted([x for x in filtered if x[0].get("human_label") == "skip"], key=lambda x: -x[1])[:k]
    fn = sorted([x for x in filtered if x[0].get("human_label") == "apply"], key=lambda x: x[1])[:k]

    print("\n" + "=" * 60)
    print(f" ERROR ANALYSIS & DISAGREEMENTS (Top-{k})")
    print("=" * 60)

    for tag, rows in (("FALSE-APPLY (Human=SKIP, Model Scored High)", fp),
                      ("FALSE-SKIP  (Human=APPLY, Model Scored Low)", fn)):
        print(f"\n== {tag} ==")
        if not rows:
            print("  None found.")
        for r, sc, reason in rows:
            print(f'  [{sc:3d}] {r.get("title", "")} @ {r.get("company", "")}')
            if reason:
                print(f'        Reason: {reason[:200]}')
            if r.get("reason_tag"):
                print(f'        Human Skip Reason: {r.get("reason_tag")}')
    print("=" * 60 + "\n")


def report(scored: List[Tuple[Dict[str, Any], int, str]], min_score: int):
    """A5. Compute and print ROC-AUC, bootstrap CI, specificity, and majority baseline."""
    filtered = [(r, sc, re) for r, sc, re in scored if r.get("human_label") != "borderline"]
    y = [1 if r.get("human_label") == "apply" else 0 for r, _, _ in filtered]
    s = [sc for _, sc, _ in filtered]

    if not y:
        print("No definitive (apply/skip) labels found in evaluated set.")
        return

    print("\n" + "=" * 60)
    print(f" VENTURE EVALUATION HARNESS RESULTS (@min_score={min_score})")
    print("=" * 60)

    pos_count = sum(y)
    neg_count = len(y) - pos_count
    total = len(y)

    apply_scores = [sc for (r, sc, _), yi in zip(filtered, y) if yi == 1]
    skip_scores = [sc for (r, sc, _), yi in zip(filtered, y) if yi == 0]

    apply_mean = float(np.mean(apply_scores)) if apply_scores else 0.0
    skip_mean = float(np.mean(skip_scores)) if skip_scores else 0.0

    if len(set(y)) < 2:
        print(f"Warning: Only one class present (pos={pos_count}, neg={neg_count}). Need both classes for ROC-AUC.")
        auc, lo, hi, rho = 0.0, 0.0, 0.0, 0.0
    else:
        auc = roc_auc_score(y, s)
        lo, hi = boot_auc(y, s)
        corr_res = spearmanr(y, s)
        rho = corr_res.correlation if corr_res else 0.0

    pred = [int(x >= min_score) for x in s]
    cm = confusion_matrix(y, pred, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()

    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    specificity = tn / max(tn + fp, 1)
    accuracy = (tp + tn) / max(total, 1)

    # Majority class baseline (predicts apply for all)
    maj_accuracy = pos_count / max(total, 1)
    maj_precision = pos_count / max(total, 1)
    maj_recall = 1.0
    maj_specificity = 0.0

    print(f"Class Distribution:  n={total} (apply={pos_count} [{pos_count/total*100:.1f}%], skip={neg_count} [{neg_count/total*100:.1f}%])")
    print(f"Per-Class Scores:    apply_mean={apply_mean:.1f} | skip_mean={skip_mean:.1f}")
    if len(set(y)) >= 2:
        print(f"ROC-AUC:             {auc:.3f} [95% CI: {lo:.3f}, {hi:.3f}]")
        print(f"Spearman rho:        {rho:.3f}")
    print(f"Confusion Matrix:    TP={tp}, FP={fp}, TN={tn}, FN={fn}")
    print(f"Precision:           {precision:.2f} ({tp}/{max(tp+fp, 1)})")
    print(f"Recall:              {recall:.2f} ({tp}/{max(tp+fn, 1)})")
    print(f"Specificity:         {specificity:.2f} ({tn}/{max(tn+fp, 1)})")
    print(f"Accuracy:            {accuracy:.2f}")
    print("-" * 60)
    print(f"Majority Baseline:   acc={maj_accuracy:.2f}  prec={maj_precision:.2f}  rec={maj_recall:.2f}  spec={maj_specificity:.2f}  auc=0.500")

    bs = [sc for r, sc, _ in scored if r.get("human_label") == "borderline"]
    if bs:
        print(f"Borderline:          n={len(bs)} mean_score={np.mean(bs):.1f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="VENTURE Model & Prompt Evaluation Harness")
    ap.add_argument("--model", default="qwen2.5-coder:7b", help="Model identifier")
    ap.add_argument("--prompt", default="current", help="Prompt version label (or 'current')")
    ap.add_argument("--split", choices=["tune", "holdout", "all"], default="tune", help="Dataset split (tune 70%%, holdout 30%%, all)")
    ap.add_argument("--min-score", type=int, default=70, help="Approval threshold for precision/recall calculation")
    ap.add_argument("--labels-path", default="eval/labels.jsonl", help="Path to human labels JSONL")
    ap.add_argument("--fresh", "--no-cache", dest="fresh", action="store_true", help="Bypass cached inference results")
    ap.add_argument("--dump-errors", action="store_true", help="Print top false positives and false negatives")
    a = ap.parse_args()

    labels = load_labels(a.labels_path)
    if not labels:
        print(f"No labels found in '{a.labels_path}'.")
        print("Run 'python eval/label_tool.py' first to label real JDs.")
        sys.exit(0)

    cfg = load_config()
    resume_text = extract_resume_text() or ""
    assert len(resume_text) > 500, f"Resume text is too short ({len(resume_text)} chars). Check candidate.resume_path."
    print("=" * 60)
    print(" CANDIDATE EVALUATION PROFILE")
    print("=" * 60)
    print(f"Skills: {cfg.get('candidate', {}).get('skills', [])}")
    print(f"Resume preview (first 200 chars):\n{resume_text[:200]}...")
    print(f"Profile Hash: {profile_hash(cfg, resume_text)}")
    print("=" * 60)

    rows = [r for r in labels if a.split == "all" or split_of(r) == a.split]
    assert_no_fewshot_leakage(rows)
    print(f"Loaded {len(rows)} samples for split='{a.split}' (out of {len(labels)} total labels).")

    p_tag = prompt_version() if a.prompt == "current" else a.prompt
    scored = score_rows(rows, model=a.model, prompt_tag=p_tag, use_cache=not a.fresh)
    report(scored, a.min_score)

    if a.dump_errors:
        dump_errors(scored, a.min_score)
