"""
Full-cycle analysis for a newly submitted repository.

Runs the same five stages as the standalone CLI scripts — clone, mine, static
analysis, SZZ labelling, ensemble scoring — but inside a worker thread that
reports progress into the analysis_jobs table so the dashboard can follow along.

The stages are deliberately the same code paths as the CLI scripts; this module
only adds orchestration, progress reporting and cancellation.
"""

import json
import logging
import subprocess
import threading
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AnalysisJob, Repository
from app.db.session import SessionLocal
from app.labelers.szz import run_szz_for_repo
from app.miners.git_miner import (
    MiningConfig,
    aggregate_file_metrics,
    clone_repository,
    mine_commits,
    register_repository,
)

logger = logging.getLogger(__name__)

# app/pipeline/orchestrator.py -> app -> ml-service -> services
TS_ANALYZER_CLI = str(
    Path(__file__).resolve().parents[3] / "ts-analyzer" / "dist" / "cli.js"
)

STAGES = [
    ("clone", "Cloning repository"),
    ("mine", "Mining commit history"),
    ("static", "Running TypeScript static analysis"),
    ("szz", "Labelling bug-introducing commits (SZZ)"),
    ("score", "Scoring files with the model ensemble"),
]

# Job ids that have been asked to stop. Checked between stages.
_cancelled: set[int] = set()
_lock = threading.Lock()


def request_cancel(job_id: int) -> None:
    with _lock:
        _cancelled.add(job_id)


def reap_orphaned_jobs() -> int:
    """
    Fail any job still marked running from a previous process.

    Workers are daemon threads, so a restart (including an autoreload) kills
    them without a chance to update their row. Without this, such a job would
    sit at "running" in the dashboard forever.
    """
    db = SessionLocal()
    try:
        stale = db.query(AnalysisJob).filter(
            AnalysisJob.status.in_(("queued", "running"))
        ).all()
        for job in stale:
            job.status = "failed"
            job.error = "Service restarted while this job was running."
            job.message = (
                f"Interrupted during '{job.stage}' by a service restart. "
                f"Start the analysis again to resume — completed stages are cached."
            )
            job.finished_at = datetime.utcnow()
        if stale:
            db.commit()
            logger.warning("Marked %d orphaned job(s) as failed", len(stale))
        return len(stale)
    finally:
        db.close()


def _is_cancelled(job_id: int) -> bool:
    with _lock:
        return job_id in _cancelled


class Cancelled(Exception):
    pass


def _update(
    db: Session,
    job: AnalysisJob,
    *,
    stage_index: int | None = None,
    message: str | None = None,
    **fields,
) -> None:
    if stage_index is not None:
        job.stage_index = stage_index
        job.stage = STAGES[stage_index][0]
        # Progress is reported at stage granularity; a stage that has started
        # counts as half-complete so the bar always moves on entry.
        job.progress = round((stage_index + 0.5) / len(STAGES), 3)
    if message is not None:
        job.message = message
        logger.info("[job %d] %s", job.id, message)
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()


def _checkpoint(job_id: int) -> None:
    if _is_cancelled(job_id):
        raise Cancelled()


def _run_static_analysis(db: Session, repo_id: int, repo_path: str) -> int:
    """Invoke the ts-analyzer CLI and merge its metrics into file_metrics."""
    if not Path(TS_ANALYZER_CLI).exists():
        raise RuntimeError(
            f"ts-analyzer is not built at {TS_ANALYZER_CLI}. "
            "Run `npm install && npm run build` in services/ts-analyzer."
        )

    result = subprocess.run(
        ["node", TS_ANALYZER_CLI, repo_path, "--batch", "--json"],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ts-analyzer failed: {result.stderr[:400]}")

    try:
        metrics = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"could not parse ts-analyzer output: {e}") from e

    repo_root = str(Path(repo_path).resolve()).replace("\\", "/")
    updated = 0

    for m in metrics:
        abs_path = m["file_path"].replace("\\", "/")
        relative = (
            abs_path[len(repo_root):].lstrip("/")
            if abs_path.startswith(repo_root)
            else abs_path
        )

        res = db.execute(
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
                "fp": relative,
                "fp_back": relative.replace("/", "\\"),
            },
        )
        updated += res.rowcount or 0

    db.commit()
    return updated


