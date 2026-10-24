"""Calls, tokens, cost and time per scenario, with the chatter pre-filter off (before) and on (after).

    python bench.py            # the fake model: token counts are ESTIMATES (characters / 4)
    python bench.py --live     # real Claude (needs ANTHROPIC_API_KEY): real tokens and cost

Besides the 11 scenarios it replays a "day" of member messages sampled from
data/classifier/train.csv, which is where skipping the model on chatter shows.
"""
from __future__ import annotations

import argparse
import csv
import random
import time
from pathlib import Path

from agent import Concierge
from world import SCENARIOS, FakeAnthropic, World

DAY_SIZE = 300


def make(scenario: dict, live: bool, model: str, prefilter: bool):
    world = World(bookbot=scenario.get("bookbot", "correct"), flaky=scenario.get("flaky", False))
    if live:
        import anthropic
        client = anthropic.Anthropic()
    else:
        client = FakeAnthropic(world.clock, world.data.house["venues"], quirks=scenario.get("quirks"))
    concierge = Concierge(world, client, model=model, prefilter=prefilter)
    world.attach(concierge)
    return world, concierge


def run_scenario(name: str, live: bool, model: str, prefilter: bool) -> dict:
    scenario = SCENARIOS[name]
    world, concierge = make(scenario, live, model, prefilter)
    started = time.perf_counter()
    for step in scenario["steps"]:
        if step[0] == "say":
            world.member_says(step[1], step[2])
        elif step[0] == "wait":
            world.advance(step[1])
        elif step[0] == "approve_all":
            for p in concierge.pending_proposals():
                concierge.approve(p["proposal_id"], approver="bench")
    return {**concierge.usage(), "wall_seconds": time.perf_counter() - started}


def run_day(live: bool, model: str, prefilter: bool) -> dict:
    """DAY_SIZE member messages spread over the six groups, one a minute."""
    path = Path(__file__).resolve().parent / "data" / "classifier" / "train.csv"
    with path.open(newline="", encoding="utf-8") as f:
        texts = [r["text"] for r in random.Random(1).sample(list(csv.DictReader(f)), DAY_SIZE)]
    world, concierge = make({}, live, model, prefilter)
    groups = sorted(world.data.groups)
    started = time.perf_counter()
    for i, text in enumerate(texts):
        world.member_says(groups[i % len(groups)], text)
        world.advance(1)
    return {**concierge.usage(), "wall_seconds": time.perf_counter() - started}


def row(name: str, u: dict) -> str:
    return (f"| {name} | {u['calls']} | {u['input_tokens']:,} | {u['output_tokens']:,} | ${u['cost_usd']:.4f} "
            f"| {u['model_seconds']:.2f} | {u['wall_seconds']:.2f} |")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", default="claude-haiku-5-5")
    args = parser.parse_args()
    kind = "real Claude: real tokens and cost" if args.live else "fake model: tokens are estimates (chars / 4)"
    header = ("| scenario | calls | input tok | output tok | cost | model s | wall s |\n"
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |")

    totals = {}
    for prefilter in (False, True):
        label = "after: pre-filter ON" if prefilter else "before: pre-filter OFF"
        print(f"\n### {label} ({args.model}, {kind})\n\n{header}")
        total = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "model_seconds": 0.0, "wall_seconds": 0.0}
        for name in SCENARIOS:
            u = run_scenario(name, args.live, args.model, prefilter)
            print(row(name, u))
            for key in total:
                total[key] += u[key]
        print(row("**all 11 scenarios**", total))
        day = run_day(args.live, args.model, prefilter)
        print(row(f"**a day: {DAY_SIZE} member messages**", day))
        totals[prefilter] = (total, day)

    print("\n### the change: skip the model when the small classifier says chatter\n")
    print("| workload | calls before → after | cost before → after | saved |\n| --- | --- | --- | ---: |")
    for i, name in enumerate(("11 scenarios", f"{DAY_SIZE}-message day")):
        b, a = totals[False][i], totals[True][i]
        saved = 1 - a["cost_usd"] / b["cost_usd"] if b["cost_usd"] else 0
        print(f"| {name} | {b['calls']} → {a['calls']} | ${b['cost_usd']:.4f} → ${a['cost_usd']:.4f} | {saved:.0%} |")


if __name__ == "__main__":
    main()
