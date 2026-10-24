"""The small model: right shape, catches obvious requests, and the agent's gate misses none we wrote."""
import csv
from pathlib import Path

from agent.gate import is_request
from classifier.predict import predict


def test_predict_returns_one_label_per_text():
    out = predict(["Book Koen for Saturday 8pm", "thanks!!", ""])
    assert len(out) == 3 and set(out) <= {"request", "not_request"}


def test_clear_cases():
    assert predict(["Can you book Casa Lumen tonight for 2?", "please cancel the car for tomorrow"]) == ["request"] * 2
    assert predict(["Good morning ☀️", "👍", "ha that's funny"]) == ["not_request"] * 3


def test_the_agent_gate_lets_every_unseen_request_through():
    with (Path(__file__).resolve().parent.parent / "classifier" / "unseen.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    missed = [r["text"] for r in rows if r["label"] == "request" and not is_request(r["text"])]
    assert missed == []