def _score_repo(db: Session, repo_id: int, limit: int) -> int:
    """Save ensemble predictions for the repo's files."""
    # Imported here to avoid a circular import with the API module.
    from app.api.routes import BASELINE_CACHE, engineer_features, get_ensemble
    from app.db.models import PredictionResult

    rows = db.execute(
        text("""
            SELECT file_path, commits_count, unique_authors, churn, file_age_days,
                   bug_fix_commits_count, lines_added_total, lines_deleted_total,
                   loc, cyclomatic_complexity, max_nesting_depth,
                   num_functions, avg_function_length, num_parameters_max
            FROM file_metrics
            WHERE repo_id = :repo_id AND loc IS NOT NULL
            ORDER BY churn DESC NULLS LAST
            LIMIT :limit
        """),
        {"repo_id": repo_id, "limit": limit},
    ).fetchall()

    base_features = [
        "commits_count", "unique_authors", "churn", "file_age_days",
        "bug_fix_commits_count", "lines_added_total", "lines_deleted_total",
        "loc", "cyclomatic_complexity", "max_nesting_depth",
        "num_functions", "avg_function_length", "num_parameters_max",
    ]

    ensemble = get_ensemble()
    saved = 0

    for row in rows:
        file_path = row[0]
        raw = engineer_features(dict(zip(base_features, row[1:], strict=False)))
        pred = ensemble.predict(raw)
        votes = ", ".join(f"{m['model_name']}={m['prediction']}" for m in pred.per_model)

        existing = db.execute(
            text("SELECT id FROM prediction_results WHERE repo_id = :rid AND file_path = :fp"),
            {"rid": repo_id, "fp": file_path},
        ).fetchone()

        if existing:
            db.execute(
                text("""
                    UPDATE prediction_results
                    SET risk_score = :score, risk_level = :level,
                        top_features = :features, model_name = :model, created_at = :now
                    WHERE id = :id
                """),
                {
                    "score": pred.risk_score, "level": pred.risk_level,
                    "features": votes,
                    "model": f"ensemble({pred.votes_buggy}/{pred.total_models})",
                    "now": datetime.utcnow(), "id": existing[0],
                },
            )
        else:
            db.add(PredictionResult(
                repo_id=repo_id,
                file_path=file_path,
                risk_score=pred.risk_score,
                risk_level=pred.risk_level,
                top_features=votes,
                explanation="",
                model_name=f"ensemble({pred.votes_buggy}/{pred.total_models})",
            ))
        saved += 1

    db.commit()
    # Metric averages changed, so the cached per-repo baselines are stale.
    BASELINE_CACHE.pop(repo_id, None)
    return saved


