# eval/reconcile_rag.py
import os
import sys
import json
import hashlib
from pathlib import Path
import numpy as np
from sklearn.metrics import roc_auc_score

WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from core.config_manager import load_config
from core.resume_parser import extract_resume_text
from core.rag_scorer import get_top_k_bullets_and_score, get_model
from automation.composite_scorer import evaluate_opportunity
from eval.common import split_of, truncate_jd

cfg = load_config()
resume_path = cfg["candidate"].get("resume_path", "")
cand_resume = extract_resume_text() or ""
cand_sha8 = hashlib.sha256(cand_resume.encode("utf-8")).hexdigest()[:8] if cand_resume else "none"

tailored_path = "tailored_resumes/Resume_Test_Tech_Corp_Full_Stack_Developer_20260808_173753.pdf"
tailored_text = ""
if os.path.exists(tailored_path):
    import pypdf
    reader = pypdf.PdfReader(tailored_path)
    tailored_text = "\n".join(page.extract_text() or "" for page in reader.pages)
tailored_sha8 = hashlib.sha256(tailored_text.encode("utf-8")).hexdigest()[:8] if tailored_text else "none"

model_name = "sentence-transformers/all-MiniLM-L6-v2"

print("=" * 70)
print(f"RAG RECONCILIATION & INPUT AUDIT")
print(f"embedding_model: {model_name}")
print("=" * 70)
print(f"Current candidate resume:")
print(f"  Path:   {resume_path}")
print(f"  Length: {len(cand_resume)} chars")
print(f"  SHA8:   {cand_sha8}")
print(f"Tailored test PDF (used in early baselines run when resume_path was empty):")
print(f"  Path:   {tailored_path}")
print(f"  Length: {len(tailored_text)} chars")
print(f"  SHA8:   {tailored_sha8}")
print("-" * 70)

rows = [json.loads(l) for l in open("eval/labels.jsonl", encoding="utf-8") if l.strip()]
rows = [r for r in rows if r.get("human_label") != "borderline"]
y = np.array([r["human_label"] == "apply" for r in rows], int)
mask_tune = np.array([split_of(r) == "tune" for r in rows])

# 1. RAG with candidate base resume (baselines.py style: truncate_jd 3000)
cand_rag_base = [get_top_k_bullets_and_score(cand_resume, truncate_jd(r.get("jd_text", ""), 3000))[1] for r in rows]

# 2. RAG with candidate base resume (composite_scorer evaluate_opportunity style)
cand_comp_res = [evaluate_opportunity(r["title"], r.get("company", ""), r["jd_text"]) for r in rows]
cand_rag_ablate = [x.rag_score for x in cand_comp_res]

# 3. RAG with tailored test PDF (fallback used when resume_path was empty)
tailored_rag = [get_top_k_bullets_and_score(tailored_text, truncate_jd(r.get("jd_text", ""), 3000))[1] for r in rows]

cand_base_auc = roc_auc_score(y, cand_rag_base)
cand_tune_auc = roc_auc_score(y[mask_tune], np.array(cand_rag_base)[mask_tune])
cand_ablate_auc = roc_auc_score(y, cand_rag_ablate)
max_diff = np.max(np.abs(np.array(cand_rag_base) - np.array(cand_rag_ablate)))

tailored_base_auc = roc_auc_score(y, tailored_rag)
tailored_tune_auc = roc_auc_score(y[mask_tune], np.array(tailored_rag)[mask_tune])

print("EVALUATION RESULTS (SAME SESSION, SAME LABELS):")
print(f"1. Candidate Resume (baselines.py path):   AUC All={cand_base_auc:.3f} | AUC Tune={cand_tune_auc:.3f}")
print(f"2. Candidate Resume (composite path):      AUC All={cand_ablate_auc:.3f} (max diff vs baseline path: {max_diff:.6f})")
print(f"3. Tailored PDF (early run fallback):     AUC All={tailored_base_auc:.3f} | AUC Tune={tailored_tune_auc:.3f}")
print("=" * 70)
