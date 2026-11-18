"""
Domain knowledge about every feature the models use.

The models only ever see numbers. This module maps those numbers back to
something a developer can act on: what the metric actually measures, how this
file compares to its repository, why the value pushes the prediction toward
"buggy" or "clean", and what to do about it.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FeatureInfo:
    label: str
    unit: str
    what: str
    high_risk: str
    low_risk: str
    advice: list[str] = field(default_factory=list)
    category: str = "process"
    high_threshold: float | None = None
    # Engineered features are ratios the developer never sees directly,
    # so we explain them in terms of their inputs instead.
    derived: bool = False


FEATURES: dict[str, FeatureInfo] = {
    # ─── Size ──────────────────────────────────────────────────────────
    "loc": FeatureInfo(
        label="Lines of code",
        unit="lines",
        what="the physical size of the file, excluding blank lines and comments",
        high_risk="large files hold more responsibilities, so a change is more "
                  "likely to touch logic the author did not fully have in mind",
        low_risk="the file is small enough that a reader can hold all of it in "
                 "their head at once",
        advice=[
            "Split the file along its natural seams — group the exported symbols "
            "that change together and move each group into its own module.",
            "If the file is a barrel of unrelated helpers, move each helper next "
            "to the code that actually uses it.",
        ],
        category="size",
        high_threshold=300,
    ),
    "num_functions": FeatureInfo(
        label="Number of functions",
        unit="functions",
        what="how many functions, methods and arrow functions the file declares",
        high_risk="many declarations in one file usually means the module has "
                  "taken on several unrelated jobs",
        low_risk="the file has a focused, narrow surface",
        advice=[
            "Group the functions by the data they operate on and extract each "
            "group into its own module.",
            "Functions used by only one caller can be inlined or moved to the caller.",
        ],
        category="size",
        high_threshold=25,
    ),
    "avg_function_length": FeatureInfo(
        label="Average function length",
        unit="lines",
        what="the mean body length of the functions in the file",
        high_risk="long functions hide branches and early returns, which is where "
                  "edge cases tend to be missed",
        low_risk="functions are short, so each one is easy to read and test in isolation",
        advice=[
            "Extract the distinct steps inside the longest functions into named "
            "helpers — the name documents the intent and makes the branch testable.",
            "Replace long if/else ladders with early returns or a lookup table.",
        ],
        category="complexity",
        high_threshold=30,
    ),
    "num_parameters_max": FeatureInfo(
        label="Largest parameter list",
        unit="parameters",
        what="the parameter count of the widest function signature in the file",
        high_risk="long parameter lists are easy to call in the wrong order and "
                  "signal that the function is doing too much",
        low_risk="call sites are hard to get wrong",
        advice=[
            "Collect related parameters into a single options object with named "
            "fields so the call site is self-documenting.",
            "If several parameters are always passed together, they probably belong "
            "to a type of their own.",
        ],
        category="complexity",
        high_threshold=5,
    ),

    # ─── Complexity ────────────────────────────────────────────────────
    "cyclomatic_complexity": FeatureInfo(
        label="Cyclomatic complexity",
        unit="paths",
        what="the number of independent paths through the code — every if, loop, "
             "case, ternary and && adds one",
        high_risk="each path is a case that has to be reasoned about and covered by "
                  "a test; past a few dozen, full coverage stops being realistic",
        low_risk="the control flow is straightforward, so the file is easy to cover "
                 "with tests",
        advice=[
            "Pull the deepest conditional blocks into small named predicates — the "
            "branch count stays the same but each piece becomes testable.",
            "Replace type-checking or string-matching chains with a discriminated "
            "union so the compiler enforces exhaustiveness.",
            "Add tests for the uncovered branches before refactoring, so the "
            "refactor is verifiable.",
        ],
        category="complexity",
        high_threshold=30,
    ),
    "max_nesting_depth": FeatureInfo(
        label="Maximum nesting depth",
        unit="levels",
        what="how deeply blocks are nested at the worst point in the file",
        high_risk="deep nesting means a reader has to track several conditions at "
                  "once, and it is where off-by-one and wrong-branch bugs cluster",
        low_risk="the code stays flat and readable",
        advice=[
            "Invert the guard conditions and return early to flatten the deepest block.",
            "Extract the innermost block into its own function — nesting disappears "
            "at the call site.",
        ],
        category="complexity",
        high_threshold=4,
    ),
    "complexity_per_loc": FeatureInfo(
        label="Complexity density",
        unit="paths per line",
        what="cyclomatic complexity divided by lines of code — how tightly packed "
             "the branching is",
        high_risk="the logic is dense rather than merely long, so there is little "
                  "straight-line code between decisions",
        low_risk="branching is spread thin across the file",
        advice=[
            "Dense branching usually means business rules are inlined — move them "
            "into a rules table or a policy object.",
        ],
        category="complexity",
        high_threshold=0.2,
        derived=True,
    ),
    "nesting_x_complexity": FeatureInfo(
        label="Nesting × complexity",
        unit="score",
        what="nesting depth multiplied by cyclomatic complexity, which isolates "
             "files that are both deeply nested and heavily branched",
        high_risk="the two worst structural signals reinforce each other here, which "
                  "historically is the strongest single predictor of defects",
        low_risk="the file avoids the combination of depth and branching",
        advice=[
            "Target the single deepest, most-branched function first — it accounts "
            "for most of this score.",
        ],
        category="complexity",
        derived=True,
    ),
    "functions_per_loc": FeatureInfo(
        label="Function density",
        unit="functions per line",
        what="how many functions the file declares relative to its size",
        high_risk="very high density can mean a grab-bag of one-line helpers with "
                  "no clear owner",
        low_risk="function size and count are in proportion",
        advice=[
            "Consider whether the small helpers belong closer to their call sites.",
        ],
        category="size",
        derived=True,
    ),

    # ─── Change history / process ──────────────────────────────────────
    "commits_count": FeatureInfo(
        label="Commit count",
        unit="commits",
        what="how many times this file has been modified over its lifetime",
        high_risk="frequently edited files are where requirements are still moving, "
                  "and every edit is another chance to introduce a defect",
        low_risk="the file is stable and rarely needs to change",
        advice=[
            "Frequent change is not itself a problem — make it safe. Get this file "
            "under solid test coverage so the next edit is verified.",
            "If the churn comes from configuration or constants mixed into logic, "
            "separate them so routine edits stop touching the logic.",
        ],
        category="process",
        high_threshold=30,
    ),
    "unique_authors": FeatureInfo(
        label="Distinct authors",
        unit="developers",
        what="how many different developers have committed to this file",
        high_risk="many authors means many mental models of the same code, and "
                  "conventions drift when no one owns the file",
        low_risk="a small group owns the file, so its conventions stay consistent",
        advice=[
            "Assign an explicit owner or reviewer for this path (a CODEOWNERS entry) "
            "so every change is seen by someone who knows it.",
            "Write down the invariants the file relies on — with many authors, the "
            "assumptions need to live in the code, not in someone's head.",
        ],
        category="process",
        high_threshold=8,
    ),
    "churn": FeatureInfo(
        label="Code churn",
        unit="lines",
        what="the total number of lines added plus deleted across all commits",
        high_risk="high churn means large parts of the file have been rewritten, so "
                  "the current code has less accumulated production exposure than "
                  "its age suggests",
        low_risk="the file has changed little, so its code is well exercised",
        advice=[
            "Check whether the churn is concentrated in one region — that region is "
            "the unstable part and the one that needs tests.",
        ],
        category="process",
        high_threshold=1000,
    ),
    "churn_per_commit": FeatureInfo(
        label="Churn per commit",
        unit="lines per commit",
        what="the average size of a change to this file",
        high_risk="large commits are harder to review carefully, so defects slip "
                  "through review more often",
        low_risk="changes arrive in small, reviewable increments",
        advice=[
            "Break future changes to this file into smaller commits — review quality "
            "drops sharply past a few hundred changed lines.",
        ],
        category="process",
        high_threshold=60,
        derived=True,
    ),
    "lines_added_total": FeatureInfo(
        label="Lines added",
        unit="lines",
        what="every line ever added to this file across its history",
        high_risk="sustained growth means the file keeps absorbing new "
                  "responsibilities instead of delegating them",
        low_risk="the file has not grown much since it was written",
        advice=[
            "When the next feature lands here, add it as a new module and compose "
            "rather than extending this file again.",
        ],
        category="process",
    ),
    "lines_deleted_total": FeatureInfo(
        label="Lines deleted",
        unit="lines",
        what="every line ever removed from this file across its history",
        high_risk="heavy deletion means logic has been reworked or reverted "
                  "repeatedly, which is a strong signal the design has not settled",
        low_risk="little has been torn out, suggesting the original design held up",
        advice=[
            "Repeated rewrites point at a design problem rather than a coding one — "
            "clarify what this module is responsible for before the next change.",
            "Look for reverted commits in this file's history; a revert often means "
            "a defect reached production.",
        ],
        category="process",
    ),
    "deleted_ratio": FeatureInfo(
        label="Deletion ratio",
        unit="fraction of churn",
        what="the share of this file's churn that was deletion rather than addition",
        high_risk="a high deletion share means changes replace existing logic instead "
                  "of extending it, which is the pattern of rework and reverts",
        low_risk="changes mostly add to the file rather than replace it",
        advice=[
            "Trace the largest deletions — if they undo recent work, the requirements "
            "for this module need clarifying before more code is written.",
        ],
        category="process",
        high_threshold=0.5,
        derived=True,
    ),
    "added_ratio": FeatureInfo(
        label="Addition ratio",
        unit="fraction of churn",
        what="the share of this file's churn that was addition rather than deletion",
        high_risk="a file that only ever grows accumulates responsibilities and "
                  "eventually outgrows its tests",
        low_risk="growth is balanced against cleanup",
        advice=[
            "Pair the next feature addition with removal of whatever it supersedes.",
        ],
        category="process",
        derived=True,
    ),
    "authors_per_commit": FeatureInfo(
        label="Authors per commit",
        unit="ratio",
        what="distinct authors divided by commit count — whether edits come from "
             "many people occasionally or a few people repeatedly",
        high_risk="a high ratio means most commits come from someone new to the file, "
                  "so there is little retained context",
        low_risk="edits come from people who have worked in the file before",
        advice=[
            "Make the file's assumptions explicit in types and tests so a first-time "
            "editor cannot violate them silently.",
        ],
        category="process",
        derived=True,
    ),
    "avg_churn_per_author": FeatureInfo(
        label="Churn per author",
        unit="lines per developer",
        what="how many lines each contributor changed on average",
        high_risk="individual contributors are making sweeping changes, which is "
                  "harder to review than incremental work",
        low_risk="each contributor's footprint is small",
        advice=[
            "Require a second reviewer for large changes to this path.",
        ],
        category="process",
        derived=True,
    ),

    # ─── Defect history ────────────────────────────────────────────────
    "bug_fix_commits_count": FeatureInfo(
        label="Past bug-fix commits",
        unit="commits",
        what="how many commits touching this file had a message indicating a fix",
        high_risk="defects cluster — a file that needed many fixes before is the most "
                  "likely place for the next one",
        low_risk="the file has needed few corrections, so its logic has held up",
        advice=[
            "Read the last few fixes to this file. If they cluster in one function, "
            "that function needs a rewrite rather than another patch.",
            "Add a regression test for each past fix that does not already have one — "
            "repeated fixes in one spot usually mean the earlier ones were untested.",
        ],
        category="defects",
        high_threshold=5,
    ),
    "bugfix_ratio": FeatureInfo(
        label="Bug-fix ratio",
        unit="fraction of commits",
        what="the share of commits to this file that were fixes rather than features",
        high_risk="when most changes are corrections, the file is in maintenance debt "
                  "rather than active development",
        low_risk="most work on the file is new functionality, not repair",
        advice=[
            "A high fix ratio justifies rewriting the module rather than continuing "
            "to patch it — the patches are not converging.",
        ],
        category="defects",
        high_threshold=0.3,
        derived=True,
    ),

    # ─── Age ───────────────────────────────────────────────────────────
    "file_age_days": FeatureInfo(
        label="File age",
        unit="days",
        what="how long ago the file was first committed",
        high_risk="old files accumulate assumptions from earlier versions of the "
                  "codebase that no longer hold",
        low_risk="the file is recent and written against current conventions",
        advice=[
            "Check whether the file still uses patterns the codebase has moved away "
            "from — old idioms next to new ones is where integration bugs appear.",
        ],
        category="history",
        high_threshold=700,
    ),
    "loc_x_age": FeatureInfo(
        label="Size × age",
        unit="score",
        what="log size multiplied by log age, isolating files that are both large "
             "and old",
        high_risk="a large file that has been around a long time is the classic "
                  "legacy hotspot: many responsibilities, many stale assumptions",
        low_risk="the file avoids being simultaneously large and old",
        advice=[
            "Treat this file as legacy: add characterization tests that capture what "
            "it currently does before changing anything.",
        ],
        category="history",
        derived=True,
    ),
}


def get_info(feature: str) -> FeatureInfo:
    """Knowledge for a feature, with a usable default for unknown names."""
    if feature in FEATURES:
        return FEATURES[feature]
    return FeatureInfo(
        label=feature.replace("_", " ").capitalize(),
        unit="",
        what=f"the {feature.replace('_', ' ')} metric",
        high_risk="a high value here correlates with defects in the training data",
        low_risk="the value here is in the range associated with stable files",
        category="other",
    )


def format_value(feature: str, value: float | None) -> str:
    """Render a metric value the way a developer expects to read it."""
    if value is None:
        return "n/a"
    info = get_info(feature)
    if info.unit in ("fraction of churn", "fraction of commits"):
        return f"{value * 100:.0f}%"
    if info.unit in ("paths per line", "functions per line", "ratio"):
        return f"{value:.3f}"
    if abs(value - round(value)) < 0.01:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


def classify_level(
    feature: str,
    value: float | None,
    baseline: float | None = None,
) -> str:
    """
    Where this value sits for this metric: "high", "elevated", "normal" or "low".

    A SHAP value only says which way a feature moved the prediction, not whether
    the underlying number is actually large. Tree models routinely push toward
    "buggy" on a low value because of how it interacts with everything else, so
    the level has to be judged separately before we describe it to a developer.
    """
    if value is None:
        return "unknown"

    info = get_info(feature)

    if info.high_threshold is not None:
        if value >= info.high_threshold:
            return "high"
        if value >= info.high_threshold * 0.7:
            return "elevated"

    if baseline and baseline > 0:
        ratio = value / baseline
        if ratio >= 2:
            return "high"
        if ratio >= 1.4:
            return "elevated"
        if ratio <= 0.5:
            return "low"

    if info.high_threshold is not None and value <= info.high_threshold * 0.3:
        return "low"

    return "normal"


def compare_to_baseline(value: float | None, baseline: float | None) -> str | None:
    """Phrase describing how this file's value relates to its repository."""
    if value is None or baseline is None or baseline <= 0:
        return None
    ratio = value / baseline
    if ratio >= 3:
        return f"{ratio:.1f}× the repository average"
    if ratio >= 1.5:
        return f"{ratio:.1f}× the repository average"
    if ratio <= 0.4:
        return "well below the repository average"
    if ratio <= 0.75:
        return "below the repository average"
    return "about average for this repository"
