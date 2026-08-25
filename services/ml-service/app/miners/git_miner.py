"""
Git mining module — uses PyDriller to extract per-file commit history metrics.
"""

import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydriller import Repository as PyDrillerRepo
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.db.models import CommitRecord, FileMetric
from app.db.models import Repository as RepoModel

logger = logging.getLogger(__name__)

BUG_KEYWORDS = {"fix", "bug", "defect", "patch", "hotfix", "resolve", "closes", "fixes"}

TS_JS_EXTENSIONS = {".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"}


@dataclass
class MiningConfig:
    repo_url: str
    clone_dir: str
    branch: str = "main"
    since: datetime | None = None
    to: datetime | None = None


def is_bug_fix_commit(message: str) -> bool:
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in BUG_KEYWORDS)


def is_ts_js_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in TS_JS_EXTENSIONS


def clone_repository(repo_url: str, clone_dir: str) -> Path:
    """Clone repo with full history (all branches). Returns clone path."""
    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    org_name = repo_url.rstrip("/").split("/")[-2]
    clone_path = Path(clone_dir) / f"{org_name}__{repo_name}"

    if clone_path.exists():
        logger.info("Repository already cloned at %s, pulling latest...", clone_path)
        subprocess.run(
            ["git", "pull", "--all"],
            cwd=clone_path,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return clone_path

    clone_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s into %s ...", repo_url, clone_path)

    result = subprocess.run(
        ["git", "clone", "--no-single-branch", repo_url, str(clone_path)],
        capture_output=True,
        text=True,
        timeout=600,
    )

    if result.returncode != 0:
        raise RuntimeError(f"git clone failed: {result.stderr}")

    logger.info("Clone complete: %s", clone_path)
    return clone_path


def register_repository(db: Session, repo_url: str, clone_path: str, branch: str) -> RepoModel:
    existing = db.query(RepoModel).filter(RepoModel.url == repo_url).first()
    if existing:
        logger.info("Repository already registered: id=%d, %s", existing.id, existing.name)
        return existing

    repo_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    repo = RepoModel(
        url=repo_url,
        name=repo_name,
        clone_path=clone_path,
        branch=branch,
        status="pending",
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    logger.info("Registered repository: id=%d, %s", repo.id, repo.name)
    return repo


def mine_commits(config: MiningConfig, db: Session, repo_id: int) -> int:
    """Traverse commits and store per-file records. Only TS/JS files."""
    existing_count = db.query(CommitRecord).filter(CommitRecord.repo_id == repo_id).count()
    if existing_count > 0:
        logger.info("Repository already has %d commit records. Skipping mining.", existing_count)
        return existing_count

    repo_name = config.repo_url.rstrip("/").split("/")[-1]
    clone_path = Path(config.clone_dir) / f"{config.repo_url.rstrip('/').split('/')[-2]}__{repo_name.replace('.git', '')}"

    repo = PyDrillerRepo(
        str(clone_path),
        only_in_branch=config.branch,
        since=config.since,
        to=config.to,
    )

    commit_count = 0
    file_record_count = 0

    for commit in repo.traverse_commits():
        for modified_file in commit.modified_files:
            if modified_file.filename is None:
                continue

            file_path = modified_file.new_path or modified_file.old_path
            if file_path is None:
                continue

            if not is_ts_js_file(file_path):
                continue

            record = CommitRecord(
                repo_id=repo_id,
                commit_hash=commit.hash,
                file_path=file_path,
                author=commit.author.name,
                author_email=commit.author.email,
                date=commit.author_date,
                added_lines=modified_file.added_lines,
                deleted_lines=modified_file.deleted_lines,
                message=commit.msg[:2000],  # truncate very long messages
                is_bug_fix=is_bug_fix_commit(commit.msg),
            )
            db.add(record)
            file_record_count += 1

        commit_count += 1
        if commit_count % 200 == 0:
            db.commit()
            logger.info(
                "Processed %d commits (%d file records so far)",
                commit_count, file_record_count,
            )

    db.commit()
    logger.info(
        "Mining complete. Commits: %d, File records: %d",
        commit_count, file_record_count,
    )
    return commit_count


def aggregate_file_metrics(db: Session, repo_id: int, cutoff_date: datetime) -> int:
    """Aggregate per-file git metrics up to cutoff_date into file_metrics table."""
    existing = (
        db.query(FileMetric)
        .filter(FileMetric.repo_id == repo_id, FileMetric.snapshot_date == cutoff_date)
        .count()
    )
    if existing > 0:
        logger.info("Metrics already exist for repo_id=%d at %s (%d files)", repo_id, cutoff_date, existing)
        return existing

    query = text("""
        INSERT INTO file_metrics (
            repo_id, file_path, snapshot_date,
            commits_count, unique_authors, churn,
            file_age_days, bug_fix_commits_count,
            lines_added_total, lines_deleted_total
        )
        SELECT
            :repo_id,
            file_path,
            :cutoff_date,
            COUNT(DISTINCT commit_hash) AS commits_count,
            COUNT(DISTINCT author_email) AS unique_authors,
            COALESCE(SUM(added_lines + deleted_lines), 0) AS churn,
            EXTRACT(EPOCH FROM (:cutoff_date - MIN(date))) / 86400.0 AS file_age_days,
            COUNT(DISTINCT CASE WHEN is_bug_fix THEN commit_hash END) AS bug_fix_commits_count,
            COALESCE(SUM(added_lines), 0) AS lines_added_total,
            COALESCE(SUM(deleted_lines), 0) AS lines_deleted_total
        FROM commit_records
        WHERE repo_id = :repo_id
          AND date <= :cutoff_date
        GROUP BY file_path
        HAVING COUNT(DISTINCT commit_hash) >= 1
    """)

    result = db.execute(query, {"repo_id": repo_id, "cutoff_date": cutoff_date})
    db.commit()

    count = db.query(FileMetric).filter(
        FileMetric.repo_id == repo_id,
        FileMetric.snapshot_date == cutoff_date,
    ).count()

    logger.info("Aggregated metrics for %d files (repo_id=%d, cutoff=%s)", count, repo_id, cutoff_date)
    return count


def get_mining_summary(db: Session, repo_id: int) -> dict:
    total_records = db.query(CommitRecord).filter(CommitRecord.repo_id == repo_id).count()
    unique_commits = db.query(func.count(func.distinct(CommitRecord.commit_hash))).filter(
        CommitRecord.repo_id == repo_id
    ).scalar()
    unique_files = db.query(func.count(func.distinct(CommitRecord.file_path))).filter(
        CommitRecord.repo_id == repo_id
    ).scalar()
    unique_authors = db.query(func.count(func.distinct(CommitRecord.author_email))).filter(
        CommitRecord.repo_id == repo_id
    ).scalar()
    bug_fix_records = db.query(CommitRecord).filter(
        CommitRecord.repo_id == repo_id, CommitRecord.is_bug_fix.is_(True)
    ).count()

    date_range = db.query(
        func.min(CommitRecord.date), func.max(CommitRecord.date)
    ).filter(CommitRecord.repo_id == repo_id).first()

    return {
        "total_file_records": total_records,
        "unique_commits": unique_commits,
        "unique_files": unique_files,
        "unique_authors": unique_authors,
        "bug_fix_records": bug_fix_records,
        "date_from": str(date_range[0]) if date_range[0] else None,
        "date_to": str(date_range[1]) if date_range[1] else None,
    }
