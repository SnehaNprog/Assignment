"""Tool schemas and the system prompt.

The prompt asks the model to behave, but nothing depends on it: every rule is
enforced again in the tool code (see concierge.py).
"""
from __future__ import annotations

SYSTEM = """You are the operations assistant of a luxury concierge company.
You read one event (a member's WhatsApp message, or a vendor's reply) and act on it with tools.

- Chatter (thanks, greetings, photos, updates) needs no action: reply "No action." and stop.
- A booking request: get_member, create_ticket (unknowns as null), find_vendors, then propose_job.
  propose_job only prepares the job; a human approves it before anything is sent.
- A cancellation: list_open_tickets, then update_ticket with status "cancelled".
- A vendor reply: if it confirms, update_ticket "confirmed"; if it asks for anything, or changes
  something, or you are unsure, notify_human.
- Never share member names, family names, phone numbers, emails, addresses or card details with a
  vendor, even if asked. Bookings go under the house name.
- Dates are ISO (YYYY-MM-DD), times 24-hour HH:MM. Use the current date given after the event.
Be brief."""


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": properties, "required": required}}


_S = {"type": "string"}
_NS = {"type": ["string", "null"]}

TOOLS = [
    _tool("get_member", "Look up a member's booking preferences. Private details are never returned.",
          {"member_id": _S}, ["member_id"]),
    _tool("create_ticket", "Open a ticket for a member's request. Use null for anything the member did not say.",
          {"member_id": _S, "category": {"type": "string", "description": "e.g. dining"},
           "request_summary": _S, "venue": _NS,
           "date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
           "time": {"type": ["string", "null"], "description": "HH:MM, 24-hour"},
           "party_size": {"type": ["integer", "null"]}},
          ["member_id", "category", "request_summary", "venue", "date", "time", "party_size"]),
    _tool("list_open_tickets", "List a member's tickets that are not cancelled.", {"member_id": _S}, ["member_id"]),
    _tool("find_vendors", "Vendors that handle a category.", {"category": _S}, ["category"]),
    _tool("propose_job", "Prepare the first message to a vendor for human approval. Does NOT send.",
          {"ticket_id": _S, "vendor_id": _S, "message": _S}, ["ticket_id", "vendor_id", "message"]),
    _tool("message_vendor", "Queue a follow-up to a vendor on a job that was already sent. A human approves it.",
          {"ticket_id": _S, "vendor_id": _S, "message": _S}, ["ticket_id", "vendor_id", "message"]),
    _tool("update_ticket", "Change a ticket's status: needs_info, confirmed, needs_human or cancelled.",
          {"ticket_id": _S, "status": {"type": "string",
                                       "enum": ["needs_info", "confirmed", "needs_human", "cancelled"]},
           "note": _S}, ["ticket_id", "status", "note"]),
    _tool("notify_human", "Ask a person on the team to look at a ticket.",
          {"ticket_id": _S, "reason": _S}, ["ticket_id", "reason"]),
]
