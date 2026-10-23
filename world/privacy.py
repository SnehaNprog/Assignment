"""A BASIC leak check, used by play.py to flag obvious leaks in what was sent.

It only looks for exact copies of a few fields. Our own review uses a much
stricter check (other phone formats, family names, addresses, card details...).
Passing this check does not mean you are safe.
"""
from __future__ import annotations


def find_leaks(text: str, member: dict) -> list[str]:
    found = []
    low = text.lower()
    for label, value in (("name", member.get("name")), ("phone", member.get("phone")), ("email", member.get("email"))):
        if value and value.lower() in low:
            found.append(f"{label}: {value}")
    return found
