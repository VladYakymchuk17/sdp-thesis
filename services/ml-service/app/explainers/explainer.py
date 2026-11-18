"""
SHAP-based explainability with optional LLM text generation.

The SHAP values say which features moved the prediction. This module turns that
into something a developer can act on by pairing each feature with its actual
value, how that value compares to the rest of the repository, and what to do
about it. Supports Ollama (local) and any OpenAI-compatible API; falls back to a
generated report when no LLM is reachable.
"""

import logging
from dataclasses import asdict, dataclass, field

import httpx
import numpy as np
import shap

from app.config import settings
from app.explainers.knowledge import (
    classify_level,
    compare_to_baseline,
    format_value,
    get_info,
)

logger = logging.getLogger(__name__)

RISK_BANDS = (
    (0.7, "high"),
    (0.4, "medium"),
    (0.0, "low"),
)


def risk_label(risk_score: float) -> str:
    for threshold, label in RISK_BANDS:
        if risk_score >= threshold:
            return label
    return "low"


@dataclass
class Factor:
    """One feature's contribution, described in developer terms."""

    feature: str
    label: str
    shap_value: float
    direction: str          # "increases" | "decreases"
    impact_share: float     # share of total absolute SHAP, 0..1
    value: float | None
    value_display: str
    unit: str
    what: str
    interpretation: str
    baseline_comparison: str | None
    category: str
    is_above_threshold: bool
    level: str              # "high" | "elevated" | "normal" | "low" | "unknown"
    actionable: bool        # value is genuinely elevated, so advice applies
    advice: list[str] = field(default_factory=list)


@dataclass
class Explanation:
    summary: str
    detail: str
    recommendations: list[str]
    factors: list[dict]
    source: str             # "llm" | "generated"


def compute_shap_values(
    model,
    X: np.ndarray,
    feature_names: list[str],
) -> dict[str, float]:
    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X)

    if isinstance(shap_values, list):
        values = shap_values[1][0]
    else:
        values = shap_values[0]

    feature_importance = dict(zip(feature_names, values, strict=False))
    sorted_features = dict(
        sorted(feature_importance.items(), key=lambda x: abs(x[1]), reverse=True)
    )

    return sorted_features


def build_factors(
    shap_features: dict[str, float],
    values: dict[str, float] | None = None,
    baselines: dict[str, float] | None = None,
    top_n: int = 5,
) -> list[Factor]:
    """Pair the highest-impact SHAP features with their real metric values."""
    values = values or {}
    baselines = baselines or {}

    total_impact = sum(abs(v) for v in shap_features.values()) or 1.0
    factors: list[Factor] = []

    for feature, shap_value in list(shap_features.items())[:top_n]:
        info = get_info(feature)
        value = values.get(feature)
        baseline = baselines.get(feature)
        pushes_buggy = shap_value > 0
        level = classify_level(feature, value, baseline)

        threshold_exceeded = (
            info.high_threshold is not None
            and value is not None
            and value >= info.high_threshold
        )

        # Advice only makes sense where the number is actually large. Telling
        # someone to split a 40-line file because SHAP happened to point that
        # way would be wrong.
        actionable = pushes_buggy and level in ("high", "elevated")

        if pushes_buggy:
            if actionable:
                interpretation = info.high_risk
            else:
                # The long explanation of combination effects is stated once in the
                # narrative, so keep the per-factor note short here.
                interpretation = (
                    "normal for this codebase, so it contributes only in combination "
                    "with the other metrics"
                )
        else:
            if level in ("high", "elevated"):
                interpretation = (
                    "on the high side, yet the models treat it as stabilising for "
                    "this particular file"
                )
            else:
                interpretation = info.low_risk

        factors.append(
            Factor(
                feature=feature,
                label=info.label,
                shap_value=round(float(shap_value), 4),
                direction="increases" if pushes_buggy else "decreases",
                impact_share=round(abs(shap_value) / total_impact, 4),
                value=round(float(value), 4) if value is not None else None,
                value_display=format_value(feature, value),
                unit=info.unit,
                what=info.what,
                interpretation=interpretation,
                baseline_comparison=compare_to_baseline(value, baseline),
                category=info.category,
                is_above_threshold=threshold_exceeded,
                level=level,
                actionable=actionable,
                advice=info.advice if actionable else [],
            )
        )

    return factors


