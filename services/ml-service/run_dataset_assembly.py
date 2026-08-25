"""
Dataset assembly — joins file_metrics with SZZ labels, exports CSV/Parquet, runs EDA.

    python run_dataset_assembly.py
    python run_dataset_assembly.py --format csv
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.features.builder import ALL_FEATURES, export_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_dataset_assembly")

OUTPUT_DIR = Path(__file__).parent / "data" / "datasets"


def normalize_path(path: str) -> str:
    return path.replace("\\", "/").strip().lower()


def load_file_metrics(db, repo_id: int | None = None) -> pd.DataFrame:
    query = """
        SELECT
            fm.repo_id,
            r.name AS repo_name,
            fm.file_path,
            fm.snapshot_date,
            fm.commits_count,
            fm.unique_authors,
            fm.churn,
            fm.file_age_days,
            fm.bug_fix_commits_count,
            fm.lines_added_total,
            fm.lines_deleted_total,
            fm.loc,
            fm.cyclomatic_complexity,
            fm.max_nesting_depth,
            fm.num_functions,
            fm.avg_function_length,
            fm.num_parameters_max
        FROM file_metrics fm
        JOIN repositories r ON r.id = fm.repo_id
        WHERE fm.loc IS NOT NULL
    """
    params: dict = {}
    if repo_id is not None:
        query += " AND fm.repo_id = :repo_id"
        params["repo_id"] = repo_id

    df = pd.read_sql(text(query), engine, params=params)
    df["file_path_norm"] = df["file_path"].map(normalize_path)
    logger.info("Loaded %d file_metrics rows", len(df))
    return df


def load_buggy_files(db, repo_id: int | None = None) -> pd.DataFrame:
    query = """
        SELECT DISTINCT
            repo_id,
            file_path
        FROM bug_labels
        WHERE is_buggy = true
    """
    params: dict = {}
    if repo_id is not None:
        query += " AND repo_id = :repo_id"
        params["repo_id"] = repo_id

    df = pd.read_sql(text(query), engine, params=params)
    df["file_path_norm"] = df["file_path"].map(normalize_path)
    df["is_buggy"] = 1
    logger.info("Loaded %d unique buggy (repo, file) pairs from SZZ", len(df))
    return df


def assemble_dataset(metrics_df: pd.DataFrame, labels_df: pd.DataFrame) -> pd.DataFrame:
    labels_unique = (
        labels_df[["repo_id", "file_path_norm", "is_buggy"]]
        .drop_duplicates(subset=["repo_id", "file_path_norm"])
    )

    dataset = metrics_df.merge(
        labels_unique,
        on=["repo_id", "file_path_norm"],
        how="left",
    )
    dataset["is_buggy"] = dataset["is_buggy"].fillna(0).astype(int)

    missing_features = [f for f in ALL_FEATURES if f not in dataset.columns]
    if missing_features:
        raise ValueError(f"Missing features: {missing_features}")

    before = len(dataset)
    dataset = dataset.dropna(subset=ALL_FEATURES)
    if len(dataset) < before:
        logger.info("Dropped %d rows with missing feature values", before - len(dataset))

    dataset = dataset.drop_duplicates(subset=["repo_id", "file_path_norm"], keep="first")

    logger.info(
        "Dataset assembled: %d rows, %d buggy (%.1f%%), %d clean (%.1f%%)",
        len(dataset),
        dataset["is_buggy"].sum(),
        100 * dataset["is_buggy"].mean(),
        (dataset["is_buggy"] == 0).sum(),
        100 * (1 - dataset["is_buggy"].mean()),
    )
    return dataset


def run_eda(df: pd.DataFrame, output_dir: Path) -> dict:
    eda: dict = {}

    # Class distribution
    class_counts = df["is_buggy"].value_counts().to_dict()
    eda["class_distribution"] = {
        "clean": int(class_counts.get(0, 0)),
        "buggy": int(class_counts.get(1, 0)),
        "buggy_pct": round(100 * df["is_buggy"].mean(), 2),
        "imbalance_ratio": round(
            class_counts.get(0, 0) / max(class_counts.get(1, 1), 1), 2
        ),
    }

    # Per-repo breakdown
    per_repo = (
        df.groupby("repo_name")
        .agg(
            files=("file_path", "count"),
            buggy=("is_buggy", "sum"),
        )
        .assign(buggy_pct=lambda x: (100 * x["buggy"] / x["files"]).round(1))
        .sort_values("files", ascending=False)
    )
    eda["per_repo"] = per_repo.to_dict(orient="index")

    # Feature summary stats
    feature_stats = df[ALL_FEATURES].describe().round(2)
    eda["feature_stats"] = feature_stats.to_dict()

    # Correlation with label
    correlations = (
        df[ALL_FEATURES + ["is_buggy"]]
        .corr(numeric_only=True)["is_buggy"]
        .drop("is_buggy")
        .sort_values(key=abs, ascending=False)
        .round(4)
    )
    eda["label_correlations"] = correlations.to_dict()

    # Save EDA artifacts
    output_dir.mkdir(parents=True, exist_ok=True)
    per_repo.to_csv(output_dir / "eda_per_repo.csv")
    feature_stats.to_csv(output_dir / "eda_feature_stats.csv")
    correlations.to_csv(output_dir / "eda_label_correlations.csv", header=["correlation"])

    with open(output_dir / "eda_summary.json", "w", encoding="utf-8") as f:
        json.dump(eda, f, indent=2, default=str)

    logger.info("EDA written to %s", output_dir)
    return eda


def print_eda_summary(eda: dict) -> None:
    cd = eda["class_distribution"]
    logger.info("=" * 60)
    logger.info("DATASET EDA SUMMARY")
    logger.info("=" * 60)
    logger.info(
        "Class balance: %d clean / %d buggy (%.1f%% buggy, imbalance %.1f:1)",
        cd["clean"],
        cd["buggy"],
        cd["buggy_pct"],
        cd["imbalance_ratio"],
    )
    logger.info("-" * 40)
    logger.info("Per-repo breakdown:")
    for repo, stats in eda["per_repo"].items():
        logger.info(
            "  %-20s  files=%5d  buggy=%5d  (%.1f%%)",
            repo,
            stats["files"],
            stats["buggy"],
            stats["buggy_pct"],
        )
    logger.info("-" * 40)
    logger.info("Top feature correlations with is_buggy:")
    for feat, corr in list(eda["label_correlations"].items())[:8]:
        logger.info("  %-28s  r=%+.4f", feat, corr)
    logger.info("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Assemble ML dataset from mined data")
    parser.add_argument("--repo-id", type=int, help="Assemble for a single repo only")
    parser.add_argument(
        "--format",
        choices=["parquet", "csv", "both"],
        default="both",
        help="Export format (default: both)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        logger.info("Dataset Assembly")
        logger.info("Loading file metrics...")
        metrics_df = load_file_metrics(db, args.repo_id)

        logger.info("Loading SZZ bug labels...")
        labels_df = load_buggy_files(db, args.repo_id)

        logger.info("Joining metrics + labels...")
        dataset = assemble_dataset(metrics_df, labels_df)

        if dataset.empty:
            logger.error("Dataset is empty — nothing to export")
            sys.exit(1)

        export_cols = (
            ["repo_id", "repo_name", "file_path", "snapshot_date"]
            + ALL_FEATURES
            + ["is_buggy"]
        )
        export_df = dataset[export_cols].copy()

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        if args.format in ("parquet", "both"):
            try:
                export_dataset(export_df, str(OUTPUT_DIR / "sdp_dataset.parquet"), "parquet")
            except ImportError:
                logger.warning("pyarrow not installed — skipping parquet. Install with: pip install pyarrow")
                if args.format == "parquet":
                    args.format = "csv"

        if args.format in ("csv", "both"):
            export_dataset(export_df, str(OUTPUT_DIR / "sdp_dataset.csv"), "csv")

        export_df[ALL_FEATURES + ["is_buggy"]].to_csv(
            OUTPUT_DIR / "sdp_features.csv", index=False
        )
        logger.info("Features matrix saved to %s", OUTPUT_DIR / "sdp_features.csv")

        eda = run_eda(export_df, OUTPUT_DIR)
        print_eda_summary(eda)

        logger.info("Done. Dataset ready for training.")

    finally:
        db.close()


if __name__ == "__main__":
    main()
