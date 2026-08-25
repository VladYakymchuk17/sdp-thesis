"""
Run git mining on a TypeScript repository.

    python run_mining.py https://github.com/typestack/class-validator --branch master
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime

from app.config import settings
from app.db.models import Base
from app.db.session import SessionLocal, engine
from app.miners.git_miner import (
    MiningConfig,
    aggregate_file_metrics,
    clone_repository,
    get_mining_summary,
    mine_commits,
    register_repository,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_mining")


def main():
    parser = argparse.ArgumentParser(description="Mine git history from a TypeScript repository")
    parser.add_argument("repo_url", help="GitHub repository URL (e.g. https://github.com/typestack/class-validator)")
    parser.add_argument("--branch", default="master", help="Branch to analyze (default: master)")
    parser.add_argument("--skip-clone", action="store_true", help="Skip cloning (repo must already exist)")
    parser.add_argument("--skip-aggregate", action="store_true", help="Skip metric aggregation")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("SDP Git Mining Pipeline")
    logger.info("=" * 60)
    logger.info("Repository: %s", args.repo_url)
    logger.info("Branch: %s", args.branch)
    logger.info("Clone dir: %s", settings.repos_clone_dir)

    # 1. Create tables
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)

    # 2. Clone repository
    if not args.skip_clone:
        logger.info("Step 1/4: Cloning repository...")
        t0 = time.time()
        clone_path = clone_repository(args.repo_url, settings.repos_clone_dir)
        logger.info("Clone done in %.1fs — %s", time.time() - t0, clone_path)
    else:
        repo_name = args.repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        org_name = args.repo_url.rstrip("/").split("/")[-2]
        clone_path = f"{settings.repos_clone_dir}/{org_name}__{repo_name}"
        logger.info("Step 1/4: Skipping clone, using %s", clone_path)

    # 3. Register in DB & mine commits
    db = SessionLocal()
    try:
        logger.info("Step 2/4: Registering repository...")
        repo = register_repository(db, args.repo_url, str(clone_path), args.branch)

        logger.info("Step 3/4: Mining commits (this may take a few minutes)...")
        t0 = time.time()
        config = MiningConfig(
            repo_url=args.repo_url,
            clone_dir=settings.repos_clone_dir,
            branch=args.branch,
        )
        commit_count = mine_commits(config, db, repo.id)
        elapsed = time.time() - t0
        logger.info("Mining done in %.1fs — %d commits processed", elapsed, commit_count)

        # Update repo status
        repo.total_commits = commit_count
        repo.status = "mined"
        db.commit()

        # 4. Aggregate metrics
        if not args.skip_aggregate:
            logger.info("Step 4/4: Aggregating file metrics...")
            t0 = time.time()
            cutoff = datetime.utcnow()
            file_count = aggregate_file_metrics(db, repo.id, cutoff)
            logger.info("Aggregation done in %.1fs — %d files", time.time() - t0, file_count)
        else:
            logger.info("Step 4/4: Skipping aggregation")

        # Summary
        summary = get_mining_summary(db, repo.id)
        logger.info("=" * 60)
        logger.info("MINING SUMMARY")
        logger.info("=" * 60)
        logger.info(json.dumps(summary, indent=2, default=str))
        logger.info("=" * 60)

    except Exception:
        logger.exception("Mining pipeline failed")
        if db:
            repo_obj = db.query(type(repo)).get(repo.id) if 'repo' in dir() else None
            if repo_obj:
                repo_obj.status = "error"
                db.commit()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
