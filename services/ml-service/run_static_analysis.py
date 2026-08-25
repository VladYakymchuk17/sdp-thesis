"""
Run ts-analyzer on cloned repos and update file_metrics with static metrics.

    python run_static_analysis.py
    python run_static_analysis.py --repo-id 1
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.db.models import Base, FileMetric
from app.db.models import Repository as RepoModel
from app.db.session import SessionLocal, engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_static_analysis")

TS_ANALYZER_CLI = str(
    Path(__file__).parent.parent / "ts-analyzer" / "dist" / "cli.js"
)


def analyze_repo_directory(repo_path: str) -> list[dict]:
    """Call ts-analyzer CLI on a directory, return list of file metrics."""
    logger.info("Running ts-analyzer on %s ...", repo_path)

    result = subprocess.run(
        ["node", TS_ANALYZER_CLI, repo_path, "--batch", "--json"],
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        logger.error("ts-analyzer failed: %s", result.stderr[:500])
        return []

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        logger.error("Failed to parse ts-analyzer output: %s", e)
        return []


def update_file_metrics(db, repo_id: int, metrics_list: list[dict], repo_path: str) -> int:
    """Update file_metrics rows with static code metrics."""
    updated = 0
    repo_path_normalized = str(Path(repo_path).resolve()).replace("\\", "/")

    for m in metrics_list:
        abs_path = m["file_path"].replace("\\", "/")
        if abs_path.startswith(repo_path_normalized):
            relative_path = abs_path[len(repo_path_normalized):].lstrip("/")
        else:
            relative_path = abs_path

        relative_path_backslash = relative_path.replace("/", "\\")

        result = db.execute(
            text("""
                UPDATE file_metrics SET
                    loc = :loc,
                    cyclomatic_complexity = :cc,
                    max_nesting_depth = :nesting,
                    num_functions = :num_fns,
                    avg_function_length = :avg_fn_len,
                    num_parameters_max = :max_params
                WHERE repo_id = :repo_id
                  AND (file_path = :fp OR file_path = :fp_back)
            """),
            {
                "loc": m["sloc"],
                "cc": m["cyclomatic_complexity"],
                "nesting": m["max_nesting_depth"],
                "num_fns": m["num_functions"],
                "avg_fn_len": m["avg_function_length"],
                "max_params": m["num_parameters_max"],
                "repo_id": repo_id,
                "fp": relative_path,
                "fp_back": relative_path_backslash,
            },
        )
        if result.rowcount > 0:
            updated += result.rowcount

    db.commit()
    return updated


def process_repo(repo: RepoModel, db) -> None:
    """Process a single repository."""
    logger.info("Processing repo: %s (id=%d)", repo.name, repo.id)

    if not repo.clone_path or not Path(repo.clone_path).exists():
        clone_dir = Path(settings.repos_clone_dir)
        org_name = repo.url.rstrip("/").split("/")[-2]
        repo_name = repo.url.rstrip("/").split("/")[-1].replace(".git", "")
        repo_path = str(clone_dir / f"{org_name}__{repo_name}")
    else:
        repo_path = repo.clone_path

    if not Path(repo_path).exists():
        logger.error("Clone path does not exist: %s", repo_path)
        return

    t0 = time.time()
    metrics = analyze_repo_directory(repo_path)
    logger.info("ts-analyzer returned %d files in %.1fs", len(metrics), time.time() - t0)

    if not metrics:
        logger.warning("No metrics returned for %s", repo.name)
        return

    t0 = time.time()
    updated = update_file_metrics(db, repo.id, metrics, repo_path)
    logger.info("Updated %d file_metrics rows in %.1fs", updated, time.time() - t0)


def main():
    parser = argparse.ArgumentParser(description="Run static analysis on cloned repos")
    parser.add_argument("--repo-id", type=int, help="Process only this repo ID")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if args.repo_id:
            repo = db.query(RepoModel).filter(RepoModel.id == args.repo_id).first()
            if not repo:
                logger.error("Repo id=%d not found", args.repo_id)
                sys.exit(1)
            process_repo(repo, db)
        else:
            repos = db.query(RepoModel).filter(RepoModel.status == "mined").all()
            logger.info("Found %d repos to analyze", len(repos))
            for repo in repos:
                process_repo(repo, db)

        has_static = db.execute(text(
            "SELECT COUNT(*) FROM file_metrics WHERE loc IS NOT NULL"
        )).scalar()
        total = db.execute(text("SELECT COUNT(*) FROM file_metrics")).scalar()
        logger.info("Static metrics coverage: %d / %d files (%.1f%%)", has_static, total, 100 * has_static / max(total, 1))

    finally:
        db.close()


if __name__ == "__main__":
    main()
