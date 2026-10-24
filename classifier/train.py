"""Trains the request / not_request classifier and saves classifier/model.joblib.

    python -m classifier.train

Steps:
  1. Clean labels: identical texts take their majority label, then examples the
     model confidently disagrees with in cross-validation are dropped (likely
     wrong labels).
  2. TF-IDF on words and on character n-grams (robust to typos, Hinglish, emoji)
     into a logistic regression.
  3. Pick the decision threshold from cross-validated scores so that recall on
     real requests is at least TARGET_RECALL: a missed request is worse than a
     false alarm.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_score, recall_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline, make_union

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "classifier" / "train.csv"
MODEL = HERE / "model.joblib"
TARGET_RECALL = 0.98
SUSPECT_BELOW = 0.10  # cross-validated probability of the given label below this: treat as mislabelled


def normalise(text: str) -> str:
    return " ".join(text.lower().split())


def make_model() -> object:
    features = make_union(
        # Built-in lowercasing only: a custom function here would be pickled by reference and break loading.
        TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True),
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True),
    )
    return make_pipeline(features, LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000))


def load() -> tuple[list[str], np.ndarray]:
    with DATA.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    votes: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        votes[normalise(row["text"])][row["label"]] += 1
    texts = [row["text"] for row in rows]
    # Majority label for identical texts (ties count as a request: missing one is worse)
    labels = []
    for row in rows:
        count = votes[normalise(row["text"])]
        labels.append(1 if count["request"] >= count["not_request"] else 0)
    return texts, np.array(labels)


def main() -> None:
    texts, y = load()
    print(f"{len(texts)} rows, {len(set(map(normalise, texts)))} distinct texts, {y.mean():.0%} requests")
    with DATA.open(newline="", encoding="utf-8") as f:
        raw = np.array([row["label"] == "request" for row in csv.DictReader(f)])
    print(f"majority vote changed {int((raw != y).sum())} labels")

    folds = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    proba = cross_val_predict(make_model(), texts, y, cv=folds, method="predict_proba")[:, 1]
    given = np.where(y == 1, proba, 1 - proba)
    keep = given >= SUSPECT_BELOW
    print(f"dropped {int((~keep).sum())} more rows the model confidently disagrees with:")
    for text, label in zip(np.array(texts)[~keep], y[~keep]):
        print(f"    labelled {'request' if label else 'not_request':<12} {text}")
    texts = [t for t, k in zip(texts, keep) if k]
    y = y[keep]

    proba = cross_val_predict(make_model(), texts, y, cv=folds, method="predict_proba")[:, 1]
    threshold = 0.5
    for candidate in np.arange(0.5, 0.0, -0.01):
        threshold = float(candidate)
        if recall_score(y, proba >= candidate) >= TARGET_RECALL:
            break
    predicted = proba >= threshold
    print(f"threshold {threshold:.2f}: cross-validated recall {recall_score(y, predicted):.3f}, "
          f"precision {precision_score(y, predicted):.3f}, accuracy {(predicted == y).mean():.3f}")

    model = make_model().fit(texts, y)
    joblib.dump({"model": model, "threshold": threshold}, MODEL)
    print(f"saved {MODEL.relative_to(HERE.parent)} ({MODEL.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
