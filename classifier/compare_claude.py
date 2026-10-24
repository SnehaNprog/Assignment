"""The small model against Claude on 100 messages: accuracy, cost per 1,000 messages, speed.

    python -m classifier.compare_claude            # needs ANTHROPIC_API_KEY for the Claude column
    python -m classifier.compare_claude --estimate # no key: Claude's numbers are estimated, and say so

The 100 messages: all 60 hand-written unseen ones plus 40 sampled from train.csv.
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import time
from pathlib import Path

from classifier.predict import predict
from world.pricing import cost_usd

HERE = Path(__file__).resolve().parent
MODEL = "claude-haiku-5-5"
PROMPT = ("You triage WhatsApp messages from members of a concierge service. Reply with exactly one word: "
          "'request' if the member wants us to do, check, change or cancel something, else 'not_request'.")
# Used only with --estimate: about 70 prompt tokens + the message, 3 output tokens, typical Haiku latency.
EST_INPUT_TOKENS, EST_OUTPUT_TOKENS, EST_SECONDS = 90, 3, 0.5


def sample() -> tuple[list[str], list[str]]:
    with (HERE / "unseen.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with (HERE.parent / "data" / "classifier" / "train.csv").open(newline="", encoding="utf-8") as f:
        rows += random.Random(7).sample(list(csv.DictReader(f)), 40)
    return [r["text"] for r in rows], [r["label"] for r in rows]


def ask_claude(texts: list[str]) -> tuple[list[str], dict]:
    import anthropic
    client = anthropic.Anthropic()
    labels, tokens_in, tokens_out = [], 0, 0
    started = time.perf_counter()
    for text in texts:
        r = client.messages.create(model=MODEL, max_tokens=5, system=PROMPT, messages=[{"role": "user", "content": text}])
        answer = "".join(getattr(b, "text", "") for b in r.content).strip().lower()
        labels.append("not_request" if "not" in answer else "request")
        tokens_in += r.usage.input_tokens
        tokens_out += r.usage.output_tokens
    seconds = time.perf_counter() - started
    return labels, {"cost": cost_usd(MODEL, tokens_in, tokens_out), "seconds": seconds, "measured": True}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--estimate", action="store_true")
    args = parser.parse_args()
    texts, truth = sample()

    started = time.perf_counter()
    ours = predict(texts)
    our_seconds = time.perf_counter() - started
    acc = lambda guess: sum(g == t for g, t in zip(guess, truth)) / len(truth)
    missed = lambda guess: sum(t == "request" != g for g, t in zip(guess, truth))
    print(f"{'':<18}{'accuracy':>9}{'missed req':>12}{'$ / 1,000 msgs':>16}{'ms / msg':>10}")
    print(f"{'small model':<18}{acc(ours):>9.2f}{missed(ours):>12}{0:>16.4f}{our_seconds / len(texts) * 1000:>10.2f}")

    if args.estimate or not os.environ.get("ANTHROPIC_API_KEY"):
        per_1000 = cost_usd(MODEL, EST_INPUT_TOKENS * 1000, EST_OUTPUT_TOKENS * 1000)
        print(f"{MODEL + ' (est.)':<18}{'n/a':>9}{'n/a':>12}{per_1000:>16.4f}{EST_SECONDS * 1000:>10.0f}")
        print("\nClaude numbers are ESTIMATES (no API key): "
              f"{EST_INPUT_TOKENS} input + {EST_OUTPUT_TOKENS} output tokens per message at world/pricing.py rates, "
              f"~{EST_SECONDS:.1f}s per call. Accuracy was not measured.")
        return
    theirs, stats = ask_claude(texts)
    print(f"{MODEL:<18}{acc(theirs):>9.2f}{missed(theirs):>12}{stats['cost'] / len(texts) * 1000:>16.4f}"
          f"{stats['seconds'] / len(texts) * 1000:>10.0f}")


if __name__ == "__main__":
    main()
