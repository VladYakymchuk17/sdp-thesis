from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String(500), nullable=False, unique=True)
    name = Column(String(200), nullable=False)
    clone_path = Column(String(500))
    branch = Column(String(100), default="main")
    total_commits = Column(Integer, default=0)
    status = Column(String(50), default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CommitRecord(Base):
    __tablename__ = "commit_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, nullable=True)
    commit_hash = Column(String(40), nullable=False)
    file_path = Column(String(500), nullable=False)
    author = Column(String(200))
    author_email = Column(String(200))
    date = Column(DateTime, nullable=False)
    added_lines = Column(Integer, default=0)
    deleted_lines = Column(Integer, default=0)
    message = Column(Text)
    is_bug_fix = Column(Boolean, default=False)


class FileMetric(Base):
    __tablename__ = "file_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, nullable=False)
    file_path = Column(String(500), nullable=False)
    snapshot_date = Column(DateTime, nullable=False)

    commits_count = Column(Integer, default=0)
    unique_authors = Column(Integer, default=0)
    churn = Column(Integer, default=0)
    file_age_days = Column(Float, default=0.0)
    bug_fix_commits_count = Column(Integer, default=0)
    lines_added_total = Column(Integer, default=0)
    lines_deleted_total = Column(Integer, default=0)
    loc = Column(Integer)
    cyclomatic_complexity = Column(Float)
    max_nesting_depth = Column(Integer)
    num_functions = Column(Integer)
    avg_function_length = Column(Float)
    num_parameters_max = Column(Integer)


class BugLabel(Base):
    __tablename__ = "bug_labels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, nullable=False)
    file_path = Column(String(500), nullable=False)
    snapshot_date = Column(DateTime, nullable=True)
    is_buggy = Column(Boolean, default=False)
    fix_commit_hash = Column(String(40))
    bug_introducing_commit_hash = Column(String(40))


class PredictionResult(Base):
    __tablename__ = "prediction_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, nullable=False)
    file_path = Column(String(500), nullable=False)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String(20))
    top_features = Column(Text)
    explanation = Column(Text)
    model_name = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)


class AnalysisJob(Base):
    """One full-cycle run: clone, mine, static analysis, SZZ, scoring."""

    __tablename__ = "analysis_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(Integer, nullable=True)
    repo_url = Column(String(500), nullable=False)
    branch = Column(String(100), default="main")
    submitted_by = Column(String(200))

    status = Column(String(20), default="queued")   # queued|running|done|failed|cancelled
    stage = Column(String(50))                      # current stage key
    stage_index = Column(Integer, default=0)
    total_stages = Column(Integer, default=5)
    progress = Column(Float, default=0.0)           # 0..1 across the whole run
    message = Column(Text)
    error = Column(Text)

    commits_mined = Column(Integer, default=0)
    files_analyzed = Column(Integer, default=0)
    bug_labels = Column(Integer, default=0)
    files_scored = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
