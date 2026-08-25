"""
Extended model training — hyperparameter tuning, ensembles, SMOTE comparison.

    python run_advanced_training.py
    python run_advanced_training.py --skip-tuning
    python run_advanced_training.py --skip-shap
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
import time
import warnings
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.ensemble import (
    ExtraTreesClassifier,
    GradientBoostingClassifier,
    RandomForestClassifier,
    StackingClassifier,
    VotingClassifier,
)
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    classification_report,
    confusion_matrix,
    f1_score,
    matthews_corrcoef,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
    roc_curve,
    average_precision_score,
)
from sklearn.model_selection import RandomizedSearchCV, StratifiedKFold, cross_validate
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from imblearn.over_sampling import SMOTE

warnings.filterwarnings("ignore", category=UserWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("advanced_training")

BASE_DIR = Path(__file__).parent
DEFAULT_DATASET = BASE_DIR / "data" / "datasets" / "sdp_features.csv"
RESULTS_DIR = BASE_DIR / "data" / "results_advanced"
MODELS_DIR = BASE_DIR / "trained_models_advanced"

BASE_FEATURES = [
    "commits_count", "unique_authors", "churn", "file_age_days",
    "bug_fix_commits_count", "lines_added_total", "lines_deleted_total",
    "loc", "cyclomatic_complexity", "max_nesting_depth",
    "num_functions", "avg_function_length", "num_parameters_max",
]


def load_dataset(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    df = df.dropna(subset=BASE_FEATURES + ["is_buggy"]).copy()
    df["is_buggy"] = df["is_buggy"].astype(int)
    logger.info("Loaded %d rows, %.1f%% buggy", len(df), 100 * df["is_buggy"].mean())
    return df


def engineer_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Create ratio and interaction features on top of base metrics."""
    df = df.copy()

    df["churn_per_commit"] = df["churn"] / df["commits_count"].clip(lower=1)
    df["complexity_per_loc"] = df["cyclomatic_complexity"] / df["loc"].clip(lower=1)
    df["deleted_ratio"] = df["lines_deleted_total"] / df["churn"].clip(lower=1)
    df["added_ratio"] = df["lines_added_total"] / df["churn"].clip(lower=1)
    df["functions_per_loc"] = df["num_functions"] / df["loc"].clip(lower=1)
    df["bugfix_ratio"] = df["bug_fix_commits_count"] / df["commits_count"].clip(lower=1)
    df["nesting_x_complexity"] = df["max_nesting_depth"] * df["cyclomatic_complexity"]
    df["loc_x_age"] = np.log1p(df["loc"]) * np.log1p(df["file_age_days"])
    df["authors_per_commit"] = df["unique_authors"] / df["commits_count"].clip(lower=1)
    df["avg_churn_per_author"] = df["churn"] / df["unique_authors"].clip(lower=1)

    engineered = [
        "churn_per_commit", "complexity_per_loc", "deleted_ratio", "added_ratio",
        "functions_per_loc", "bugfix_ratio", "nesting_x_complexity",
        "loc_x_age", "authors_per_commit", "avg_churn_per_author",
    ]
    all_features = BASE_FEATURES + engineered
    return df, all_features


def time_aware_split(df: pd.DataFrame, ratio: float = 0.8):
    df_sorted = df.sort_values("file_age_days", ascending=False)
    idx = int(len(df_sorted) * ratio)
    train, test = df_sorted.iloc[:idx].copy(), df_sorted.iloc[idx:].copy()
    logger.info(
        "Split: train=%d (%.1f%% buggy) | test=%d (%.1f%% buggy)",
        len(train), 100 * train["is_buggy"].mean(),
        len(test), 100 * test["is_buggy"].mean(),
    )
    return train, test


