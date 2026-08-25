"""
Training and evaluation of defect prediction models.
Supports LR, RF, XGBoost with time-aware splitting.
"""

from __future__ import annotations

import json
import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from app.config import settings
from app.features.builder import ALL_FEATURES

logger = logging.getLogger(__name__)


def time_aware_split(
    df: pd.DataFrame,
    train_ratio: float = 0.8,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Split by file age (older -> train, newer -> test) to avoid data leakage."""
    if "file_age_days" in df.columns and df["file_age_days"].nunique() > 10:
        df_sorted = df.sort_values("file_age_days", ascending=False)
        logger.info("Using file_age_days split (older → train, newer → test)")
    elif "snapshot_date" in df.columns and df["snapshot_date"].nunique() > 1:
        df_sorted = df.sort_values("snapshot_date")
        logger.info("Using snapshot_date split")
    else:
        # Fallback: still deterministic, but warn
        logger.warning("No usable time column — falling back to deterministic index split")
        df_sorted = df.reset_index(drop=True)

    split_idx = int(len(df_sorted) * train_ratio)
    train_df = df_sorted.iloc[:split_idx].copy()
    test_df = df_sorted.iloc[split_idx:].copy()

    logger.info(
        "Split: train=%d (%.1f%% buggy), test=%d (%.1f%% buggy)",
        len(train_df),
        100 * train_df["is_buggy"].mean(),
        len(test_df),
        100 * test_df["is_buggy"].mean(),
    )
    return train_df, test_df


def get_feature_importance(model, features: list[str]) -> dict[str, float]:
    if hasattr(model, "feature_importances_"):
        values = model.feature_importances_
    elif hasattr(model, "coef_"):
        values = np.abs(model.coef_).ravel()
        values = values / values.sum() if values.sum() > 0 else values
    else:
        return {}

    importance = dict(zip(features, values.tolist(), strict=False))
    return dict(sorted(importance.items(), key=lambda x: x[1], reverse=True))


def evaluate(y_true, y_pred, y_proba) -> dict:
    return {
        "precision": float(precision_score(y_true, y_pred, zero_division=0)),
        "recall": float(recall_score(y_true, y_pred, zero_division=0)),
        "f1": float(f1_score(y_true, y_pred, zero_division=0)),
        "auc_roc": float(roc_auc_score(y_true, y_proba)) if len(np.unique(y_true)) > 1 else 0.0,
        "confusion_matrix": confusion_matrix(y_true, y_pred).tolist(),
        "classification_report": classification_report(y_true, y_pred, zero_division=0),
    }


def train_model(
    df: pd.DataFrame,
    model_name: str = "random_forest",
    features: list[str] | None = None,
    train_ratio: float = 0.8,
) -> dict:
    if features is None:
        features = [f for f in ALL_FEATURES if f in df.columns]

    train_df, test_df = time_aware_split(df, train_ratio=train_ratio)

    X_train = train_df[features].astype(float).values
    y_train = train_df["is_buggy"].astype(int).values
    X_test = test_df[features].astype(float).values
    y_test = test_df["is_buggy"].astype(int).values

    scaler = None
    if model_name == "logistic_regression":
        scaler = StandardScaler()
        X_train = scaler.fit_transform(X_train)
        X_test = scaler.transform(X_test)
        model = LogisticRegression(
            class_weight="balanced",
            max_iter=2000,
            random_state=42,
        )
    elif model_name == "random_forest":
        model = RandomForestClassifier(
            n_estimators=300,
            max_depth=20,
            min_samples_leaf=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        )
    elif model_name == "xgboost":
        neg_count = int(np.sum(y_train == 0))
        pos_count = int(np.sum(y_train == 1))
        scale = neg_count / max(pos_count, 1)
        model = XGBClassifier(
            n_estimators=300,
            max_depth=8,
            learning_rate=0.05,
            scale_pos_weight=scale,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            eval_metric="logloss",
            n_jobs=-1,
        )
    else:
        raise ValueError(f"Unknown model: {model_name}")

    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]

    metrics = evaluate(y_test, y_pred, y_proba)
    importance = get_feature_importance(model, features)

    logger.info(
        "Model %-20s  P=%.3f  R=%.3f  F1=%.3f  AUC=%.3f",
        model_name,
        metrics["precision"],
        metrics["recall"],
        metrics["f1"],
        metrics["auc_roc"],
    )

    return {
        "model": model,
        "scaler": scaler,
        "metrics": metrics,
        "features": features,
        "feature_importance": importance,
        "model_name": model_name,
        "train_size": len(train_df),
        "test_size": len(test_df),
        "train_buggy_pct": float(100 * y_train.mean()),
        "test_buggy_pct": float(100 * y_test.mean()),
    }


def save_model(result: dict, filename: str | None = None) -> Path:
    if filename is None:
        filename = f"{result['model_name']}_model.pkl"

    path = Path(settings.trained_models_dir)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / path
    path.mkdir(parents=True, exist_ok=True)
    out = path / filename

    payload = {
        "model": result["model"],
        "scaler": result.get("scaler"),
        "features": result["features"],
        "feature_importance": result["feature_importance"],
        "model_name": result["model_name"],
        "metrics": {
            k: v for k, v in result["metrics"].items() if k != "classification_report"
        },
    }
    with open(out, "wb") as f:
        pickle.dump(payload, f)
    logger.info("Model saved to %s", out)
    return out


def save_metrics_report(results: list[dict], output_path: Path) -> None:
    rows = []
    for r in results:
        rows.append({
            "model": r["model_name"],
            "precision": r["metrics"]["precision"],
            "recall": r["metrics"]["recall"],
            "f1": r["metrics"]["f1"],
            "auc_roc": r["metrics"]["auc_roc"],
            "train_size": r["train_size"],
            "test_size": r["test_size"],
            "train_buggy_pct": r["train_buggy_pct"],
            "test_buggy_pct": r["test_buggy_pct"],
            "top_features": list(r["feature_importance"].keys())[:5],
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(output_path.with_suffix(".csv"), index=False)
    with open(output_path.with_suffix(".json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    logger.info("Metrics report saved to %s", output_path.with_suffix(".json"))


def load_model(filename: str) -> dict:
    path = Path(settings.trained_models_dir) / filename
    if not path.is_absolute() and not path.exists():
        path = Path(__file__).resolve().parents[2] / settings.trained_models_dir / filename
    with open(path, "rb") as f:
        return pickle.load(f)