def build_recommendations(factors: list[Factor], risk_score: float) -> list[str]:
    """Prioritised, de-duplicated actions drawn from the actionable factors."""
    recommendations: list[str] = []
    seen: set[str] = set()

    actionable = [f for f in factors if f.actionable]
    # Metrics past their absolute threshold come first, then by SHAP impact.
    actionable.sort(key=lambda f: (not f.is_above_threshold, -f.impact_share))

    for factor in actionable:
        for item in factor.advice:
            if item not in seen:
                seen.add(item)
                recommendations.append(item)

    if not actionable and risk_score >= 0.4:
        # The models flagged the file but no individual metric is extreme, so
        # pointing at one metric would be misleading.
        drivers = [f for f in factors if f.direction == "increases"][:2]
        names = " and ".join(f.label.lower() for f in drivers) or "its change history"
        recommendations.append(
            f"No single metric is extreme here — the risk comes from the combination "
            f"of {names} rather than one outlier, so there is no single number to fix."
        )
        recommendations.append(
            "Start with test coverage: confirm the branches in this file are covered, "
            "since that is what limits the damage when the prediction is right."
        )
        recommendations.append(
            "Compare this file against the repository's other high-risk files. If they "
            "share a pattern, the fix belongs at the design level, not in this file."
        )

    if risk_score >= 0.7:
        recommendations.append(
            "Until then, treat changes to this file as high-risk: require a second "
            "reviewer and confirm the touched paths have test coverage."
        )
    elif risk_score >= 0.4:
        recommendations.append(
            "Flag this file during code review and check test coverage before merging "
            "changes to it."
        )
    elif not recommendations:
        recommendations.append(
            "No action needed. The metrics for this file are in the range associated "
            "with stable code — keep the current test coverage in place."
        )

    return recommendations[:6]


def _describe_factor_sentence(factor: Factor) -> str:
    """One sentence tying a factor's value to its consequence."""
    parts = [f"**{factor.label}**"]

    if factor.value is not None:
        value_text = factor.value_display
        if factor.unit and factor.unit not in ("score", "ratio", "fraction of churn",
                                               "fraction of commits", "paths per line",
                                               "functions per line"):
            value_text = f"{value_text} {factor.unit}"
        parts.append(f"is {value_text}")
        if factor.baseline_comparison:
            parts.append(f"({factor.baseline_comparison})")

    sentence = " ".join(parts)

    # Only the factors worth acting on get the full "and here is why it matters"
    # treatment; the rest would just repeat the narrative's closing note.
    if not factor.actionable and factor.direction == "increases":
        return f"{sentence} — {factor.interpretation}."

    verb = "pushing the prediction toward buggy" if factor.direction == "increases" \
        else "pulling the prediction toward clean"
    return f"{sentence} — {factor.interpretation}, {verb}."


