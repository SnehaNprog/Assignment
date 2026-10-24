"""Every message we send a vendor is built here, from ticket fields only.

The model's draft is never forwarded. That is the main privacy defence: a
member's own words (names, numbers, family) cannot leak if they are never
copied. Only the details the house rule allows go out: venue, date, time,
guests, occasion in general words, seating and dietary needs, and the house name.
"""
from __future__ import annotations

import re
from datetime import date

from world.parse import fmt_date, fmt_time

# General words we may pass on, found in the member's message.
_EXTRAS = [
    (r"\bbirthday\b|\bbday\b", "a birthday celebration"),
    (r"\banniversary\b", "an anniversary"),
    (r"\bbusiness\b|\bclient dinner\b", "a business meal"),
    (r"\bcorner table\b", "a corner table if possible"),
    (r"\bwindow\b", "a window table if possible"),
    (r"\bsea view\b|\bwith a view\b|\bview\b", "a table with a view if possible"),
    (r"\boutdoor\b|\boutside\b|\bterrace seating\b", "outdoor seating if possible"),
    (r"\bquiet\b", "a quiet table if possible"),
    (r"\bprivate room\b", "a private room if possible"),
    (r"\bhigh ?chair\b|\bkids?\b|\bchildren\b", "a child in the party"),
    (r"\bwheelchair\b|\baccessible\b", "step-free access"),
    (r"\bvegan\b", "vegan options"),
    (r"\bvegetarian\b|\bveg\b", "vegetarian options"),
    (r"\bjain\b", "Jain food options"),
    (r"\bgluten\b", "a gluten-free option"),
    (r"\bnut allerg\w*|\bno nuts\b", "a nut allergy"),
    (r"\bshellfish\b", "no shellfish"),
]


def allowed_extras(text: str) -> list[str]:
    low = text.lower()
    return [label for pattern, label in _EXTRAS if re.search(pattern, low)]


def _when(ticket: dict) -> str:
    return f"{fmt_date(date.fromisoformat(ticket['date']))} at {fmt_time(ticket['time'])}"


def job_message(ticket: dict, booking_name: str) -> str:
    lines = [f"Hello, please book a table at {ticket['venue']} on {_when(ticket)} "
             f"for {ticket['party_size']} guests, under the name {booking_name}."]
    if ticket.get("extras"):
        lines.append("Notes: " + "; ".join(ticket["extras"]) + ".")
    lines.append(f"Our reference: {ticket['ticket_id']}. Please confirm on this thread. Thank you.")
    return "\n".join(lines)


def reminder_message(ticket: dict, booking_name: str) -> str:
    return (f"Hello, following up on our request {ticket['ticket_id']}: {ticket['venue']}, {_when(ticket)}, "
            f"{ticket['party_size']} guests, under the name {booking_name}. Could you let us know the status? Thank you.")


def cancel_message(ticket: dict, booking_name: str) -> str:
    return (f"Hello, please cancel our request {ticket['ticket_id']}: {ticket['venue']}, {_when(ticket)}, "
            f"{ticket['party_size']} guests, under the name {booking_name}. Thank you.")
