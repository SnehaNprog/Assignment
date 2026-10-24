"""Shared test helpers: run a story against the agent, and a strict leak check."""
from __future__ import annotations

import re

from agent import Concierge
from world import SCENARIOS, FakeAnthropic, World


def build(bookbot: str = "correct", quirks=None, flaky: bool = False, client=None):
    world = World(bookbot=bookbot, flaky=flaky)
    client = client or FakeAnthropic(world.clock, world.data.house["venues"], quirks=quirks)
    concierge = Concierge(world, client)
    world.attach(concierge)
    return world, concierge


def approve_all(concierge, approver: str = "test-human") -> list[dict]:
    return [concierge.approve(p["proposal_id"], approver=approver) for p in concierge.pending_proposals()]


def run_scenario(name: str):
    s = SCENARIOS[name]
    world, concierge = build(s["bookbot"], s.get("quirks"), s.get("flaky", False))
    for step in s["steps"]:
        if step[0] == "say":
            world.member_says(step[1], step[2])
        elif step[0] == "wait":
            world.advance(step[1])
        elif step[0] == "approve_all":
            approve_all(concierge)
    return world, concierge


def private_values(member: dict) -> list[str]:
    """Everything about a member that must never reach a vendor. Independent of agent/privacy.py."""
    values = [member["name"], member["email"], member["card"]["last4"], member["card"]["expiry"]]
    values += member["name"].split()
    for person in member.get("family", []):
        values += [person["name"], *person["name"].split()]
    values += [part.strip() for part in member["address"].split(",") if len(part.strip()) > 4]
    return values


def leaks(text: str, members: dict) -> list[str]:
    found = []
    flat_digits = re.sub(r"\D", "", text)
    for member in members.values():
        for value in private_values(member):
            if re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I):
                found.append(value)
        phone = re.sub(r"\D", "", member["phone"])[-10:]
        if phone[-8:] in flat_digits:  # any spacing, with or without +91
            found.append(member["phone"])
    if re.search(r"[\w.+-]+@[\w-]+\.\w+", text.replace("bookings@concierge.example", "")):
        found.append("an email address")
    for digits in re.findall(r"\d[\d\s-]{8,}\d", text.replace("+91 22 4000 0000", "")):
        found.append(f"a long number: {digits}")
    return found


def all_leaks(world) -> list[str]:
    return [leak for out in world.transport.sent for leak in leaks(out["text"], world.data.members)]