def build_models(skip_tuning: bool = False) -> dict:
    models = {}

    models["logistic_regression"] = (
        LogisticRegression(class_weight="balanced", max_iter=2000, random_state=42, solver="saga"),
        {
            "C": [0.01, 0.1, 1, 10, 100],
            "l1_ratio": [0.0, 0.25, 0.5, 0.75, 1.0],
        } if not skip_tuning else None,
    )

    models["random_forest"] = (
        RandomForestClassifier(class_weight="balanced", random_state=42, n_jobs=4),
        {
            "n_estimators": [200, 400],
            "max_depth": [10, 20, 30],
            "min_samples_split": [2, 5, 10],
            "min_samples_leaf": [2, 4, 8],
            "max_features": ["sqrt", "log2"],
        } if not skip_tuning else None,
    )

    models["xgboost"] = (
        XGBClassifier(
            eval_metric="logloss", random_state=42, n_jobs=4,
            tree_method="hist",
        ),
        {
            "n_estimators": [200, 400],
            "max_depth": [4, 6, 8],
            "learning_rate": [0.01, 0.05, 0.1],
            "subsample": [0.7, 0.8, 0.9],
            "colsample_bytree": [0.6, 0.8, 1.0],
            "scale_pos_weight": [0.8, 1.0, 1.5],
        } if not skip_tuning else None,
    )

    models["lightgbm"] = (
        LGBMClassifier(
            is_unbalance=True, random_state=42, n_jobs=4, verbose=-1,
        ),
        {
            "n_estimators": [200, 400],
            "max_depth": [6, 10, -1],
            "learning_rate": [0.01, 0.05, 0.1],
            "num_leaves": [31, 63, 127],
            "subsample": [0.7, 0.8, 0.9],
            "colsample_bytree": [0.6, 0.8, 1.0],
        } if not skip_tuning else None,
    )

    models["extra_trees"] = (
        ExtraTreesClassifier(
            n_estimators=400, class_weight="balanced", random_state=42, n_jobs=4,
        ),
        {
            "n_estimators": [300, 500],
            "max_depth": [15, 20, None],
            "min_samples_leaf": [2, 5],
        } if not skip_tuning else None,
    )

    models["gradient_boosting"] = (
        GradientBoostingClassifier(
            random_state=42, n_iter_no_change=15, validation_fraction=0.1,
        ),
        {
            "n_estimators": [200, 400],
            "max_depth": [4, 6, 8],
            "learning_rate": [0.01, 0.05, 0.1],
            "subsample": [0.8, 0.9, 1.0],
            "min_samples_leaf": [5, 10],
        } if not skip_tuning else None,
    )

    return models


def tune_and_train(
    name: str, model, param_grid, X_train, y_train, X_test, y_test, cv_folds=5,
) -> dict:
    t0 = time.time()
    cv = StratifiedKFold(n_splits=min(cv_folds, 3), shuffle=True, random_state=42)

    if param_grid is not None:
        n_iter = 15
        logger.info("  Tuning %s with RandomizedSearchCV (%d iters, %d-fold)...", name, n_iter, cv_folds)
        search = RandomizedSearchCV(
            model, param_grid,
            n_iter=n_iter, scoring="f1", cv=cv,
            random_state=42, n_jobs=4, verbose=0,
        )
        search.fit(X_train, y_train)
        best_model = search.best_estimator_
        best_params = search.best_params_
        cv_f1 = search.best_score_
        logger.info("  Best params: %s (CV F1=%.4f)", best_params, cv_f1)
    else:
        best_model = model
        best_model.fit(X_train, y_train)
        best_params = {}
        cv_scores = cross_validate(
            model, X_train, y_train, cv=cv, scoring="f1", n_jobs=4,
        )
        cv_f1 = float(cv_scores["test_score"].mean())

    y_pred = best_model.predict(X_test)
    y_proba = best_model.predict_proba(X_test)[:, 1]

    elapsed = time.time() - t0
    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y_test, y_proba)),
        "auc_pr": float(average_precision_score(y_test, y_proba)),
        "mcc": float(matthews_corrcoef(y_test, y_pred)),
        "cv_f1_mean": float(cv_f1),
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
    }

    importance = {}
    if hasattr(best_model, "feature_importances_"):
        importance = dict(zip(BASE_FEATURES, best_model.feature_importances_.tolist()))
    elif hasattr(best_model, "coef_"):
        vals = np.abs(best_model.coef_).ravel()
        vals = vals / vals.sum() if vals.sum() > 0 else vals

    importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True)) if importance else {}

    logger.info(
        "  %-22s P=%.3f R=%.3f F1=%.3f AUC=%.3f MCC=%.3f (%.1fs)",
        name, metrics["precision"], metrics["recall"], metrics["f1"],
        metrics["auc_roc"], metrics["mcc"], elapsed,
    )

    return {
        "model_name": name,
        "model": best_model,
        "metrics": metrics,
        "best_params": best_params,
        "feature_importance": importance,
        "y_test": y_test,
        "y_pred": y_pred,
        "y_proba": y_proba,
        "elapsed_s": elapsed,
    }


