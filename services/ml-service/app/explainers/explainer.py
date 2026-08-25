"""
SHAP-based explainability with optional LLM text generation.
"""

import logging

import httpx
import numpy as np
import shap

from app.config import settings

logger = logging.getLogger(__name__)


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


async def generate_llm_explanation(
    file_path: str,
    risk_score: float,
    top_features: dict[str, float],
    top_n: int = 3,
) -> str:
    top = dict(list(top_features.items())[:top_n])

    prompt = f"""You are a software quality expert analyzing defect prediction results.

File: {file_path}
Predicted defect risk score: {risk_score:.2f} (0 = safe, 1 = very risky)

Top contributing factors (SHAP values):
{chr(10).join(f"- {name}: {value:+.3f}" for name, value in top.items())}

Explain in 2-3 sentences why this file is predicted to be risky (or safe).
Focus on actionable insights for the developer. Be specific about which metrics
are concerning and what could be done to reduce risk."""

    if not settings.llm_api_key:
        return f"Risk score: {risk_score:.2f}. Top factors: {', '.join(top.keys())}. (LLM API key not configured)"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.llm_api_url}/chat/completions",
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
            json={
                "model": settings.llm_model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
