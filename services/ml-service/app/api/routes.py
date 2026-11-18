import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.auth import get_current_user
from app.config import settings
from app.db.models import AnalysisJob, PredictionResult, Repository
from app.db.session import get_db
from app.pipeline.orchestrator import STAGES, request_cancel, start_job
from app.explainers.explainer import (
    compute_shap_values,
    generate_explanation,
)
from app.models.ensemble import EnsemblePredictor

logger = logging.getLogger(__name__)
router = APIRouter()

MODELS_DIR = Path(__file__).parent.parent.parent / "trained_models_advanced"
_ensemble: EnsemblePredictor | None = None


def get_ensemble() -> EnsemblePredictor:
    global _ensemble
    if _ensemble is None:
        _ensemble = EnsemblePredictor(MODELS_DIR)
        _ensemble.load()
    return _ensemble


BASE_FEATURES = [
    "commits_count", "unique_authors", "churn", "file_age_days",
    "bug_fix_commits_count", "lines_added_total", "lines_deleted_total",
    "loc", "cyclomatic_complexity", "max_nesting_depth",
    "num_functions", "avg_function_length", "num_parameters_max",
]


def engineer_features(raw: dict) -> dict:
    commits = max(raw.get("commits_count", 1), 1)
    churn = max(raw.get("churn", 0), 1)
    loc = max(raw.get("loc", 1), 1)
    authors = max(raw.get("unique_authors", 1), 1)

    raw["churn_per_commit"] = churn / commits
    raw["complexity_per_loc"] = raw.get("cyclomatic_complexity", 0) / loc
    raw["deleted_ratio"] = raw.get("lines_deleted_total", 0) / churn
    raw["added_ratio"] = raw.get("lines_added_total", 0) / churn
    raw["functions_per_loc"] = raw.get("num_functions", 0) / loc
    raw["bugfix_ratio"] = raw.get("bug_fix_commits_count", 0) / commits
    raw["nesting_x_complexity"] = raw.get("max_nesting_depth", 0) * raw.get("cyclomatic_complexity", 0)
    raw["loc_x_age"] = np.log1p(raw.get("loc", 0)) * np.log1p(raw.get("file_age_days", 0))
    raw["authors_per_commit"] = authors / commits
    raw["avg_churn_per_author"] = churn / authors
    return raw


# ─── Request / Response schemas ────────────────────────────────────────

class PredictRequest(BaseModel):
    file_path: str
    commits_count: int = 0
    unique_authors: int = 0
    churn: int = 0
    file_age_days: float = 0.0
    bug_fix_commits_count: int = 0
    lines_added_total: int = 0
    lines_deleted_total: int = 0
    loc: int = 0
    cyclomatic_complexity: float = 0.0
    max_nesting_depth: int = 0
    num_functions: int = 0
    avg_function_length: float = 0.0
    num_parameters_max: int = 0


class ModelVote(BaseModel):
    model_name: str
    risk_score: float
    prediction: str
    f1_score: float


class Factor(BaseModel):
    feature: str
    label: str
    shap_value: float
    direction: str
    impact_share: float
    value: float | None
    value_display: str
    unit: str
    what: str
    interpretation: str
    baseline_comparison: str | None
    category: str
    is_above_threshold: bool
    level: str
    actionable: bool
    advice: list[str]


class PredictResponse(BaseModel):
    file_path: str
    risk_score: float
    risk_level: str
    is_buggy: bool
    votes_buggy: int
    votes_clean: int
    total_models: int
    per_model: list[ModelVote]
    top_features: dict[str, float]
    explanation: str
    explanation_detail: str = ""
    recommendations: list[str] = []
    factors: list[Factor] = []
    explanation_source: str = "generated"


class FileRisk(BaseModel):
    file_path: str
    risk_score: float
    risk_level: str
    is_buggy: bool
    votes_buggy: int
    total_models: int


