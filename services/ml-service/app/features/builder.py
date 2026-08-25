"""
Feature definitions and dataset export helpers.
"""

import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

GIT_FEATURES = [
    "commits_count",
    "unique_authors",
    "churn",
    "file_age_days",
    "bug_fix_commits_count",
    "lines_added_total",
    "lines_deleted_total",
]

STATIC_FEATURES = [
    "loc",
    "cyclomatic_complexity",
    "max_nesting_depth",
    "num_functions",
    "avg_function_length",
    "num_parameters_max",
]

ALL_FEATURES = GIT_FEATURES + STATIC_FEATURES


def build_dataset(
    git_metrics_df: pd.DataFrame,
    static_metrics_df: pd.DataFrame,
    labels_df: pd.DataFrame,
) -> pd.DataFrame:
    dataset = git_metrics_df.merge(
        static_metrics_df,
        on=["file_path", "snapshot_date"],
        how="inner",
    )

    dataset = dataset.merge(
        labels_df[["file_path", "snapshot_date", "is_buggy"]],
        on=["file_path", "snapshot_date"],
        how="left",
    )

    dataset["is_buggy"] = dataset["is_buggy"].fillna(0).astype(int)

    logger.info(
        "Dataset built: %d rows, %d buggy (%.1f%%)",
        len(dataset),
        dataset["is_buggy"].sum(),
        100 * dataset["is_buggy"].mean(),
    )

    return dataset


def export_dataset(df: pd.DataFrame, output_path: str, fmt: str = "parquet") -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "parquet":
        df.to_parquet(path, index=False)
    elif fmt == "csv":
        df.to_csv(path, index=False)
    else:
        raise ValueError(f"Unsupported format: {fmt}")

    logger.info("Dataset exported to %s (%d rows)", path, len(df))
    return path
