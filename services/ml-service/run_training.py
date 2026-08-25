"""
Train baseline defect prediction models (LR, RF, XGBoost).

    python run_training.py
    python run_training.py --model random_forest
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from app.features.builder import ALL_FEATURES
from app.models.trainer import save_metrics_report, save_model, train_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_training")

DEFAULT_DATASET = Path(__file__).parent / "data" / "datasets" / "sdp_dataset.parquet"
RESULTS_DIR = Path(__file__).parent / "data" / "results"
MODELS_DIR = Path(__file__).parent / "trained_models"


def load_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        # Fallback to CSV
        csv_path = path.with_suffix(".csv")
        if csv_path.exists():
            path = csv_path
        else:
            raise FileNotFoundError(f"Dataset not found: {path}")

    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    else:
        df = pd.read_csv(path)

    missing = [f for f in ALL_FEATURES if f not in df.columns]
    if missing:
        raise ValueError(f"Dataset missing features: {missing}")
    if "is_buggy" not in df.columns:
        raise ValueError("Dataset missing is_buggy column")

    df = df.dropna(subset=ALL_FEATURES + ["is_buggy"]).copy()
    df["is_buggy"] = df["is_buggy"].astype(int)
    logger.info(
        "Loaded dataset: %d rows, %.1f%% buggy",
        len(df),
        100 * df["is_buggy"].mean(),
    )
    return df


def plot_feature_importance(importance: dict[str, float], model_name: str, out_dir: Path) -> None:
    items = list(importance.items())[:12]
    if not items:
        return

    names = [k for k, _ in items][::-1]
    values = [v for _, v in items][::-1]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(names, values, color="#3b82f6")
    ax.set_xlabel("Importance")
    ax.set_title(f"Feature importance — {model_name}")
    fig.tight_layout()
    out_path = out_dir / f"feature_importance_{model_name}.png"
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    logger.info("Feature importance plot saved to %s", out_path)


def plot_metrics_comparison(results: list[dict], out_dir: Path) -> None:
    models = [r["model_name"] for r in results]
    metrics = ["precision", "recall", "f1", "auc_roc"]

    x = range(len(models))
    width = 0.2
    fig, ax = plt.subplots(figsize=(9, 5))

    for i, metric in enumerate(metrics):
        values = [r["metrics"][metric] for r in results]
        offset = (i - 1.5) * width
        ax.bar([xi + offset for xi in x], values, width, label=metric)

    ax.set_xticks(list(x))
    ax.set_xticklabels(models, rotation=15)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score")
    ax.set_title("Model comparison (time-aware test split)")
    ax.legend()
    fig.tight_layout()
    out_path = out_dir / "model_comparison.png"
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    logger.info("Comparison plot saved to %s", out_path)


def try_shap_summary(result: dict, df: pd.DataFrame, out_dir: Path, sample_size: int = 500) -> None:
    if result["model_name"] not in ("random_forest", "xgboost"):
        return

    try:
        import shap
    except ImportError:
        logger.warning("shap not available — skipping SHAP plot")
        return

    features = result["features"]
    sample = df[features].astype(float).sample(
        n=min(sample_size, len(df)), random_state=42
    )

    try:
        explainer = shap.TreeExplainer(result["model"])
        shap_values = explainer.shap_values(sample.values)

        # Binary classifiers may return list [class0, class1]
        if isinstance(shap_values, list):
            values = shap_values[1]
        else:
            values = shap_values
            # RF sometimes returns (n, features, 2)
            if getattr(values, "ndim", 0) == 3:
                values = values[:, :, 1]

        plt.figure(figsize=(9, 6))
        shap.summary_plot(values, sample, feature_names=features, show=False)
        out_path = out_dir / f"shap_summary_{result['model_name']}.png"
        plt.tight_layout()
        plt.savefig(out_path, dpi=120, bbox_inches="tight")
        plt.close()
        logger.info("SHAP summary saved to %s", out_path)
    except Exception as e:
        logger.warning("SHAP failed for %s: %s", result["model_name"], e)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train SDP defect prediction models")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
        help="Path to dataset parquet/csv",
    )
    parser.add_argument(
        "--model",
        choices=["logistic_regression", "random_forest", "xgboost", "all"],
        default="all",
        help="Which model(s) to train",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--skip-shap", action="store_true", help="Skip SHAP plots (faster)")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    from app.config import settings
    settings.trained_models_dir = str(MODELS_DIR)

    df = load_dataset(args.dataset)

    model_names = (
        ["logistic_regression", "random_forest", "xgboost"]
        if args.model == "all"
        else [args.model]
    )

    logger.info("=" * 60)
    logger.info("ML Training Pipeline")
    logger.info("=" * 60)
    logger.info("Models: %s", ", ".join(model_names))
    logger.info("Features: %s", ", ".join(ALL_FEATURES))

    results = []
    for name in model_names:
        logger.info("-" * 40)
        logger.info("Training %s ...", name)
        result = train_model(df, model_name=name, train_ratio=args.train_ratio)
        save_model(result, f"{name}_model.pkl")
        plot_feature_importance(result["feature_importance"], name, RESULTS_DIR)

        if not args.skip_shap:
            try_shap_summary(result, df, RESULTS_DIR)

            logger.info("\n%s", result["metrics"]["classification_report"])
        results.append(result)

    save_metrics_report(results, RESULTS_DIR / "model_metrics")
    if len(results) > 1:
        plot_metrics_comparison(results, RESULTS_DIR)

    best = max(results, key=lambda r: r["metrics"]["f1"])
    save_model(best, "best_model.pkl")

    logger.info("=" * 60)
    logger.info("TRAINING SUMMARY")
    logger.info("=" * 60)
    for r in results:
        m = r["metrics"]
        logger.info(
            "  %-22s  P=%.3f  R=%.3f  F1=%.3f  AUC=%.3f",
            r["model_name"],
            m["precision"],
            m["recall"],
            m["f1"],
            m["auc_roc"],
        )
    logger.info(
        "Best model: %s (F1=%.3f)",
        best["model_name"],
        best["metrics"]["f1"],
    )
    logger.info("Models saved to: %s", MODELS_DIR)
    logger.info("Results saved to: %s", RESULTS_DIR)
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("Training failed")
        sys.exit(1)