class RepoAnalysisResponse(BaseModel):
    repo_id: int
    repo_name: str
    total_files: int
    high_risk: int
    medium_risk: int
    low_risk: int
    files: list[FileRisk]


class RepoInfo(BaseModel):
    id: int
    name: str
    url: str
    branch: str
    total_commits: int
    status: str


class RepoStatsResponse(BaseModel):
    repo_id: int
    repo_name: str
    total_files: int
    files_with_metrics: int
    total_commits: int
    buggy_files_szz: int
    avg_loc: float | None
    avg_complexity: float | None
    avg_churn: float | None


# ─── Submit repo ────────────────────────────────────────────────────────

class SubmitRepoRequest(BaseModel):
    repo_url: str
    branch: str = "main"


class SubmitRepoResponse(BaseModel):
    status: str
    repo_id: int | None = None
    message: str


@router.post("/submit-repo", response_model=SubmitRepoResponse)
async def submit_repo(req: SubmitRepoRequest, db: Session = Depends(get_db)):
    """
    Register a new GitHub repository for analysis.
    If already registered, returns the existing repo.
    NOTE: actual mining/analysis is a heavy background job —
    run `python run_mining.py <url>` on the server to process it.
    """
    existing = db.query(Repository).filter(Repository.url == req.repo_url).first()
    if existing:
        return SubmitRepoResponse(
            status="exists",
            repo_id=existing.id,
            message=f"Repository '{existing.name}' already registered (id={existing.id}). "
                    f"Status: {existing.status}.",
        )

    repo_name = req.repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    repo = Repository(
        url=req.repo_url,
        name=repo_name,
        branch=req.branch,
        status="pending",
        total_commits=0,
    )
    db.add(repo)
    db.commit()
    db.refresh(repo)
    logger.info("Registered new repo: %s (id=%d)", repo_name, repo.id)

    return SubmitRepoResponse(
        status="registered",
        repo_id=repo.id,
        message=f"Repository '{repo_name}' registered (id={repo.id}). "
                f"Run the mining pipeline on the server to populate data.",
    )


# ─── Full-cycle analysis jobs ──────────────────────────────────────────

class FullAnalysisRequest(BaseModel):
    repo_url: str
    branch: str = "main"
    # Large repositories take hours to mine in full; bounding the history keeps
    # a first run to a few minutes.
    since_days: int | None = Field(
        default=730,
        description="Only mine commits newer than this many days. null = full history.",
    )
    score_limit: int = Field(default=500, ge=1, le=5000)


class JobResponse(BaseModel):
    id: int
    repo_id: int | None
    repo_url: str
    branch: str
    submitted_by: str | None
    status: str
    stage: str | None
    stage_label: str | None
    stage_index: int
    total_stages: int
    progress: float
    message: str | None
    error: str | None
    commits_mined: int
    files_analyzed: int
    bug_labels: int
    files_scored: int
    created_at: str | None
    started_at: str | None
    finished_at: str | None


def _job_to_response(job: AnalysisJob) -> JobResponse:
    stage_label = next(
        (label for key, label in STAGES if key == job.stage), None
    )
    return JobResponse(
        id=job.id,
        repo_id=job.repo_id,
        repo_url=job.repo_url,
        branch=job.branch or "main",
        submitted_by=job.submitted_by,
        status=job.status or "queued",
        stage=job.stage,
        stage_label=stage_label,
        stage_index=job.stage_index or 0,
        total_stages=job.total_stages or len(STAGES),
        progress=float(job.progress or 0.0),
        message=job.message,
        error=job.error,
        commits_mined=job.commits_mined or 0,
        files_analyzed=job.files_analyzed or 0,
        bug_labels=job.bug_labels or 0,
        files_scored=job.files_scored or 0,
        created_at=job.created_at.isoformat() if job.created_at else None,
        started_at=job.started_at.isoformat() if job.started_at else None,
        finished_at=job.finished_at.isoformat() if job.finished_at else None,
    )


