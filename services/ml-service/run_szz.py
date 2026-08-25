"""
SZZ bug labeling pipeline.

    python run_szz.py
    python run_szz.py --repo-id 1
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from app.config import settings
from app.db.models import Base, BugLabel
from app.db.models import Repository as RepoModel
from app.db.session import SessionLocal, engine
from app.labelers.szz import run_szz_for_repo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_szz")


def resolve_repo_path(repo: RepoModel) -> str:
    clone_dir = Path(settings.repos_clone_dir)
    org_name = repo.url.rstrip("/").split("/")[-2]
    repo_name = repo.url.rstrip("/").split("/")[-1].replace(".git", "")
    return str(clone_dir / f"{org_name}__{repo_name}")


def main():
    parser = argparse.ArgumentParser(description="Run SZZ bug labeling")
    parser.add_argument("--repo-id", type=int, help="Process only this repo ID")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        if args.repo_id:
            repos = [db.query(RepoModel).filter(RepoModel.id == args.repo_id).first()]
            if not repos[0]:
                logger.error("Repo id=%d not found", args.repo_id)
                sys.exit(1)
        else:
            repos = db.query(RepoModel).filter(RepoModel.status == "mined").all()

        logger.info("=" * 60)
        logger.info("SZZ Bug Labeling Pipeline")
        logger.info("=" * 60)
        logger.info("Repos to process: %d", len(repos))

        all_results = {}

        for repo in repos:
            repo_path = resolve_repo_path(repo)
            if not Path(repo_path).exists():
                logger.error("Clone not found: %s", repo_path)
                continue

            logger.info("-" * 40)
            logger.info("Processing: %s (id=%d)", repo.name, repo.id)
            t0 = time.time()

            result = run_szz_for_repo(db, repo.id, repo_path)
            elapsed = time.time() - t0

            all_results[repo.name] = result
            logger.info("Done in %.1fs", elapsed)

        # Summary
        logger.info("=" * 60)
        logger.info("SZZ SUMMARY")
        logger.info("=" * 60)

        total_labels = db.query(BugLabel).count()
        logger.info("Total bug labels in DB: %d", total_labels)
        logger.info(json.dumps(all_results, indent=2, default=str))

    finally:
        db.close()


if __name__ == "__main__":
    main()