def run_full_cycle(
    job_id: int,
    repo_url: str,
    branch: str,
    since_days: int | None = None,
    score_limit: int = 500,
) -> None:
    """Execute every stage for one job. Intended to run in a worker thread."""
    db = SessionLocal()
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        db.close()
        logger.error("job %d disappeared before it started", job_id)
        return

    repo = None
    try:
        _update(
            db, job,
            status="running", started_at=datetime.utcnow(),
            stage_index=0, message=f"Cloning {repo_url} ...",
        )
        _checkpoint(job_id)

        clone_path = clone_repository(repo_url, settings.repos_clone_dir)
        repo = register_repository(db, repo_url, str(clone_path), branch)
        job.repo_id = repo.id
        db.commit()

        # ─── Mine commits ──────────────────────────────────────────────
        _update(
            db, job, stage_index=1,
            message="Walking commit history with PyDriller. This is the slowest stage.",
        )
        _checkpoint(job_id)

        config = MiningConfig(
            repo_url=repo_url,
            clone_dir=settings.repos_clone_dir,
            branch=branch,
            since=datetime.utcnow() - timedelta(days=since_days) if since_days else None,
        )
        mine_commits(config, db, repo.id)
        # mine_commits returns a file-record count when it skips already-mined
        # repos, so read the real number of distinct commits back from the DB.
        commits = db.execute(
            text("SELECT COUNT(DISTINCT commit_hash) FROM commit_records WHERE repo_id = :rid"),
            {"rid": repo.id},
        ).scalar() or 0
        repo.total_commits = commits
        repo.status = "mined"
        db.commit()
        _update(
            db, job, commits_mined=commits,
            message=f"Mined {commits:,} commits. Aggregating per-file metrics ...",
        )

        # Aggregation is keyed on snapshot date, so a re-run would otherwise add a
        # second row per file. Everything downstream expects one row per file.
        db.execute(
            text("DELETE FROM file_metrics WHERE repo_id = :repo_id"),
            {"repo_id": repo.id},
        )
        db.commit()

        files = aggregate_file_metrics(db, repo.id, datetime.utcnow())
        _update(db, job, files_analyzed=files, message=f"Aggregated metrics for {files:,} files.")
        _checkpoint(job_id)

        # ─── Static analysis ───────────────────────────────────────────
        _update(db, job, stage_index=2, message="Extracting complexity metrics from TypeScript sources ...")
        static_updated = _run_static_analysis(db, repo.id, str(clone_path))
        _update(db, job, message=f"Static metrics written for {static_updated:,} files.")
        _checkpoint(job_id)

        # ─── SZZ ───────────────────────────────────────────────────────
        _update(db, job, stage_index=3, message="Tracing bug-fixing commits back to their origin (SZZ) ...")
        szz_result = run_szz_for_repo(db, repo.id, str(clone_path)) or {}
        label_count = szz_result.get(
            "bug_introductions", szz_result.get("existing_labels", 0)
        )
        _update(db, job, bug_labels=label_count, message=f"SZZ produced {label_count:,} bug labels.")
        _checkpoint(job_id)

        # ─── Score ─────────────────────────────────────────────────────
        _update(db, job, stage_index=4, message="Scoring files with the model ensemble ...")
        scored = _score_repo(db, repo.id, score_limit)

        repo.status = "analyzed"
        job.status = "done"
        job.progress = 1.0
        job.finished_at = datetime.utcnow()
        job.files_scored = scored
        job.message = (
            f"Complete. {commits:,} commits mined, {files:,} files measured, "
            f"{scored:,} files scored."
        )
        db.commit()
        logger.info("[job %d] finished", job_id)

    except Cancelled:
        job.status = "cancelled"
        job.message = "Cancelled before completion."
        job.finished_at = datetime.utcnow()
        if repo:
            repo.status = "partial"
        db.commit()
        logger.info("[job %d] cancelled", job_id)

    except Exception as e:
        logger.exception("[job %d] failed", job_id)
        job.status = "failed"
        job.error = str(e)[:2000]
        job.message = f"Failed during '{job.stage}': {e}"
        job.finished_at = datetime.utcnow()
        if repo:
            repo.status = "error"
        db.commit()

    finally:
        with _lock:
            _cancelled.discard(job_id)
        db.close()


def start_job(
    repo_url: str,
    branch: str,
    submitted_by: str,
    since_days: int | None = None,
    score_limit: int = 500,
) -> AnalysisJob:
    """Create the job row and hand it to a worker thread."""
    db = SessionLocal()
    try:
        job = AnalysisJob(
            repo_url=repo_url,
            branch=branch,
            submitted_by=submitted_by,
            status="queued",
            stage=STAGES[0][0],
            total_stages=len(STAGES),
            message="Queued.",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id
    finally:
        db.close()

    thread = threading.Thread(
        target=run_full_cycle,
        args=(job_id, repo_url, branch, since_days, score_limit),
        name=f"sdp-job-{job_id}",
        daemon=True,
    )
    thread.start()

    db = SessionLocal()
    try:
        return db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    finally:
        db.close()