def train_smote_variant(
    name: str, model, X_train, y_train, X_test, y_test,
) -> dict:
    t0 = time.time()
    smote = SMOTE(random_state=42)
    X_res, y_res = smote.fit_resample(X_train, y_train)
    logger.info("  SMOTE resampled: %d → %d rows", len(X_train), len(X_res))

    model.fit(X_res, y_res)
    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    elapsed = time.time() - t0

    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y_test, y_proba)),
        "auc_pr": float(average_precision_score(y_test, y_proba)),
        "mcc": float(matthews_corrcoef(y_test, y_pred)),
        "cv_f1_mean": 0.0,
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
    }

    importance = {}
    if hasattr(model, "feature_importances_"):
        importance = dict(zip(BASE_FEATURES, model.feature_importances_.tolist()))
    importance = dict(sorted(importance.items(), key=lambda x: x[1], reverse=True)) if importance else {}

    logger.info(
        "  %-22s P=%.3f R=%.3f F1=%.3f AUC=%.3f MCC=%.3f (%.1fs)",
        name, metrics["precision"], metrics["recall"], metrics["f1"],
        metrics["auc_roc"], metrics["mcc"], elapsed,
    )

    return {
        "model_name": name,
        "model": model,
        "metrics": metrics,
        "best_params": {},
        "feature_importance": importance,
        "y_test": y_test,
        "y_pred": y_pred,
        "y_proba": y_proba,
        "elapsed_s": elapsed,
    }


def build_stacking_ensemble(X_train, y_train, X_test, y_test) -> dict:
    t0 = time.time()
    logger.info("  Building Stacking Ensemble (RF + XGB + LGBM → LR)...")

    estimators = [
        ("rf", RandomForestClassifier(
            n_estimators=200, max_depth=20, class_weight="balanced",
            random_state=42, n_jobs=2,
        )),
        ("xgb", XGBClassifier(
            n_estimators=200, max_depth=8, learning_rate=0.05,
            eval_metric="logloss", random_state=42, n_jobs=2,
            tree_method="hist",
        )),
        ("lgbm", LGBMClassifier(
            n_estimators=200, max_depth=10, learning_rate=0.05,
            is_unbalance=True, random_state=42, n_jobs=2, verbose=-1,
        )),
    ]

    stacking = StackingClassifier(
        estimators=estimators,
        final_estimator=LogisticRegression(max_iter=1000, random_state=42),
        cv=3,
        n_jobs=2,
        passthrough=False,
    )
    stacking.fit(X_train, y_train)

    y_pred = stacking.predict(X_test)
    y_proba = stacking.predict_proba(X_test)[:, 1]
    elapsed = time.time() - t0

    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y_test, y_proba)),
        "auc_pr": float(average_precision_score(y_test, y_proba)),
        "mcc": float(matthews_corrcoef(y_test, y_pred)),
        "cv_f1_mean": 0.0,
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
    }

    logger.info(
        "  %-22s P=%.3f R=%.3f F1=%.3f AUC=%.3f MCC=%.3f (%.1fs)",
        "stacking_ensemble", metrics["precision"], metrics["recall"], metrics["f1"],
        metrics["auc_roc"], metrics["mcc"], elapsed,
    )

    return {
        "model_name": "stacking_ensemble",
        "model": stacking,
        "metrics": metrics,
        "best_params": {},
        "feature_importance": {},
        "y_test": y_test,
        "y_pred": y_pred,
        "y_proba": y_proba,
        "elapsed_s": elapsed,
    }


