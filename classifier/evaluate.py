"""How well the classifier does on phrasings it never saw, and how fast it is.

    python -m classifier.evaluate

classifier/unseen.csv is 60 messages we wrote by hand in a different style from
train.csv (new services, slang, Hinglish, typos). It is small, so treat the
numbers as a rough check, not a benchmark.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

from agent.gate import _HINT
from classifier.predict import predict

UNSEEN = Path(__file__).resolve().parent / "unseen.csv"


def report(name: str, truth: list[str], guess: list[str]) -> None:
    pairs = list(zip(truth, guess))
    tp = sum(t == g == "request" for t, g in pairs)
    fn = sum(t == "request" != g for t, g in pairs)
    fp = sum(g == "request" != t for t, g in pairs)
    accuracy = sum(t == g for t, g in pairs) / len(pairs)
    print(f"{name:<28} accuracy {accuracy:.2f}  recall {tp / (tp + fn):.2f}  precision {tp / max(1, tp + fp):.2f}  "
          f"missed requests {fn}  false alarms {fp}")


def main() -> None:
    with UNSEEN.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    texts, truth = [r["text"] for r in rows], [r["label"] for r in rows]

    predict(texts[:1])  # load the model once, outside the timing
    started = time.perf_counter()
    model = predict(texts * 50)[: len(texts)]
    per_1000 = (time.perf_counter() - started) / (len(texts) * 50) * 1000
    keywords = ["request" if _HINT.search(t) else "not_request" for t in texts]
    gate = ["request" if m == "request" or k == "request" else "not_request" for m, k in zip(model, keywords)]

    report("classifier alone", truth, model)
    report("keywords alone", truth, keywords)
    report("agent gate (either)", truth, gate)
    print(f"classifier speed: {per_1000 * 1000:.1f} ms per 1,000 messages on this CPU")
    print("\nmisses and false alarms of the classifier:")
    for text, t, m in zip(texts, truth, model):
        if t != m:
            print(f"    truth {t:<12} said {m:<12} {text}")


if __name__ == "__main__":
    main()
