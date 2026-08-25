"""
SZZ algorithm — identifies bug-introducing commits by tracing
fix commits back through git blame.
"""

import logging
import re
import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.models import BugLabel

logger = logging.getLogger(__name__)


def get_fix_commits(db: Session, repo_id: int) -> list[dict]:
    rows = db.execute(
        text("""
            SELECT DISTINCT commit_hash, message
            FROM commit_records
            WHERE repo_id = :repo_id AND is_bug_fix = true
            ORDER BY commit_hash
        """),
        {"repo_id": repo_id},
    ).fetchall()
    return [{"hash": r[0], "message": r[1]} for r in rows]


def get_fix_commit_files(db: Session, repo_id: int, commit_hash: str) -> list[str]:
    rows = db.execute(
        text("""
            SELECT DISTINCT file_path
            FROM commit_records
            WHERE repo_id = :repo_id AND commit_hash = :hash
        """),
        {"repo_id": repo_id, "hash": commit_hash},
    ).fetchall()
    return [r[0] for r in rows]


def parse_deleted_lines_from_diff(diff_output: str) -> list[int]:
    """Parse unified diff output, return line numbers of deleted lines in old file."""
    deleted_lines = []
    current_old_line = 0

    for line in diff_output.split("\n"):
        hunk_match = re.match(r'^@@ -(\d+)', line)
        if hunk_match:
            current_old_line = int(hunk_match.group(1))
            continue

        if current_old_line == 0:
            continue

        if line.startswith("-") and not line.startswith("---"):
            stripped = line[1:].strip()
            # skip empty/comment-only lines
            if stripped and not stripped.startswith("//") and not stripped.startswith("*"):
                deleted_lines.append(current_old_line)
            current_old_line += 1
        elif line.startswith("+") and not line.startswith("+++"):
            pass
        elif not line.startswith("\\"):
            current_old_line += 1

    return deleted_lines


def get_diff_deleted_lines(repo_path: str, commit_hash: str, file_path: str) -> list[int]:
    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}^", commit_hash, "--", file_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            return []
        return parse_deleted_lines_from_diff(result.stdout)
    except (subprocess.TimeoutExpired, Exception):
        return []


def blame_lines(repo_path: str, commit_hash: str, file_path: str, lines: list[int]) -> list[str]:
    """Run git blame on parent of commit_hash for given lines, return introducing hashes."""
    blamed_hashes = set()

    if not lines:
        return []

    try:
        result = subprocess.run(
            ["git", "blame", "--porcelain", f"{commit_hash}^", "--", file_path],
            cwd=repo_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if result.returncode != 0:
            return []

        line_to_hash = {}
        current_hash = None
        current_line = None

        for blame_line in result.stdout.split("\n"):
            match = re.match(r'^([0-9a-f]{40}) (\d+) (\d+)', blame_line)
            if match:
                current_hash = match.group(1)
                current_line = int(match.group(3))  # result line number
                # Map original line number to hash
                orig_line = int(match.group(2))
                line_to_hash[orig_line] = current_hash

        for line_num in lines:
            h = line_to_hash.get(line_num)
            if h and not h.startswith("0000000"):
                blamed_hashes.add(h)

    except (subprocess.TimeoutExpired, Exception):
        return []

    return list(blamed_hashes)


def run_szz_for_repo(
    db: Session,
    repo_id: int,
    repo_path: str,
    batch_size: int = 50,
) -> dict:
    existing = db.query(BugLabel).filter(BugLabel.repo_id == repo_id).count()
    if existing > 0:
        logger.info("SZZ already ran for repo_id=%d (%d labels). Skipping.", repo_id, existing)
        return {"skipped": True, "existing_labels": existing}

    fix_commits = get_fix_commits(db, repo_id)
    logger.info("Found %d fix commits for repo_id=%d", len(fix_commits), repo_id)

    total_introductions = 0
    total_files_processed = 0
    total_skipped = 0

    for i, fix in enumerate(fix_commits):
        files = get_fix_commit_files(db, repo_id, fix["hash"])

        for file_path in files:
            deleted_lines = get_diff_deleted_lines(repo_path, fix["hash"], file_path)

            if not deleted_lines:
                total_skipped += 1
                continue

            # limit lines per file to keep blame fast
            sampled_lines = deleted_lines[:20] if len(deleted_lines) > 20 else deleted_lines

            blamed = blame_lines(repo_path, fix["hash"], file_path, sampled_lines)

            for bug_hash in blamed:
                label = BugLabel(
                    repo_id=repo_id,
                    file_path=file_path,
                    snapshot_date=None,  # filled later during dataset assembly
                    is_buggy=True,
                    fix_commit_hash=fix["hash"],
                    bug_introducing_commit_hash=bug_hash,
                )
                db.add(label)
                total_introductions += 1

            total_files_processed += 1

        if (i + 1) % batch_size == 0:
            db.commit()
            logger.info(
                "  SZZ progress: %d/%d fix commits, %d bug introductions found",
                i + 1, len(fix_commits), total_introductions,
            )

    db.commit()

    summary = {
        "fix_commits": len(fix_commits),
        "files_processed": total_files_processed,
        "files_skipped": total_skipped,
        "bug_introductions": total_introductions,
    }
    logger.info("SZZ complete for repo_id=%d: %s", repo_id, summary)
    return summary