def build_voting_ensemble(X_train, y_train, X_test, y_test) -> dict:
    t0 = time.time()
    logger.info("  Building Voting Ensemble (RF + XGB + LGBM + ET, soft)...")

    estimators = [
        ("rf", RandomForestClassifier(
            n_estimators=200, max_depth=20, class_weight="balanced",
            random_state=42, n_jobs=2,
        )),
        ("xgb", XGBClassifier(
            n_estimators=200, max_depth=8, learning_rate=0.05,
            eval_metric="logloss", random_state=42, n_jobs=2,
            tree_method="hist",
        )),
        ("lgbm", LGBMClassifier(
            n_estimators=200, max_depth=10, learning_rate=0.05,
            is_unbalance=True, random_state=42, n_jobs=2, verbose=-1,
        )),
        ("et", ExtraTreesClassifier(
            n_estimators=200, max_depth=20, class_weight="balanced",
            random_state=42, n_jobs=2,
        )),
    ]

    voting = VotingClassifier(estimators=estimators, voting="soft", n_jobs=2)
    voting.fit(X_train, y_train)

    y_pred = voting.predict(X_test)
    y_proba = voting.predict_proba(X_test)[:, 1]
    elapsed = time.time() - t0

    metrics = {
        "precision": float(precision_score(y_test, y_pred, zero_division=0)),
        "recall": float(recall_score(y_test, y_pred, zero_division=0)),
        "f1": float(f1_score(y_test, y_pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y_test, y_proba)),
        "auc_pr": float(average_precision_score(y_test, y_proba)),
        "mcc": float(matthews_corrcoef(y_test, y_pred)),
        "cv_f1_mean": 0.0,
        "confusion_matrix": confusion_matrix(y_test, y_pred).tolist(),
    }

    logger.info(
        "  %-22s P=%.3f R=%.3f F1=%.3f AUC=%.3f MCC=%.3f (%.1fs)",
        "voting_ensemble", metrics["precision"], metrics["recall"], metrics["f1"],
        metrics["auc_roc"], metrics["mcc"], elapsed,
    )

    return {
        "model_name": "voting_ensemble",
        "model": voting,
        "metrics": metrics,
        "best_params": {},
        "feature_importance": {},
        "y_test": y_test,
        "y_pred": y_pred,
        "y_proba": y_proba,
        "elapsed_s": elapsed,
    }



def plot_all_roc_curves(results: list[dict], out_dir: Path):
    fig, ax = plt.subplots(figsize=(9, 7))
    for r in results:
        fpr, tpr, _ = roc_curve(r["y_test"], r["y_proba"])
        ax.plot(fpr, tpr, label=f"{r['model_name']} (AUC={r['metrics']['auc_roc']:.3f})")
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4)
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title("ROC Curves — All Models")
    ax.legend(fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(out_dir / "roc_curves_all.png", dpi=150)
    plt.close(fig)


def plot_all_pr_curves(results: list[dict], out_dir: Path):
    fig, ax = plt.subplots(figsize=(9, 7))
    for r in results:
        prec, rec, _ = precision_recall_curve(r["y_test"], r["y_proba"])
        ax.plot(rec, prec, label=f"{r['model_name']} (AP={r['metrics']['auc_pr']:.3f})")
    ax.set_xlabel("Recall")
    ax.set_ylabel("Precision")
    ax.set_title("Precision-Recall Curves — All Models")
    ax.legend(fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(out_dir / "pr_curves_all.png", dpi=150)
    plt.close(fig)


def plot_confusion_matrices(results: list[dict], out_dir: Path):
    n = len(results)
    cols = min(4, n)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(4 * cols, 4 * rows))
    if n == 1:
        axes = np.array([axes])
    axes = axes.flatten()

    for i, r in enumerate(results):
        cm = confusion_matrix(r["y_test"], r["y_pred"])
        disp = ConfusionMatrixDisplay(cm, display_labels=["Clean", "Buggy"])
        disp.plot(ax=axes[i], cmap="Blues", colorbar=False)
        axes[i].set_title(r["model_name"], fontsize=9)

    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    fig.suptitle("Confusion Matrices", fontsize=12)
    fig.tight_layout()
    fig.savefig(out_dir / "confusion_matrices_all.png", dpi=150)
    plt.close(fig)


def plot_metrics_comparison(results: list[dict], out_dir: Path):
    metrics_to_plot = ["precision", "recall", "f1", "auc_roc", "auc_pr", "mcc"]
    models = [r["model_name"] for r in results]
    x = np.arange(len(models))
    width = 0.12

    fig, ax = plt.subplots(figsize=(14, 6))
    for i, metric in enumerate(metrics_to_plot):
        values = [r["metrics"][metric] for r in results]
        offset = (i - len(metrics_to_plot) / 2 + 0.5) * width
        bars = ax.bar(x + offset, values, width, label=metric)

    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=25, ha="right", fontsize=8)
    ax.set_ylim(0, 1.1)
    ax.set_ylabel("Score")
    ax.set_title("Model Comparison — All Metrics (Time-Aware Split)")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_dir / "model_comparison_advanced.png", dpi=150)
    plt.close(fig)