def generate_report(
    file_path: str,
    risk_score: float,
    factors: list[Factor],
    recommendations: list[str],
) -> tuple[str, str]:
    """Deterministic explanation used when no LLM is available."""
    level = risk_label(risk_score)
    risky = [f for f in factors if f.direction == "increases"]
    protective = [f for f in factors if f.direction == "decreases"]

    if level == "high":
        opening = (
            f"The ensemble scores `{file_path}` at {risk_score:.2f}, placing it in the "
            f"high-risk band. The models agree that this file is substantially more "
            f"likely than average to receive a defect-fixing commit."
        )
    elif level == "medium":
        opening = (
            f"The ensemble scores `{file_path}` at {risk_score:.2f}, in the medium-risk "
            f"band. The file shows some of the patterns associated with defects, but "
            f"not strongly enough to call it a hotspot."
        )
    else:
        opening = (
            f"The ensemble scores `{file_path}` at {risk_score:.2f}, in the low-risk "
            f"band. Its size, complexity and change history all sit in the range the "
            f"models associate with stable code."
        )

    detail_parts: list[str] = []

    if risky:
        detail_parts.append("**What is driving the risk**\n")
        detail_parts.extend(f"- {_describe_factor_sentence(f)}" for f in risky)

    if protective:
        detail_parts.append("\n**What is working in the file's favour**\n")
        detail_parts.extend(f"- {_describe_factor_sentence(f)}" for f in protective)

    over_threshold = [f for f in risky if f.is_above_threshold]
    if over_threshold:
        names = ", ".join(f.label.lower() for f in over_threshold)
        detail_parts.append(
            f"\nAmong these, {names} "
            f"{'are' if len(over_threshold) > 1 else 'is'} past the threshold where "
            f"the metric becomes a problem on its own, independent of the model."
        )
    elif risky and level != "low":
        detail_parts.append(
            "\nNone of these metrics is extreme on its own. The models are reacting to "
            "the combination, which means there is no single number to bring down — the "
            "practical response is test coverage and closer review rather than a "
            "targeted refactor."
        )

    return opening, "\n".join(detail_parts)


def build_prompt(
    file_path: str,
    risk_score: float,
    factors: list[Factor],
    repo_name: str | None = None,
) -> str:
    """Prompt that gives the model values and context, not just feature names."""
    lines = []
    for factor in factors:
        bits = [
            f"- {factor.label} ({factor.feature}): value = {factor.value_display}",
        ]
        if factor.baseline_comparison:
            bits.append(f"which is {factor.baseline_comparison}")
        bits.append(f"level = {factor.level}")
        bits.append(
            f"SHAP {factor.shap_value:+.3f} "
            f"({factor.direction} risk, {factor.impact_share * 100:.0f}% of total impact)"
        )
        if factor.is_above_threshold:
            bits.append("ABOVE the accepted threshold for this metric")
        lines.append(", ".join(bits) + f". This metric measures {factor.what}.")

    any_actionable = any(f.actionable for f in factors)
    accuracy_rule = (
        "Some metrics below push toward 'buggy' even though their value is normal or "
        "low — that is how tree models work. Never describe a normal or low value as "
        "large, heavy or excessive, and never recommend reducing a metric that is "
        "already low. For those, say the risk comes from the combination of metrics."
    )
    if not any_actionable:
        accuracy_rule += (
            " In this case NO metric is genuinely elevated, so do not prescribe a "
            "refactor of any single metric. Focus WHAT TO DO on test coverage, review "
            "practice and verifying the prediction."
        )

    context = f" in the {repo_name} repository" if repo_name else ""

    return f"""You are a senior engineer reviewing a defect-prediction result for a TypeScript file{context}.

File: {file_path}
Ensemble risk score: {risk_score:.2f} ({risk_label(risk_score)} risk, where 1.00 = almost certain to need a bug fix)

Feature contributions from SHAP, with the file's actual measured values:
{chr(10).join(lines)}

Write an explanation for the developer who owns this file, in this exact structure:

ASSESSMENT
Two or three sentences stating how risky the file is and the single most important reason why. Reference the actual numbers above. Do not restate the score alone — explain what the numbers mean for someone changing this file.

WHY
Three to four bullets. Each bullet takes one metric, states its value, and explains the concrete mechanism by which that value leads to defects. Avoid restating the metric name as an explanation — say what goes wrong in practice.

WHAT TO DO
Three to four bullets of specific, ordered remediation steps. Each must be an action the developer can start today on this file, not general advice. Where a metric is far above threshold, say which part of the file to attack first. If the file is low risk, say what to preserve instead of inventing work.

Rules: be concrete and reference the numbers. No preamble, no closing summary, no markdown headers beyond the three labels above. Never suggest rewriting the whole file when a targeted change would do.

Accuracy requirement: {accuracy_rule}"""


