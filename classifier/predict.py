"""predict(texts) -> ["request" | "not_request", ...]. Offline, CPU, a few milliseconds per batch.

Uses classifier/model.joblib (built by `python -m classifier.train`). If the
file is missing it trains in memory first, which takes a few seconds.
"""
from __future__ import annotations

from pathlib import Path

import joblib

_MODEL_PATH = Path(__file__).resolve().parent / "model.joblib"
_loaded: dict | None = None


def _load() -> dict:
    global _loaded
    if _loaded is None:
        if not _MODEL_PATH.exists():
            from .train import main
            main()
        _loaded = joblib.load(_MODEL_PATH)
    return _loaded


def scores(texts: list[str]) -> list[float]:
    """Probability that each text is a real request."""
    return [float(p) for p in _load()["model"].predict_proba(list(texts))[:, 1]]


def predict(texts: list[str]) -> list[str]:
    threshold = _load()["threshold"]
    return ["request" if p >= threshold else "not_request" for p in scores(texts)]