def plot_feature_importance_top(results: list[dict], features: list[str], out_dir: Path):
    tree_results = [r for r in results if r["feature_importance"]]
    if not tree_results:
        return

    n = len(tree_results)
    fig, axes = plt.subplots(1, n, figsize=(6 * n, 5))
    if n == 1:
        axes = [axes]

    for ax, r in zip(axes, tree_results):
        imp = r["feature_importance"]
        items = list(imp.items())[:10]
        names = [k for k, _ in items][::-1]
        vals = [v for _, v in items][::-1]
        ax.barh(names, vals, color="#3b82f6")
        ax.set_title(f"Feature Importance — {r['model_name']}", fontsize=9)
        ax.set_xlabel("Importance")

    fig.tight_layout()
    fig.savefig(out_dir / "feature_importance_comparison.png", dpi=150)
    plt.close(fig)


def try_shap(results: list[dict], X_test_df: pd.DataFrame, out_dir: Path):
    try:
        import shap
    except ImportError:
        logger.warning("SHAP not installed — skipping")
        return

    for r in results:
        if r["model_name"] not in ("xgboost", "lightgbm", "random_forest"):
            continue
        try:
            sample = X_test_df.sample(n=min(300, len(X_test_df)), random_state=42)
            explainer = shap.TreeExplainer(r["model"])
            shap_values = explainer.shap_values(sample.values)

            if isinstance(shap_values, list):
                sv = shap_values[1]
            else:
                sv = shap_values
                if getattr(sv, "ndim", 0) == 3:
                    sv = sv[:, :, 1]

            plt.figure(figsize=(10, 6))
            shap.summary_plot(sv, sample, feature_names=list(sample.columns), show=False)
            plt.tight_layout()
            plt.savefig(out_dir / f"shap_{r['model_name']}.png", dpi=150, bbox_inches="tight")
            plt.close()
            logger.info("  SHAP saved for %s", r["model_name"])
        except Exception as e:
            logger.warning("  SHAP failed for %s: %s", r["model_name"], e)