def _parse_llm_sections(text: str) -> tuple[str, str, list[str]]:
    """Split the model's ASSESSMENT / WHY / WHAT TO DO response."""
    upper = text.upper()
    idx_why = upper.find("WHY")
    idx_todo = upper.find("WHAT TO DO")

    if idx_why == -1 or idx_todo == -1 or not (idx_why < idx_todo):
        # Model ignored the structure — use the whole reply as the summary.
        return text.strip(), "", []

    assessment = text[:idx_why]
    why = text[idx_why:idx_todo]
    todo = text[idx_todo:]

    for label in ("ASSESSMENT", "Assessment"):
        assessment = assessment.replace(label, "")
    why = why[3:] if why.upper().startswith("WHY") else why
    todo = todo[len("WHAT TO DO"):]

    recommendations = [
        line.lstrip("-•* ").strip()
        for line in todo.splitlines()
        if line.strip().lstrip("-•* ").strip()
    ]

    return assessment.strip(), why.strip(), recommendations


async def generate_explanation(
    file_path: str,
    risk_score: float,
    shap_features: dict[str, float],
    values: dict[str, float] | None = None,
    baselines: dict[str, float] | None = None,
    repo_name: str | None = None,
    top_n: int = 5,
) -> Explanation:
    """
    Full explanation for one file: structured factors, narrative and advice.
    Uses the configured LLM when reachable, otherwise a generated report.
    """
    factors = build_factors(shap_features, values, baselines, top_n=top_n)
    recommendations = build_recommendations(factors, risk_score)
    summary, detail = generate_report(file_path, risk_score, factors, recommendations)

    llm_text = await _call_llm(file_path, risk_score, factors, repo_name)

    if llm_text:
        llm_summary, llm_detail, llm_recommendations = _parse_llm_sections(llm_text)
        if llm_summary:
            return Explanation(
                summary=llm_summary,
                detail=llm_detail or detail,
                # Keep the knowledge-base advice when the model gave none.
                recommendations=llm_recommendations or recommendations,
                factors=[asdict(f) for f in factors],
                source="llm",
            )

    return Explanation(
        summary=summary,
        detail=detail,
        recommendations=recommendations,
        factors=[asdict(f) for f in factors],
        source="generated",
    )


async def _call_llm(
    file_path: str,
    risk_score: float,
    factors: list[Factor],
    repo_name: str | None,
) -> str | None:
    """Returns the raw LLM reply, or None when the LLM is unavailable."""
    prompt = build_prompt(file_path, risk_score, factors, repo_name)

    headers = {"Content-Type": "application/json"}
    if settings.llm_api_key:
        headers["Authorization"] = f"Bearer {settings.llm_api_key}"

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.llm_api_url}/chat/completions",
                headers=headers,
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 900,
                    "temperature": 0.2,
                },
                timeout=120,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
    except httpx.ConnectError:
        logger.info("LLM not reachable at %s — using generated report", settings.llm_api_url)
        return None
    except Exception as e:
        logger.warning("LLM call failed: %s — using generated report", e)
        return None


# ─── Backwards-compatible helpers ──────────────────────────────────────

async def generate_llm_explanation(
    file_path: str,
    risk_score: float,
    top_features: dict[str, float],
    top_n: int = 3,
) -> str:
    result = await generate_explanation(
        file_path, risk_score, top_features, top_n=top_n
    )
    return f"{result.summary}\n\n{result.detail}".strip()


def _fallback_explanation(
    file_path: str,
    risk_score: float,
    top_features: dict[str, float],
    top_n: int = 3,
) -> str:
    factors = build_factors(top_features, top_n=top_n)
    recommendations = build_recommendations(factors, risk_score)
    summary, detail = generate_report(file_path, risk_score, factors, recommendations)
    return f"{summary}\n\n{detail}".strip()
