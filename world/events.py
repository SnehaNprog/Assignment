"""How events are written down for the model.

Use these functions to turn an event into the text of a user message. The fake
model reads the first line (the header) to understand what happened, so keep the
header exactly as produced here. You may add more context AFTER the event text
(member preferences, open tickets, rules, anything you like).
"""
from __future__ import annotations

import re


def render_group_message(group_id: str, member_id: str, sender: str, text: str) -> str:
    return f"[group_message] group_id={group_id} member_id={member_id} sender={sender!r}\n{text}"


def render_vendor_reply(vendor_id: str, ticket_id: str, member_id: str, text: str) -> str:
    return f"[vendor_reply] vendor_id={vendor_id} ticket_id={ticket_id} member_id={member_id}\n{text}"


def render_timer(ticket_id: str, vendor_id: str, member_id: str, minutes_waiting: int) -> str:
    return (f"[timer] ticket_id={ticket_id} vendor_id={vendor_id} member_id={member_id} "
            f"minutes_waiting={minutes_waiting}\nNo reply from the vendor yet.")


_HEADER = re.compile(r"^\[(group_message|vendor_reply|timer)\]\s*(.*)$")
_PAIR = re.compile(r"(\w+)=('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|\S+)")


def parse_event(text: str) -> dict | None:
    """Reverse of the render functions. Returns {"kind", fields..., "body"} or None."""
    first, _, rest = text.partition("\n")
    m = _HEADER.match(first.strip())
    if not m:
        return None
    event = {"kind": m.group(1)}
    for key, value in _PAIR.findall(m.group(2)):
        if value[:1] in "'\"":
            value = value[1:-1]
        event[key] = value
    # The body is the event text; anything the agent appended after a blank
    # "---" line is extra context and is ignored by the fake model.
    event["body"] = rest.split("\n---", 1)[0].strip()
    return event
