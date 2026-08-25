from app.miners.git_miner import is_bug_fix_commit


def test_bug_fix_detection_positive():
    assert is_bug_fix_commit("fix: resolve null pointer in parser") is True
    assert is_bug_fix_commit("Bug fix for login timeout") is True
    assert is_bug_fix_commit("fixes #123 — handle edge case") is True
    assert is_bug_fix_commit("hotfix: critical production crash") is True
    assert is_bug_fix_commit("closes #456") is True


def test_bug_fix_detection_negative():
    assert is_bug_fix_commit("feat: add new dashboard component") is False
    assert is_bug_fix_commit("refactor: clean up database module") is False
    assert is_bug_fix_commit("docs: update README") is False
    assert is_bug_fix_commit("chore: update dependencies") is False
