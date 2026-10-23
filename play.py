"""Run a scenario and watch what your agent does.

    python play.py                       list the scenarios
    python play.py riya_corner_table     run one, with a readable trace
    python play.py all                   run every scenario, one summary line each
    python play.py all --live            same, against real Claude (needs ANTHROPIC_API_KEY)
    python play.py riya_corner_table --live --model claude-sonnet-5-5
"""
from __future__ import annotations

import argparse
import sys

from world import SCENARIOS, FakeAnthropic, World
from world.privacy import find_leaks


def make_client(world: World, scenario: dict, live: bool):
    if live:
        import anthropic  # pip install anthropic
        return anthropic.Anthropic()
    return FakeAnthropic(world.clock, world.data.house["venues"], quirks=scenario.get("quirks"))


def run(name: str, live: bool, model: str, verbose: bool) -> dict:
    from agent import Concierge

    scenario = SCENARIOS[name]
    world = World(bookbot=scenario["bookbot"], flaky=scenario.get("flaky", False))
    concierge = Concierge(world, make_client(world, scenario, live), model=model)
    world.attach(concierge)

    say = print if verbose else (lambda *a, **k: None)
    say(f"\n=== {name} ===\n{scenario['about']}\n")
    shown = 0
    for step in scenario["steps"]:
        if step[0] == "say":
            world.member_says(step[1], step[2])
        elif step[0] == "wait":
            world.advance(step[1])
        elif step[0] == "approve_all":
            for p in concierge.pending_proposals():
                say(f"  [{world.clock.now:%H:%M}] PROPOSAL {p['proposal_id']} for {p['ticket_id']} to {p['vendor_id']}")
                say("      would send:  " + p["outbound_message"].replace("\n", "\n                   "))
                say("      held back:   " + (", ".join(p["held_back"]) or "nothing"))
                result = concierge.approve(p["proposal_id"], approver="demo-human")
                say(f"      approved ->  {result}")
        for entry in world.log[shown:]:
            say(_line(entry))
        shown = len(world.log)

    sent = world.transport.sent
    leaks = []
    for out in sent:
        ticket = next((t for t in concierge.tickets() if t["ticket_id"] == out["ticket_id"]), None)
        member = world.data.members.get(ticket["member_id"]) if ticket else None
        if member:
            leaks += find_leaks(out["text"], member)

    say("\n  Tickets:")
    for t in concierge.tickets():
        say(f"    {t['ticket_id']}  {t['status']:<18} {t.get('venue')} {t.get('date')} {t.get('time')} x{t.get('party_size')}")
    say("  Alerts for a human:")
    for a in concierge.alerts() or [{"ticket_id": "-", "reason": "none"}]:
        say(f"    {a['ticket_id']}: {a['reason']}")
    say(f"  Messages that left the building: {len(sent)}")
    say(f"  Basic leak check: {'LEAKED ' + '; '.join(leaks) if leaks else 'nothing obvious (our review checks much more)'}")
    say(f"  Usage: {concierge.usage()}")
    return {"name": name, "sent": len(sent), "leaks": leaks, "tickets": concierge.tickets(),
            "alerts": concierge.alerts(), "usage": concierge.usage()}


def _line(entry: dict) -> str:
    at = f"  [{entry['at']:%H:%M}]"
    if entry["kind"] == "member":
        return f"{at} {entry['sender']} in {entry['group_id']}: {entry['text']}"
    if entry["kind"] == "sent":
        return f"{at} SENT to {entry['vendor_id']} ({entry['ticket_id']}): " + entry["text"].replace("\n", " / ")
    if entry["kind"] == "vendor_reply":
        return f"{at} {entry['vendor_id']} replied ({entry['ticket_id']}): {entry['text']}"
    return f"{at} {entry}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", nargs="?")
    parser.add_argument("--live", action="store_true", help="use real Claude instead of the fake model")
    parser.add_argument("--model", default="claude-haiku-5-5")
    args = parser.parse_args()

    if not args.scenario:
        for name, s in SCENARIOS.items():
            print(f"{name:<32} {s['about']}")
        return
    try:
        if args.scenario == "all":
            for name in SCENARIOS:
                r = run(name, args.live, args.model, verbose=False)
                statuses = ",".join(t["status"] for t in r["tickets"]) or "-"
                print(f"{name:<32} sent={r['sent']}  tickets={statuses:<22} alerts={len(r['alerts'])}  "
                      f"leaks={'YES' if r['leaks'] else 'no'}  cost=${r['usage'].get('cost_usd', 0):.4f}")
        else:
            run(args.scenario, args.live, args.model, verbose=True)
    except NotImplementedError:
        sys.exit("The Concierge in agent/concierge.py is not built yet. That is your job.")


if __name__ == "__main__":
    main()
