"""
Multi-model ensemble predictor.
Loads N trained models and predicts via majority voting + averaged probabilities.
"""

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ENSEMBLE_MODELS = [
    "xgboost_model.pkl",
    "gradient_boosting_model.pkl",
    "random_forest_model.pkl",
    "lightgbm_model.pkl",
    "extra_trees_model.pkl",
]


@dataclass
class ModelEntry:
    name: str
    model: object
    features: list[str]
    metrics: dict = field(default_factory=dict)


@dataclass
class EnsemblePrediction:
    risk_score: float
    risk_level: str
    is_buggy: bool
    votes_buggy: int
    votes_clean: int
    total_models: int
    per_model: list[dict]


class EnsemblePredictor:
    def __init__(self, models_dir: str | Path):
        self.models_dir = Path(models_dir)
        self.models: list[ModelEntry] = []
        self._loaded = False

    def load(self):
        if self._loaded:
            return

        for pkl_name in ENSEMBLE_MODELS:
            path = self.models_dir / pkl_name
            if not path.exists():
                logger.warning("Model not found, skipping: %s", path)
                continue
            try:
                with open(path, "rb") as f:
                    data = pickle.load(f)
                entry = ModelEntry(
                    name=data.get("model_name", pkl_name.replace("_model.pkl", "")),
                    model=data["model"],
                    features=data.get("features", []),
                    metrics={k: v for k, v in data.get("metrics", {}).items()
                             if k != "confusion_matrix"},
                )
                self.models.append(entry)
                logger.info("Loaded model: %s (F1=%.4f)", entry.name,
                            entry.metrics.get("f1", 0))
            except Exception as e:
                logger.error("Failed to load %s: %s", pkl_name, e)

        if not self.models:
            raise RuntimeError(f"No models loaded from {self.models_dir}")

        self._loaded = True
        logger.info("Ensemble ready: %d models", len(self.models))

    def predict(self, feature_dict: dict) -> EnsemblePrediction:
        self.load()

        per_model = []
        probas = []

        for entry in self.models:
            feature_values = [float(feature_dict.get(f, 0)) for f in entry.features]
            X = np.array([feature_values])

            proba = float(entry.model.predict_proba(X)[0][1])
            label = int(proba >= 0.5)
            probas.append(proba)

            per_model.append({
                "model_name": entry.name,
                "risk_score": round(proba, 4),
                "prediction": "buggy" if label else "clean",
                "f1_score": round(entry.metrics.get("f1", 0), 4),
            })

        votes_buggy = sum(1 for p in probas if p >= 0.5)
        votes_clean = len(probas) - votes_buggy
        avg_proba = float(np.mean(probas))
        is_buggy = votes_buggy > votes_clean

        if avg_proba >= 0.7:
            risk_level = "high"
        elif avg_proba >= 0.4:
            risk_level = "medium"
        else:
            risk_level = "low"

        return EnsemblePrediction(
            risk_score=round(avg_proba, 4),
            risk_level=risk_level,
            is_buggy=is_buggy,
            votes_buggy=votes_buggy,
            votes_clean=votes_clean,
            total_models=len(self.models),
            per_model=per_model,
        )

    def predict_batch(self, rows: list[dict]) -> list[EnsemblePrediction]:
        self.load()
        return [self.predict(row) for row in rows]

    def get_info(self) -> dict:
        self.load()
        return {
            "total_models": len(self.models),
            "models": [
                {
                    "name": m.name,
                    "features_count": len(m.features),
                    "metrics": m.metrics,
                }
                for m in self.models
            ],
        }