def main():
    parser = argparse.ArgumentParser(description="Advanced SDP ML Training")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--skip-tuning", action="store_true", help="Skip hyperparameter search")
    parser.add_argument("--skip-shap", action="store_true", help="Skip SHAP plots")
    parser.add_argument("--skip-ensembles", action="store_true", help="Skip ensemble models")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    df = load_dataset(args.dataset)
    df, all_features = engineer_features(df)
    train_df, test_df = time_aware_split(df, ratio=args.train_ratio)

    X_train = train_df[all_features].astype(float)
    y_train = train_df["is_buggy"].astype(int).values
    X_test = test_df[all_features].astype(float)
    y_test = test_df["is_buggy"].astype(int).values

    X_train_np = X_train.values
    X_test_np = X_test.values

    logger.info("=" * 70)
    logger.info("ADVANCED ML TRAINING — %d features, %d train, %d test", len(all_features), len(X_train), len(X_test))
    logger.info("Features: %s", ", ".join(all_features))
    logger.info("=" * 70)

    models_def = build_models(skip_tuning=args.skip_tuning)
    all_results: list[dict] = []

    for name, (model, grid) in models_def.items():
        logger.info("─" * 50)
        logger.info("Training: %s", name)

        if name == "logistic_regression":
            scaler = StandardScaler()
            Xtr = scaler.fit_transform(X_train_np)
            Xte = scaler.transform(X_test_np)
        else:
            Xtr, Xte = X_train_np, X_test_np

        result = tune_and_train(name, model, grid, Xtr, y_train, Xte, y_test)
        all_results.append(result)

    logger.info("─" * 50)
    logger.info("Training: xgboost + SMOTE")
    smote_model = XGBClassifier(
        n_estimators=400, max_depth=8, learning_rate=0.05,
        eval_metric="logloss", random_state=42, n_jobs=4,
        tree_method="hist",
    )
    smote_result = train_smote_variant(
        "xgboost_smote", smote_model, X_train_np, y_train, X_test_np, y_test,
    )
    all_results.append(smote_result)

    if not args.skip_ensembles:
        logger.info("─" * 50)
        stacking_result = build_stacking_ensemble(X_train_np, y_train, X_test_np, y_test)
        all_results.append(stacking_result)

        logger.info("─" * 50)
        voting_result = build_voting_ensemble(X_train_np, y_train, X_test_np, y_test)
        all_results.append(voting_result)

    logger.info("=" * 70)
    logger.info("Generating plots...")
    plot_all_roc_curves(all_results, RESULTS_DIR)
    plot_all_pr_curves(all_results, RESULTS_DIR)
    plot_confusion_matrices(all_results, RESULTS_DIR)
    plot_metrics_comparison(all_results, RESULTS_DIR)
    plot_feature_importance_top(all_results, all_features, RESULTS_DIR)

    if not args.skip_shap:
        logger.info("Generating SHAP plots (sampled)...")
        try_shap(all_results, X_test, RESULTS_DIR)

    rows = []
    for r in all_results:
        model_path = MODELS_DIR / f"{r['model_name']}_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump({
                "model": r["model"],
                "features": all_features,
                "feature_importance": r["feature_importance"],
                "model_name": r["model_name"],
                "metrics": {k: v for k, v in r["metrics"].items() if k != "confusion_matrix"},
                "best_params": r["best_params"],
            }, f)

        rows.append({
            "model": r["model_name"],
            "precision": r["metrics"]["precision"],
            "recall": r["metrics"]["recall"],
            "f1": r["metrics"]["f1"],
            "auc_roc": r["metrics"]["auc_roc"],
            "auc_pr": r["metrics"]["auc_pr"],
            "mcc": r["metrics"]["mcc"],
            "cv_f1": r["metrics"]["cv_f1_mean"],
            "train_time_s": round(r["elapsed_s"], 1),
            "top_features": list(r["feature_importance"].keys())[:5] if r["feature_importance"] else [],
            "best_params": r["best_params"],
        })

    report_df = pd.DataFrame(rows)
    report_df.to_csv(RESULTS_DIR / "advanced_model_metrics.csv", index=False)
    with open(RESULTS_DIR / "advanced_model_metrics.json", "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)

    best = max(all_results, key=lambda r: r["metrics"]["f1"])
    best_path = MODELS_DIR / "best_model.pkl"
    with open(best_path, "wb") as f:
        pickle.dump({
            "model": best["model"],
            "features": all_features,
            "feature_importance": best["feature_importance"],
            "model_name": best["model_name"],
            "metrics": best["metrics"],
            "best_params": best["best_params"],
        }, f)

    logger.info("=" * 70)
    logger.info("FINAL RESULTS SUMMARY")
    logger.info("=" * 70)
    logger.info(
        "  %-24s %8s %8s %8s %8s %8s %8s",
        "Model", "Prec", "Recall", "F1", "AUC-ROC", "AUC-PR", "MCC",
    )
    logger.info("  " + "-" * 76)
    for r in sorted(all_results, key=lambda x: x["metrics"]["f1"], reverse=True):
        m = r["metrics"]
        logger.info(
            "  %-24s %8.4f %8.4f %8.4f %8.4f %8.4f %8.4f",
            r["model_name"], m["precision"], m["recall"], m["f1"],
            m["auc_roc"], m["auc_pr"], m["mcc"],
        )
    logger.info("  " + "-" * 76)
    logger.info("  BEST MODEL: %s (F1=%.4f, AUC-ROC=%.4f)", best["model_name"], best["metrics"]["f1"], best["metrics"]["auc_roc"])
    logger.info("")
    logger.info("  Models saved to:  %s", MODELS_DIR)
    logger.info("  Results saved to: %s", RESULTS_DIR)
    logger.info("=" * 70)

    # Print full classification reports for top 3
    top3 = sorted(all_results, key=lambda x: x["metrics"]["f1"], reverse=True)[:3]
    for r in top3:
        logger.info("\n--- Classification Report: %s ---", r["model_name"])
        logger.info("\n%s", classification_report(r["y_test"], r["y_pred"], target_names=["Clean", "Buggy"]))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Advanced training failed")
        sys.exit(1)
