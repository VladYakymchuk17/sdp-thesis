"""
CLI tool to test the explainability pipeline (SHAP + LLM).

    python run_explain.py --repo-id 1 --file-path "src/index.ts"
    python run_explain.py --repo-id 1 --top 5
    python run_explain.py --random 3
"""

import argparse
import asyncio
import json
import logging
import pickle
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text

from app.config import settings
from app.db.session import SessionLocal
from app.explainers.explainer import (
    compute_shap_values,
    generate_llm_explanation,
    _fallback_explanation,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_explain")

MODELS_DIR = Path(__file__).parent / "trained_models_advanced"

BASE_FEATURES = [
    "commits_count", "unique_authors", "churn", "file_age_days",
    "bug_fix_commits_count", "lines_added_total", "lines_deleted_total",
    "loc", "cyclomatic_complexity", "max_nesting_depth",
    "num_functions", "avg_function_length", "num_parameters_max",
]


def load_model():
    best_path = MODELS_DIR / "best_model.pkl"
    if not best_path.exists():
        all_pkls = sorted(MODELS_DIR.glob("*.pkl"))
        if not all_pkls:
            logger.error("No trained models found in %s", MODELS_DIR)
            sys.exit(1)
        best_path = all_pkls[0]

    with open(best_path, "rb") as f:
        data = pickle.load(f)

    logger.info("Loaded model: %s", data.get("model_name", "unknown"))
    return data


def engineer_features_row(raw: dict) -> dict:
    commits = max(raw.get("commits_count", 1), 1)
    churn_val = max(raw.get("churn", 0), 1)
    loc_val = max(raw.get("loc", 1), 1)
    authors = max(raw.get("unique_authors", 1), 1)

    raw["churn_per_commit"] = churn_val / commits
    raw["complexity_per_loc"] = raw.get("cyclomatic_complexity", 0) / loc_val
    raw["deleted_ratio"] = raw.get("lines_deleted_total", 0) / churn_val
    raw["added_ratio"] = raw.get("lines_added_total", 0) / churn_val
    raw["functions_per_loc"] = raw.get("num_functions", 0) / loc_val
    raw["bugfix_ratio"] = raw.get("bug_fix_commits_count", 0) / commits
    raw["nesting_x_complexity"] = raw.get("max_nesting_depth", 0) * raw.get("cyclomatic_complexity", 0)
    raw["loc_x_age"] = np.log1p(raw.get("loc", 0)) * np.log1p(raw.get("file_age_days", 0))
    raw["authors_per_commit"] = authors / commits
    raw["avg_churn_per_author"] = churn_val / authors
    return raw


def get_files_from_db(repo_id: int = None, file_path: str = None, random_n: int = None):
    db = SessionLocal()
    try:
        if file_path:
            row = db.execute(
                text("""
                    SELECT r.name, fm.file_path,
                           fm.commits_count, fm.unique_authors, fm.churn, fm.file_age_days,
                           fm.bug_fix_commits_count, fm.lines_added_total, fm.lines_deleted_total,
                           fm.loc, fm.cyclomatic_complexity, fm.max_nesting_depth,
                           fm.num_functions, fm.avg_function_length, fm.num_parameters_max
                    FROM file_metrics fm
                    JOIN repositories r ON r.id = fm.repo_id
                    WHERE fm.repo_id = :repo_id AND fm.file_path LIKE :fp AND fm.loc IS NOT NULL
                    LIMIT 1
                """),
                {"repo_id": repo_id, "fp": f"%{file_path}%"},
            ).fetchone()
            if not row:
                logger.error("File not found: repo_id=%s, file_path=%s", repo_id, file_path)
                return []
            return [row]
        else:
            query = """
                SELECT r.name, fm.file_path,
                       fm.commits_count, fm.unique_authors, fm.churn, fm.file_age_days,
                       fm.bug_fix_commits_count, fm.lines_added_total, fm.lines_deleted_total,
                       fm.loc, fm.cyclomatic_complexity, fm.max_nesting_depth,
                       fm.num_functions, fm.avg_function_length, fm.num_parameters_max
                FROM file_metrics fm
                JOIN repositories r ON r.id = fm.repo_id
                WHERE fm.loc IS NOT NULL
            """
            params = {}
            if repo_id:
                query += " AND fm.repo_id = :repo_id"
                params["repo_id"] = repo_id
            query += f" ORDER BY RANDOM() LIMIT {random_n or 3}"
            return db.execute(text(query), params).fetchall()
    finally:
        db.close()


async def explain_file(model_data, row, use_llm: bool = True):
    repo_name = row[0]
    file_path = row[1]
    metrics_values = list(row[2:])

    raw = dict(zip(BASE_FEATURES, metrics_values))
    raw = engineer_features_row(raw)

    feature_names = model_data.get("features", BASE_FEATURES)
    feature_values = [raw.get(f, 0) for f in feature_names]
    X = np.array([feature_values])

    model = model_data["model"]
    risk_score = float(model.predict_proba(X)[0][1])
    risk_level = "high" if risk_score >= 0.7 else "medium" if risk_score >= 0.4 else "low"

    try:
        shap_features = compute_shap_values(model, X, feature_names)
    except Exception as e:
        logger.warning("SHAP failed: %s", e)
        shap_features = dict(zip(feature_names, feature_values))

    if use_llm:
        explanation = await generate_llm_explanation(file_path, risk_score, shap_features, top_n=3)
    else:
        explanation = _fallback_explanation(file_path, risk_score, shap_features)

    return {
        "repo": repo_name,
        "file_path": file_path,
        "risk_score": round(float(risk_score), 4),
        "risk_level": risk_level,
        "top_features": {k: round(float(v), 4) for k, v in list(shap_features.items())[:5]},
        "explanation": explanation,
    }


async def main_async(args):
    model_data = load_model()

    rows = get_files_from_db(
        repo_id=args.repo_id,
        file_path=args.file_path,
        random_n=args.random,
    )

    if not rows:
        logger.error("No files to analyze")
        sys.exit(1)

    results = []
    for row in rows:
        result = await explain_file(model_data, row, use_llm=not args.no_llm)
        results.append(result)

        print("\n" + "=" * 70)
        print(f"  Repo: {result['repo']}")
        print(f"  File: {result['file_path']}")
        print(f"  Risk: {result['risk_score']} ({result['risk_level'].upper()})")
        print("-" * 70)
        print("  Top SHAP features:")
        for name, value in result["top_features"].items():
            direction = "+" if value > 0 else ""
            print(f"    {name:30s}  {direction}{value:.4f}")
        print("-" * 70)
        print(f"  Explanation: {result['explanation']}")
        print("=" * 70)

    output_path = Path(__file__).parent / "data" / "results_advanced" / "explanations.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s", output_path)


def main():
    parser = argparse.ArgumentParser(description="Test SHAP + LLM explainability pipeline")
    parser.add_argument("--repo-id", type=int, help="Repository ID")
    parser.add_argument("--file-path", type=str, help="File path pattern to search")
    parser.add_argument("--random", type=int, default=3, help="Explain N random files (default: 3)")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM, use rule-based fallback only")
    parser.add_argument("--top", type=int, default=5, help="Show top N SHAP features")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