@router.post("/jobs/analyze-full", response_model=JobResponse)
async def start_full_analysis(
    req: FullAnalysisRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Run the complete pipeline for a repository: clone, mine history, static
    analysis, SZZ labelling and ensemble scoring. Returns immediately with a
    job to poll.
    """
    active = db.query(AnalysisJob).filter(
        AnalysisJob.repo_url == req.repo_url,
        AnalysisJob.status.in_(("queued", "running")),
    ).first()
    if active:
        raise HTTPException(
            status_code=409,
            detail=f"This repository is already being analyzed (job {active.id}).",
        )

    job = start_job(
        repo_url=req.repo_url,
        branch=req.branch,
        submitted_by=user.get("sub", "unknown"),
        since_days=req.since_days,
        score_limit=req.score_limit,
    )
    return _job_to_response(job)


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    jobs = db.query(AnalysisJob).order_by(AnalysisJob.id.desc()).limit(limit).all()
    return [_job_to_response(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job)


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Ask a running job to stop. It stops at the next stage boundary."""
    job = db.query(AnalysisJob).filter(AnalysisJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("queued", "running"):
        raise HTTPException(status_code=400, detail=f"Job is already {job.status}")

    request_cancel(job_id)
    job.message = "Cancellation requested — stopping after the current stage."
    db.commit()
    db.refresh(job)
    return _job_to_response(job)


@router.get("/pipeline-stages")
async def pipeline_stages():
    """The stage sequence, so the UI can render the pipeline before a job starts."""
    return {
        "stages": [
            {"key": key, "label": label, "index": i}
            for i, (key, label) in enumerate(STAGES)
        ]
    }


# ─── Endpoints ──────────────────────────────────────────────────────────

BASELINE_CACHE: dict[int, dict[str, float]] = {}


def get_repo_baselines(db: Session, repo_id: int) -> dict[str, float]:
    """
    Repository-wide averages, used to tell the developer whether a file's
    metric is unusual for its own project rather than in absolute terms.
    """
    if repo_id in BASELINE_CACHE:
        return BASELINE_CACHE[repo_id]

    row = db.execute(
        text("""
            SELECT AVG(loc), AVG(cyclomatic_complexity), AVG(max_nesting_depth),
                   AVG(num_functions), AVG(avg_function_length), AVG(num_parameters_max),
                   AVG(commits_count), AVG(unique_authors), AVG(churn),
                   AVG(file_age_days), AVG(bug_fix_commits_count),
                   AVG(lines_added_total), AVG(lines_deleted_total)
            FROM file_metrics
            WHERE repo_id = :repo_id AND loc IS NOT NULL
        """),
        {"repo_id": repo_id},
    ).fetchone()

    keys = [
        "loc", "cyclomatic_complexity", "max_nesting_depth", "num_functions",
        "avg_function_length", "num_parameters_max", "commits_count",
        "unique_authors", "churn", "file_age_days", "bug_fix_commits_count",
        "lines_added_total", "lines_deleted_total",
    ]
    baselines = {
        key: float(value)
        for key, value in zip(keys, row or [], strict=False)
        if value is not None
    }
    BASELINE_CACHE[repo_id] = baselines
    return baselines


async def run_prediction(
    request: PredictRequest,
    baselines: dict[str, float] | None = None,
    repo_name: str | None = None,
) -> PredictResponse:
    """Ensemble vote + SHAP + explanation for one file's metrics."""
    ensemble = get_ensemble()
    raw = request.model_dump()
    raw = engineer_features(raw)
    result = ensemble.predict(raw)

    best_model = ensemble.models[0]
    feature_names = best_model.features
    feature_values = [float(raw.get(f, 0)) for f in feature_names]
    X = np.array([feature_values])

    shap_features: dict[str, float] = {}
    try:
        shap_features = compute_shap_values(best_model.model, X, feature_names)
        top_features = {k: round(float(v), 4) for k, v in list(shap_features.items())[:5]}
    except Exception as e:
        logger.warning("SHAP failed: %s", e)
        top_features = {}

    explanation = await generate_explanation(
        file_path=request.file_path,
        risk_score=result.risk_score,
        shap_features=shap_features,
        values={name: float(raw.get(name, 0)) for name in feature_names},
        baselines=baselines,
        repo_name=repo_name,
        top_n=5,
    )

    return PredictResponse(
        file_path=request.file_path,
        risk_score=result.risk_score,
        risk_level=result.risk_level,
        is_buggy=result.is_buggy,
        votes_buggy=result.votes_buggy,
        votes_clean=result.votes_clean,
        total_models=result.total_models,
        per_model=[ModelVote(**m) for m in result.per_model],
        top_features=top_features,
        explanation=explanation.summary,
        explanation_detail=explanation.detail,
        recommendations=explanation.recommendations,
        factors=[Factor(**f) for f in explanation.factors],
        explanation_source=explanation.source,
    )


@router.post("/predict", response_model=PredictResponse)
async def predict_defect(request: PredictRequest):
    """
    Predict defect risk for a single file using the model ensemble.
    Majority voting determines the final label, average probability is the risk score.
    """
    return await run_prediction(request)


@router.get("/analyze/{repo_id}", response_model=RepoAnalysisResponse)
async def analyze_repo(
    repo_id: int,
    limit: int = Query(500, ge=1, le=5000),
    min_risk: float = Query(0.0, ge=0, le=1),
    sort_by: str = Query("risk", pattern="^(risk|path|loc)$"),
    db: Session = Depends(get_db),
):
    """
    Run ensemble prediction on all files in a repository.
    Returns files sorted by risk score (highest first by default).
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    rows = db.execute(
        text("""
            SELECT file_path, commits_count, unique_authors, churn, file_age_days,
                   bug_fix_commits_count, lines_added_total, lines_deleted_total,
                   loc, cyclomatic_complexity, max_nesting_depth,
                   num_functions, avg_function_length, num_parameters_max
            FROM file_metrics
            WHERE repo_id = :repo_id AND loc IS NOT NULL
        """),
        {"repo_id": repo_id},
    ).fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="No files with metrics found")

    ensemble = get_ensemble()
    results = []

    for row in rows:
        file_path = row[0]
        raw = dict(zip(BASE_FEATURES, row[1:]))
        raw = engineer_features(raw)

        pred = ensemble.predict(raw)

        if pred.risk_score < min_risk:
            continue

        results.append(FileRisk(
            file_path=file_path,
            risk_score=pred.risk_score,
            risk_level=pred.risk_level,
            is_buggy=pred.is_buggy,
            votes_buggy=pred.votes_buggy,
            total_models=pred.total_models,
        ))

    if sort_by == "risk":
        results.sort(key=lambda x: x.risk_score, reverse=True)
    elif sort_by == "path":
        results.sort(key=lambda x: x.file_path)

    high = sum(1 for r in results if r.risk_level == "high")
    medium = sum(1 for r in results if r.risk_level == "medium")
    low = sum(1 for r in results if r.risk_level == "low")

    return RepoAnalysisResponse(
        repo_id=repo_id,
        repo_name=repo.name,
        total_files=len(results),
        high_risk=high,
        medium_risk=medium,
        low_risk=low,
        files=results[:limit],
    )


@router.get("/analyze/{repo_id}/file")
async def analyze_single_file(
    repo_id: int,
    path: str = Query(..., description="File path to analyze"),
    db: Session = Depends(get_db),
):
    """
    Predict + explain a single file from the database.
    Returns ensemble vote, SHAP top features, and LLM explanation.
    """
    row = db.execute(
        text("""
            SELECT file_path, commits_count, unique_authors, churn, file_age_days,
                   bug_fix_commits_count, lines_added_total, lines_deleted_total,
                   loc, cyclomatic_complexity, max_nesting_depth,
                   num_functions, avg_function_length, num_parameters_max
            FROM file_metrics
            WHERE repo_id = :repo_id AND loc IS NOT NULL
              AND (file_path = :exact OR file_path LIKE :path)
            ORDER BY CASE WHEN file_path = :exact THEN 0 ELSE 1 END
            LIMIT 1
        """),
        {"repo_id": repo_id, "exact": path, "path": f"%{path}%"},
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="File not found in database")

    actual_path = row[0]
    raw = dict(zip(BASE_FEATURES, row[1:]))
    raw["file_path"] = actual_path
    request = PredictRequest(**raw)

    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    response = await run_prediction(
        request,
        baselines=get_repo_baselines(db, repo_id),
        repo_name=repo.name if repo else None,
    )

    votes_str = ", ".join(f"{m.model_name}={m.prediction}" for m in response.per_model)
    stored_explanation = "\n\n".join(
        part for part in (
            response.explanation,
            response.explanation_detail,
            "\n".join(f"- {r}" for r in response.recommendations),
        ) if part
    )
    existing = db.execute(
        text("SELECT id FROM prediction_results WHERE repo_id = :rid AND file_path = :fp"),
        {"rid": repo_id, "fp": actual_path},
    ).fetchone()
    if existing:
        db.execute(
            text("""
                UPDATE prediction_results
                SET risk_score = :score, risk_level = :level, top_features = :features,
                    explanation = :expl, model_name = :model, created_at = :now
                WHERE id = :id
            """),
            {
                "score": response.risk_score, "level": response.risk_level,
                "features": votes_str, "expl": stored_explanation,
                "model": f"ensemble({response.votes_buggy}/{response.total_models})",
                "now": datetime.utcnow(), "id": existing[0],
            },
        )
    else:
        db.add(PredictionResult(
            repo_id=repo_id,
            file_path=actual_path,
            risk_score=response.risk_score,
            risk_level=response.risk_level,
            top_features=votes_str,
            explanation=stored_explanation,
            model_name=f"ensemble({response.votes_buggy}/{response.total_models})",
        ))
    db.commit()
    return response


@router.post("/analyze/{repo_id}/save")
async def analyze_and_save(
    repo_id: int,
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """
    Run ensemble prediction on a repo and save results to prediction_results table.
    """
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    rows = db.execute(
        text("""
            SELECT file_path, commits_count, unique_authors, churn, file_age_days,
                   bug_fix_commits_count, lines_added_total, lines_deleted_total,
                   loc, cyclomatic_complexity, max_nesting_depth,
                   num_functions, avg_function_length, num_parameters_max
            FROM file_metrics
            WHERE repo_id = :repo_id AND loc IS NOT NULL
            LIMIT :limit
        """),
        {"repo_id": repo_id, "limit": limit},
    ).fetchall()

    ensemble = get_ensemble()
    saved = 0

    for row in rows:
        file_path = row[0]
        raw = dict(zip(BASE_FEATURES, row[1:]))
        raw = engineer_features(raw)
        pred = ensemble.predict(raw)

        votes_str = ", ".join(f"{m['model_name']}={m['prediction']}" for m in pred.per_model)

        existing = db.execute(
            text("SELECT id FROM prediction_results WHERE repo_id = :rid AND file_path = :fp"),
            {"rid": repo_id, "fp": file_path},
        ).fetchone()

        if existing:
            db.execute(
                text("""
                    UPDATE prediction_results
                    SET risk_score = :score, risk_level = :level,
                        top_features = :features, model_name = :model,
                        created_at = :now
                    WHERE id = :id
                """),
                {
                    "score": pred.risk_score, "level": pred.risk_level,
                    "features": votes_str,
                    "model": f"ensemble({pred.votes_buggy}/{pred.total_models})",
                    "now": datetime.utcnow(), "id": existing[0],
                },
            )
        else:
            result = PredictionResult(
                repo_id=repo_id,
                file_path=file_path,
                risk_score=pred.risk_score,
                risk_level=pred.risk_level,
                top_features=votes_str,
                explanation="",
                model_name=f"ensemble({pred.votes_buggy}/{pred.total_models})",
            )
            db.add(result)
        saved += 1

    db.commit()
    return {
        "status": "done",
        "repo": repo.name,
        "files_analyzed": saved,
    }


# ─── Repository & data endpoints ───────────────────────────────────────

@router.get("/repositories", response_model=list[RepoInfo])
async def list_repositories(db: Session = Depends(get_db)):
    repos = db.query(Repository).order_by(Repository.id).all()
    return [
        RepoInfo(
            id=r.id, name=r.name, url=r.url,
            branch=r.branch or "main",
            total_commits=r.total_commits or 0,
            status=r.status or "unknown",
        )
        for r in repos
    ]


@router.get("/repositories/{repo_id}/stats", response_model=RepoStatsResponse)
async def repo_stats(repo_id: int, db: Session = Depends(get_db)):
    repo = db.query(Repository).filter(Repository.id == repo_id).first()
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    stats = db.execute(
        text("""
            SELECT
                COUNT(*) AS total,
                COUNT(CASE WHEN loc IS NOT NULL THEN 1 END) AS with_metrics,
                ROUND(AVG(loc)::numeric, 1) AS avg_loc,
                ROUND(AVG(cyclomatic_complexity)::numeric, 2) AS avg_cc,
                ROUND(AVG(churn)::numeric, 1) AS avg_churn
            FROM file_metrics
            WHERE repo_id = :repo_id
        """),
        {"repo_id": repo_id},
    ).fetchone()

    buggy = db.execute(
        text("SELECT COUNT(DISTINCT file_path) FROM bug_labels WHERE repo_id = :repo_id AND is_buggy = true"),
        {"repo_id": repo_id},
    ).scalar()

    return RepoStatsResponse(
        repo_id=repo_id,
        repo_name=repo.name,
        total_files=stats[0] or 0,
        files_with_metrics=stats[1] or 0,
        total_commits=repo.total_commits or 0,
        buggy_files_szz=buggy or 0,
        avg_loc=float(stats[2]) if stats[2] else None,
        avg_complexity=float(stats[3]) if stats[3] else None,
        avg_churn=float(stats[4]) if stats[4] else None,
    )


@router.get("/repositories/{repo_id}/files")
async def list_files(
    repo_id: int,
    search: str = Query("", description="Filter by file path"),
    has_prediction: bool = Query(False, description="Only files with predictions"),
    risk_level: str | None = Query(None, pattern="^(high|medium|low)$"),
    sort_by: str = Query("risk", pattern="^(risk|path|loc)$"),
    limit: int = Query(50, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List files in a repository with their metrics."""
    where = "WHERE fm.repo_id = :repo_id AND fm.loc IS NOT NULL"
    params: dict = {"repo_id": repo_id}

    if search:
        where += " AND fm.file_path ILIKE :search"
        params["search"] = f"%{search}%"
    if has_prediction:
        where += " AND pr.id IS NOT NULL"
    if risk_level:
        where += " AND pr.risk_level = :risk_level"
        params["risk_level"] = risk_level

    order = {
        "risk": "pr.risk_score DESC NULLS LAST, fm.file_path",
        "loc": "fm.loc DESC NULLS LAST, fm.file_path",
        "path": "fm.file_path",
    }[sort_by]

    query = f"""
        SELECT fm.file_path, fm.loc, fm.cyclomatic_complexity, fm.max_nesting_depth,
               fm.commits_count, fm.unique_authors, fm.churn,
               pr.risk_score, pr.risk_level
        FROM file_metrics fm
        LEFT JOIN prediction_results pr ON pr.repo_id = fm.repo_id AND pr.file_path = fm.file_path
        {where}
        ORDER BY {order}
        LIMIT :limit OFFSET :offset
    """
    params["limit"] = limit
    params["offset"] = offset

    rows = db.execute(text(query), params).fetchall()

    total = db.execute(
        text(f"""
            SELECT COUNT(*)
            FROM file_metrics fm
            LEFT JOIN prediction_results pr ON pr.repo_id = fm.repo_id AND pr.file_path = fm.file_path
            {where}
        """),
        {k: v for k, v in params.items() if k not in ("limit", "offset")},
    ).scalar()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "files": [
            {
                "file_path": r[0],
                "loc": r[1],
                "cyclomatic_complexity": float(r[2]) if r[2] else None,
                "max_nesting_depth": r[3],
                "commits_count": r[4],
                "unique_authors": r[5],
                "churn": r[6],
                "risk_score": float(r[7]) if r[7] else None,
                "risk_level": r[8],
            }
            for r in rows
        ],
    }


@router.get("/predictions/{repo_id}")
async def list_predictions(
    repo_id: int,
    risk_level: str = Query(None, pattern="^(high|medium|low)$"),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List saved prediction results for a repository."""
    query = """
        SELECT file_path, risk_score, risk_level, model_name, top_features, created_at
        FROM prediction_results
        WHERE repo_id = :repo_id
    """
    params: dict = {"repo_id": repo_id}

    if risk_level:
        query += " AND risk_level = :level"
        params["level"] = risk_level

    query += " ORDER BY risk_score DESC LIMIT :limit"
    params["limit"] = limit

    rows = db.execute(text(query), params).fetchall()
    return {
        "repo_id": repo_id,
        "count": len(rows),
        "predictions": [
            {
                "file_path": r[0],
                "risk_score": float(r[1]),
                "risk_level": r[2],
                "model_name": r[3],
                "votes": r[4],
                "predicted_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ],
    }


# ─── Model / system info ───────────────────────────────────────────────

@router.get("/ensemble-info")
async def ensemble_info():
    """Return information about all models in the ensemble."""
    ensemble = get_ensemble()
    return ensemble.get_info()


@router.get("/dashboard-summary")
async def dashboard_summary(db: Session = Depends(get_db)):
    """High-level stats for the whole system."""
    repos = db.execute(text("SELECT COUNT(*) FROM repositories")).scalar()
    files = db.execute(text("SELECT COUNT(*) FROM file_metrics WHERE loc IS NOT NULL")).scalar()
    commits = db.execute(text("SELECT COUNT(*) FROM commit_records")).scalar()
    buggy = db.execute(text("SELECT COUNT(DISTINCT file_path) FROM bug_labels WHERE is_buggy = true")).scalar()
    predictions = db.execute(text("SELECT COUNT(*) FROM prediction_results")).scalar()

    high_risk = db.execute(
        text("SELECT COUNT(*) FROM prediction_results WHERE risk_level = 'high'")
    ).scalar()

    medium_risk = db.execute(
        text("SELECT COUNT(*) FROM prediction_results WHERE risk_level = 'medium'")
    ).scalar()

    low_risk = db.execute(
        text("SELECT COUNT(*) FROM prediction_results WHERE risk_level = 'low'")
    ).scalar()

    avg_risk = db.execute(
        text("SELECT ROUND(AVG(risk_score)::numeric, 4) FROM prediction_results")
    ).scalar()

    ensemble = get_ensemble()

    return {
        "repositories": repos or 0,
        "files_analyzed": files or 0,
        "total_commits": commits or 0,
        "buggy_files_szz": buggy or 0,
        "predictions_saved": predictions or 0,
        "high_risk_files": high_risk or 0,
        "medium_risk_files": medium_risk or 0,
        "low_risk_files": low_risk or 0,
        "avg_risk_score": float(avg_risk) if avg_risk else None,
        "ensemble_models": len(ensemble.models),
        "model_names": [m.name for m in ensemble.models],
    }
